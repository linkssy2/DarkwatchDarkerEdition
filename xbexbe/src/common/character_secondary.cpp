#include "character_secondary.h"
#include "character_runtime.h"
#include "kernel/kernel.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

namespace {
struct Vec { float x = 0, y = 0, z = 0; };
Vec operator+(Vec a, Vec b) { return {a.x+b.x,a.y+b.y,a.z+b.z}; }
Vec operator-(Vec a, Vec b) { return {a.x-b.x,a.y-b.y,a.z-b.z}; }
Vec operator*(Vec a, float b) { return {a.x*b,a.y*b,a.z*b}; }
float Length(Vec a) { return std::sqrt(a.x*a.x+a.y*a.y+a.z*a.z); }
Vec Limit(Vec a, float maximum) { const float n=Length(a); return n>maximum ? a*(maximum/n) : a; }
struct Spring { Vec anchor, speed, offset, velocity; };
struct Instance {
    uint32_t actor=0, serial=0, component=0, matrices=0;
    float clock=0;
    bool moving=false;
    std::array<Spring,4> springs{};
};
std::array<Instance,2> instances{};
constexpr unsigned parents[]{8,8,0,0,0,0};
constexpr unsigned poseBones[]{8,8,0,0,4,1};
constexpr unsigned springIndices[]{0,1,2,3,2,3};
constexpr Vec centers[]{{.0340607145f,.1280383572f,.075f},{.0340607145f,.1280383572f,-.075f},
                        {.085f,-.015f,-.105f},{-.085f,-.015f,-.105f}};

bool Span(const uint8_t* base, uint64_t address, uint64_t bytes) {
    if (!base || !address || !bytes || address+bytes>(uint64_t(1)<<32)) return false;
    for (uint64_t page=address&~uint64_t(mem::kPage-1);page<address+bytes;page+=mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t address, T& value) {
    if (!Span(base,address,sizeof(T))) return false;
    std::memcpy(&value,base+address,sizeof(T)); return true;
}
bool Name(const uint8_t* base, uint32_t actor) {
    uint32_t handle;
    if (!Read(base,uint64_t(actor)+0x50,handle) || !handle) return false;
    for (const char* expected : {"CassidySpectralSolo","CassidySpectralPlayerTwo"}) {
        const size_t bytes=std::strlen(expected)+1;
        if (Span(base,uint64_t(handle)+2,bytes) && !std::memcmp(base+handle+2,expected,bytes)) return true;
    }
    return false;
}
bool Matrix(const float* matrix) {
    for (unsigned row=0;row<4;++row) for (unsigned axis=0;axis<3;++axis)
        if (!std::isfinite(matrix[row*4+axis]) || std::abs(matrix[row*4+axis])>1000000) return false;
    for (unsigned row=0;row<3;++row) {
        const float n=Length({matrix[row*4],matrix[row*4+1],matrix[row*4+2]});
        if (n<.01f || n>100.f) return false;
    }
    return true;
}
Vec Position(const float* matrix) { return {matrix[12],matrix[13],matrix[14]}; }
Vec Anchor(const float* matrix, Vec center) {
    // A longer inertial lever makes turns readable without amplifying translation.
    center=center*2.f;
    return Position(matrix)+Vec{matrix[0],matrix[1],matrix[2]}*center.x+
        Vec{matrix[4],matrix[5],matrix[6]}*center.y+Vec{matrix[8],matrix[9],matrix[10]}*center.z;
}

void Advance(Spring& spring, Vec anchor, float dt, bool moving, float maximum) {
    const Vec speed=(anchor-spring.anchor)*(1.f/dt);
    const Vec force=moving ? Limit((speed-spring.speed)*(1.f/dt),80.f)*-.7f : Vec{};
    spring.anchor=anchor; spring.speed=speed;
    // Bounded substeps keep the same spring stable at high FPS and after a slow frame.
    const unsigned steps=unsigned(std::ceil(dt*240.f));
    // Soft tissue can lag and rebound visibly, with displacement capped below.
    const float h=dt/steps, omega=14.f, damping=2.f*.45f*omega;
    for (unsigned i=0;i<steps;++i) {
        const Vec acceleration=force-spring.offset*(omega*omega)-spring.velocity*damping;
        spring.velocity=Limit(spring.velocity+acceleration*h,.6f);
        spring.offset=Limit(spring.offset+spring.velocity*h,maximum);
    }
}
} // namespace

void DarkwatchCharacterSecondaryReset() { instances={}; }

void DarkwatchCharacterSecondary(X86Context& ctx, uint8_t* base) {
    uint32_t type,actor,serial,animator,pose,parent_pose,hierarchy,count,matrices,parent_map;
    float clock;
    if (base!=kernel::g_base || ctx.esi!=ctx.edi+0x84 ||
        !Read(base,ctx.edi,type) || type!=0x41D258 ||
        !Read(base,uint64_t(ctx.edi)+0x0C,actor) ||
        !DarkwatchCharacterIsCassidyPlayer(base,actor) || !Name(base,actor) ||
        !Read(base,uint64_t(actor)+0x70,serial) ||
        !Read(base,uint64_t(ctx.edi)+0x60,animator) || !animator ||
        !Read(base,uint64_t(animator)+0x58,pose) || !pose ||
        !Read(base,pose,parent_pose) || parent_pose ||
        !Read(base,uint64_t(pose)+0x10,hierarchy) || !hierarchy ||
        !Read(base,uint64_t(hierarchy)+4,count) || count!=51 ||
        !Read(base,uint64_t(hierarchy)+8,matrices) || !Span(base,matrices,51*64) ||
        !Read(base,uint64_t(pose)+8,parent_map) || !Span(base,parent_map,51*4) ||
        !Read(base,0x4B7AE4,clock) || !std::isfinite(clock)) return;
    for (unsigned i=0;i<6;++i) {
        uint32_t parent;
        if (!Read(base,uint64_t(parent_map)+(22+i)*4,parent) || parent!=parents[i]) return;
    }
    std::array<std::array<float,16>,6> source;
    std::array<Vec,4> anchors;
    for (unsigned i=0;i<6;++i) {
        std::memcpy(source[i].data(),base+matrices+poseBones[i]*64,64);
        if (!Matrix(source[i].data())) return;
        if (i<4) anchors[i]=Anchor(source[i].data(),centers[i]);
    }
    auto slot=std::find_if(instances.begin(),instances.end(),[actor](const Instance& s){return s.actor==actor;});
    if (slot==instances.end()) slot=std::find_if(instances.begin(),instances.end(),[](const Instance& s){return !s.actor;});
    if (slot==instances.end()) slot=std::min_element(instances.begin(),instances.end(),
        [](const Instance& a,const Instance& b){return a.clock<b.clock;});
    auto& state=*slot;
    const float dt=clock-state.clock;
    bool reset=state.actor!=actor || state.serial!=serial || state.component!=ctx.edi ||
        state.matrices!=matrices || dt<0 || dt>.15f || (dt>0 && dt<.000001f);
    for (unsigned i=0;i<4;++i) reset=reset || Length(anchors[i]-state.springs[i].anchor)>.75f;
    if (reset) {
        state={actor,serial,ctx.edi,matrices,clock};
        for (unsigned i=0;i<4;++i) state.springs[i].anchor=anchors[i];
    } else if (dt>0) {
        for (unsigned i=0;i<4;++i) Advance(state.springs[i],anchors[i],dt,state.moving,i<2?.065f:.05f);
        state.moving=true; state.clock=clock;
    }
    // The original pose is rebuilt before this seam. Only private body helper bones change.
    for (unsigned i=0;i<6;++i) {
        // Thigh helpers retain the native leg pose and share their hip's displacement.
        const Vec offset=state.springs[springIndices[i]].offset;
        source[i][12]+=offset.x;
        source[i][13]+=offset.y;
        source[i][14]+=offset.z;
        if (Length(offset)>0) {
            // RwMatrix's identity shortcut is invalid after adding a translation.
            uint32_t flags;
            std::memcpy(&flags,&source[i][3],4); flags&=~0x20000u;
            std::memcpy(&source[i][3],&flags,4);
        }
        std::memcpy(base+matrices+(22+i)*64,source[i].data(),64);
    }
}
