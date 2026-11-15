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
float Dot(Vec a, Vec b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
float Length(Vec a) { return std::sqrt(Dot(a,a)); }
struct Spring { Vec anchor, offset, velocity; };
constexpr unsigned motionPoints=6;
struct Instance {
    uint32_t actor=0, serial=0, component=0, matrices=0;
    float clock=0;
    std::array<Spring,motionPoints> springs{};
    std::array<Spring,6> simulated{};
    std::array<Vec,6> observedAnchors{}, observedRest{};
    double pending=0;
};
// Keep one history per local player; split-screen draws must not evict each other.
std::array<Instance,4> instances{};
std::array<Instance,64> enemies{};
constexpr Vec bansheeCenters[]{{.0753753904f,.0960187617f,.07f},{.0753753904f,.0960187617f,-.07f}};
constexpr unsigned parents[]{8,8,0,0,0,0};
constexpr unsigned poseBones[]{8,8,0,0,4,1};
constexpr unsigned springIndices[]{0,1,2,3,4,5};
constexpr Vec centers[]{{.0340607145f,.1280383572f,.075f},{.0340607145f,.1280383572f,-.075f},
                        {.10f,-.08f,-.09f},{-.10f,-.08f,-.09f}};
// The same cheek centers transformed by the source model's thigh 4/1 inverse binds.
// Sampling each animated leg adds step/turn inertia that a pelvis-only anchor misses.
constexpr Vec thighCenters[]{{.0670377828f,.0997243593f,-.0215932884f},
                              {.0669885149f,.0997262975f,.0220732757f}};
constexpr Vec kawaiiCenters[]{centers[0],centers[1],centers[2],centers[3],thighCenters[0],thighCenters[1]};
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
bool Name(const uint8_t* base, uint32_t actor, bool& bossTala, bool& banshee) {
    uint32_t handle;
    if (!Read(base,uint64_t(actor)+0x50,handle) || !handle) return false;
    constexpr const char* names[]{"CassidySpectralSolo","CassidySpectralPlayerTwo","BossTalaSolo","BossTalaCoop","Banshee","SuperBanshee"};
    for (unsigned i=0;i<std::size(names);++i) {
        const char* expected=names[i];
        const size_t bytes=std::strlen(expected)+1;
        if (Span(base,uint64_t(handle)+2,bytes) && !std::memcmp(base+handle+2,expected,bytes)) {
            bossTala=i==2 || i==3; banshee=i>=4;
            return true;
        }
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
void CorrectNeck(uint8_t* base, uint32_t actor, uint32_t count, uint32_t matrices, uint32_t parent_map) {
    float neck, head;
    if ((count != 22 && count != 51) || !DarkwatchCharacterNeckLengths(base, actor, neck, head)) return;
    std::array<std::array<float,16>,4> chain{};
    for (unsigned i=0;i<4;++i) {
        std::memcpy(chain[i].data(),base+matrices+(8+i)*64,64);
        uint32_t parent;
        if (!Matrix(chain[i].data()) || !Read(base,uint64_t(parent_map)+(8+i)*4,parent) || parent!=7+i) return;
    }
    const Vec segments[]{Position(chain[1].data())-Position(chain[0].data()),
                         Position(chain[2].data())-Position(chain[1].data())};
    const float lengths[]{neck,head}; Vec shifts[2]{};
    for (unsigned i=0;i<2;++i) {
        const auto& m=chain[i];
        const float scale=Length({m[0],m[1],m[2]});
        // Preserve uniform actor scaling; reject malformed/nonuniform skeleton bases.
        if (std::abs(Length({m[4],m[5],m[6]})-scale)>scale*.001f ||
            std::abs(Length({m[8],m[9],m[10]})-scale)>scale*.001f) return;
        const float actual=Length(segments[i]), wanted=lengths[i]*scale;
        if (!std::isfinite(actual) || actual<wanted*.25f || actual>wanted*4.f) return;
        if (std::abs(actual-wanted)>scale*.000002f) shifts[i]=segments[i]*(wanted/actual-1.f);
    }
    for (unsigned i=1;i<4;++i) {
        const Vec shift=shifts[0]+(i>=2?shifts[1]:Vec{});
        if (Length(shift)==0) continue;
        auto& m=chain[i];m[12]+=shift.x;m[13]+=shift.y;m[14]+=shift.z;
        uint32_t flags;std::memcpy(&flags,&m[3],4);flags&=~0x20000u;std::memcpy(&m[3],&flags,4);
        std::memcpy(base+matrices+(8+i)*64,m.data(),64);
    }
}

Vec RestVector(const float* matrix, Vec center) {
    return Vec{matrix[0],matrix[1],matrix[2]}*center.x+
        Vec{matrix[4],matrix[5],matrix[6]}*center.y+Vec{matrix[8],matrix[9],matrix[10]}*center.z;
}
// Adapted from KawaiiPhysics SimulateModifyBones (MIT, pafuhana1213).
// Pinned source and changes: docs/KAWAII_PROTOTYPE.md; license: licenses/KawaiiPhysics.txt.
Vec KawaiiOffset(Vec offset, Vec rest) {
    const float radius=Length(rest),length=Length(rest+offset);
    if (radius<=1e-6f || length<=1e-6f) return {};
    const Vec projected=(rest+offset)*(radius/length);
    // Length alone lets a particle orbit through its anchored skin. Retain the
    // accepted small-motion response, but stop excess inward compression at 30
    // degrees; the surface replay keeps normal bounce and bounds sharp turns.
    constexpr float axialLimit=.8660254038f, lateralLimit=.5f;
    const float axial=Dot(projected,rest)/radius;
    if (axial>=radius*axialLimit) return projected-rest;
    const Vec tangent=projected-rest*(axial/radius);
    const float side=Length(tangent);
    return side>1e-6f ? rest*(axialLimit-1.f)+tangent*(radius*lateralLimit/side) : Vec{};
}
void KawaiiStep(Spring& spring, Vec anchor, float h, Vec rest,
                float stiffness, float damping, float inertia) {
    const Vec previous=spring.offset;
    const Vec motion=anchor-spring.anchor;
    const float retain=std::pow(1.f-damping,60.f*h);
    const float poseRetention=std::pow(1.f-stiffness,60.f*h);
    const Vec candidate=(previous+spring.velocity*(h*retain)-motion*inertia)*poseRetention;
    spring.offset=KawaiiOffset(candidate,rest);
    spring.velocity=(spring.offset-previous)*(1.f/h);
    spring.anchor=anchor;
}

Vec InterpolateVector(Vec a, Vec b, float fraction) {
    return a+(b-a)*fraction;
}
Vec InterpolateRest(Vec a, Vec b, float fraction) {
    const Vec direction=InterpolateVector(a,b,fraction);
    const float length=Length(direction);
    return length>1e-6f ? direction*((Length(a)+(Length(b)-Length(a))*fraction)/length) : b;
}
void AdvanceKawaii(Instance& state, const std::array<Vec,6>& anchors,
                   const std::array<Vec,6>& rests, float dt, bool bossTala, unsigned points=6) {
    constexpr double tick=1.0/240.0;
    const double total=state.pending+dt;
    double next=tick-state.pending;
    unsigned steps=0;
    while(next<=dt+1e-8 && steps<37) {
        const float fraction=std::clamp(float(next/dt),0.f,1.f);
        for(unsigned i=0;i<points;++i) {
            const bool hip=i>=2;
            const float stiffness=hip?(bossTala?.010f:.014f):(bossTala?.012f:.018f);
            const float damping=hip?(bossTala?.07f:.095f):(bossTala?.09f:.12f);
            const float inertia=hip?(bossTala?.05f:.04f):(bossTala?.095f:.075f);
            KawaiiStep(state.simulated[i],InterpolateVector(state.observedAnchors[i],anchors[i],fraction),
                float(tick),InterpolateRest(state.observedRest[i],rests[i],fraction),
                stiffness,damping,inertia);
        }
        next+=tick;
        ++steps;
    }
    state.pending=std::max(0.,total-steps*tick);
    state.observedAnchors=anchors; state.observedRest=rests;
}
} // namespace

void DarkwatchCharacterSecondaryReset() { instances={}; enemies={}; }

void DarkwatchCharacterSecondary(X86Context& ctx, uint8_t* base) {
    uint32_t type,actor,serial,animator,pose,parent_pose,hierarchy,count,matrices,parent_map;
    float clock;
    bool bossTala=false, banshee=false;
    if (base!=kernel::g_base || ctx.esi!=ctx.edi+0x84 ||
        !Read(base,ctx.edi,type) || type!=0x41D258 ||
        !Read(base,uint64_t(ctx.edi)+0x0C,actor) ||
        !Read(base,uint64_t(actor)+0x70,serial) ||
        !Read(base,uint64_t(ctx.edi)+0x60,animator) || !animator ||
        !Read(base,uint64_t(animator)+0x58,pose) || !pose ||
        !Read(base,pose,parent_pose) || parent_pose ||
        !Read(base,uint64_t(pose)+0x10,hierarchy) || !hierarchy ||
        !Read(base,uint64_t(hierarchy)+4,count) || (count!=22 && count!=34 && count!=51) ||
        !Read(base,uint64_t(hierarchy)+8,matrices) || !Span(base,matrices,count*64) ||
        !Read(base,uint64_t(pose)+8,parent_map) || !Span(base,parent_map,count*4) ||
        !Read(base,0x4B7AE4,clock) || !std::isfinite(clock)) return;
    CorrectNeck(base,actor,count,matrices,parent_map);
    if (!Name(base,actor,bossTala,banshee) || count!=(banshee?34u:51u) ||
        (!banshee && !(DarkwatchCharacterIsCassidyPlayer(base,actor) || DarkwatchCharacterIsTalaPlayer(base,actor)))) return;
    const unsigned points=banshee?2:6, first=banshee?32:22;
    for (unsigned i=0;i<points;++i) {
        uint32_t parent;
        if (!Read(base,uint64_t(parent_map)+(first+i)*4,parent) || parent!=(banshee?0:parents[i])) return;
    }
    std::array<std::array<float,16>,6> source{};
    std::array<Vec,motionPoints> anchors{};
    std::array<Vec,6> rests{};
    for (unsigned i=0;i<points;++i) {
        std::memcpy(source[i].data(),base+matrices+(banshee?2:poseBones[i])*64,64);
        if (!Matrix(source[i].data())) return;
        rests[i]=RestVector(source[i].data(),banshee?bansheeCenters[i]:kawaiiCenters[i]);
        anchors[i]=Position(source[i].data())+rests[i];
    }
    // Tala's lower cheek uses thigh donors; one per-side displacement keeps
    // that continuous surface together while its native leg pose still bends.
    if (bossTala) for (unsigned side=0;side<2;++side) {
        anchors[side+2]=(anchors[side+2]+anchors[side+4])*.5f;
        anchors[side+4]=anchors[side+2];
        rests[side+4]=rests[side+2];
    }
    auto* begin=banshee?enemies.data():instances.data();
    auto* end=begin+(banshee?enemies.size():instances.size());
    auto slot=std::find_if(begin,end,[actor](const Instance& s){return s.actor==actor;});
    if (slot==end) slot=std::find_if(begin,end,[](const Instance& s){return !s.actor;});
    if (slot==end) slot=std::min_element(begin,end,
        [](const Instance& a,const Instance& b){return a.clock<b.clock;});
    auto& state=*slot;
    const float dt=clock-state.clock;
    bool reset=state.actor!=actor || state.serial!=serial || state.component!=ctx.edi ||
        state.matrices!=matrices || dt<0 || dt>.15f || (dt>0 && dt<.000001f);
    for (unsigned i=0;i<points;++i) reset=reset || Length(anchors[i]-state.springs[i].anchor)>.75f;
    if (reset) {
        state={actor,serial,ctx.edi,matrices,clock};
        for (unsigned i=0;i<points;++i) state.springs[i].anchor=anchors[i];
        state.simulated=state.springs; state.observedAnchors=anchors;
        state.observedRest=rests;
    } else if (dt>0) {
        AdvanceKawaii(state,anchors,rests,dt,bossTala,points);
        state.clock=clock;
    }
    // Refresh constraints even on same-clock poses without changing simulation history.
    state.springs=state.simulated;
    for(unsigned i=0;i<points;++i)
        state.springs[i].offset=KawaiiOffset(state.springs[i].offset,rests[i]);
    // The original pose is rebuilt before this seam. Only private body helper bones change.
    for (unsigned i=0;i<points;++i) {
        // Helper translations retain the native animated bases.
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
        std::memcpy(base+matrices+(first+i)*64,source[i].data(),64);
    }
}
