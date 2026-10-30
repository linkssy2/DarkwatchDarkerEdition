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
                        {.10f,-.08f,-.09f},{-.10f,-.08f,-.09f}};
// The same cheek centers transformed by the source model's thigh 4/1 inverse binds.
// Sampling each animated leg adds step/turn inertia that a pelvis-only anchor misses.
constexpr Vec thighCenters[]{{.0670377828f,.0997243593f,-.0215932884f},
                              {.0669885149f,.0997262975f,.0220732757f}};
// Both cheeks use the same sagittal rest vector; lateral hinges pull them apart.
constexpr Vec hipRest{0,-.145f,-.09f};
// The lower cheek/thigh collar tolerates less down/forward compression than up/back travel.
constexpr float hipLimit=.030f, hipForwardLimit=.020f, hipLateralLimit=.010f;

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
bool Name(const uint8_t* base, uint32_t actor, bool& bossTala) {
    uint32_t handle;
    if (!Read(base,uint64_t(actor)+0x50,handle) || !handle) return false;
    constexpr const char* names[]{"CassidySpectralSolo","CassidySpectralPlayerTwo","BossTalaSolo","BossTalaCoop"};
    for (unsigned i=0;i<std::size(names);++i) {
        const char* expected=names[i];
        const size_t bytes=std::strlen(expected)+1;
        if (Span(base,uint64_t(handle)+2,bytes) && !std::memcmp(base+handle+2,expected,bytes)) {
            bossTala=i>=2;
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
Vec RestVector(const float* matrix, Vec center) {
    return Vec{matrix[0],matrix[1],matrix[2]}*center.x+
        Vec{matrix[4],matrix[5],matrix[6]}*center.y+Vec{matrix[8],matrix[9],matrix[10]}*center.z;
}
Vec Anchor(const float* matrix, Vec center) {
    // A longer inertial lever makes turns readable without amplifying translation.
    center=center*2.f;
    return Position(matrix)+RestVector(matrix,center);
}

Vec ConstrainedOffset(Vec offset, Vec rest, float maximum) {
    const float radius=Length(rest);
    if (radius<1e-6f) return {};
    const Vec pole=rest*(1.f/radius), candidate=rest+offset;
    const float length=Length(candidate);
    if (length<1e-6f) return {};
    Vec direction=candidate*(1.f/length);
    // DOAXBV's verified rest-length projection; the chord cap retains Darkwatch's bounds.
    const float chord=std::min(maximum,2.f*radius);
    const float minimumCosine=std::clamp(1.f-chord*chord/(2.f*radius*radius),-1.f,1.f);
    const float cosine=std::clamp(Dot(direction,pole),-1.f,1.f);
    if (cosine<minimumCosine) {
        const Vec tangent=direction-pole*cosine;
        const float tangentLength=Length(tangent);
        if (tangentLength<1e-6f) return {};
        direction=pole*minimumCosine+tangent*(std::sqrt(std::max(0.f,1.f-minimumCosine*minimumCosine))/tangentLength);
    }
    return direction*radius-rest;
}

void Advance(Spring& spring, Vec anchor, float dt, bool moving, float maximum, Vec rest, bool fixedLength=true, bool hips=false, bool bossTala=false) {
    const Vec speed=(anchor-spring.anchor)*(1.f/dt);
    const Vec force=moving ? Limit((speed-spring.speed)*(1.f/dt),80.f)*-(bossTala?1.2f:hips?.9f:.7f) : Vec{};
    spring.anchor=anchor; spring.speed=speed;
    // Bounded substeps keep the same spring stable at high FPS and after a slow frame.
    const unsigned steps=unsigned(std::ceil(dt*240.f));
    // Soft tissue can lag and rebound visibly, with displacement capped below.
    const float h=dt/steps, omega=bossTala?11.f:14.f, damping=2.f*(bossTala?.27f:hips?.35f:.45f)*omega;
    for (unsigned i=0;i<steps;++i) {
        const Vec acceleration=force-spring.offset*(omega*omega)-spring.velocity*damping;
        spring.velocity=Limit(spring.velocity+acceleration*h,.6f);
        const Vec previous=spring.offset;
        spring.offset=fixedLength ? ConstrainedOffset(previous+spring.velocity*h,rest,maximum)
                                  : Limit(previous+spring.velocity*h,maximum);
        // Feed the constrained displacement back so a saturated spring cannot store outward speed.
        spring.velocity=Limit((spring.offset-previous)*(1.f/h),.6f);
    }
}
void ConstrainHips(Spring& left, Spring& right, Vec rest, Vec lateral, float dt) {
    const float radius=Length(rest);
    if (radius<1e-6f) { left.offset=right.offset=left.velocity=right.velocity={}; return; }
    const Vec pole=rest*(1.f/radius);
    lateral=lateral-pole*Dot(lateral,pole);
    const float width=Length(lateral);
    if (width<1e-6f) { left.offset=right.offset=left.velocity=right.velocity={}; return; }
    lateral=lateral*(1.f/width);
    // Cross(rest, right) points down/forward in the player's pelvis frame.
    const Vec tangent{pole.y*lateral.z-pole.z*lateral.y,
                      pole.z*lateral.x-pole.x*lateral.z,
                      pole.x*lateral.y-pole.y*lateral.x};
    auto plane=[radius](float chord) {
        chord=std::min(chord,std::sqrt(2.f)*radius);
        return std::max(0.f,radius-chord*chord/(2.f*radius));
    };
    const float backPlane=plane(hipLimit),forwardPlane=plane(hipForwardLimit);
    const float backCone=std::max(0.f,radius*radius-backPlane*backPlane);
    const float forwardCone=std::max(0.f,radius*radius-forwardPlane*forwardPlane);
    const float lateralLimit=std::min(hipLateralLimit,std::sqrt(std::min(backCone,forwardCone)));
    const float x=std::clamp((Dot(left.offset,lateral)+Dot(right.offset,lateral))*.5f,
                             -lateralLimit,lateralLimit);
    const float back=std::sqrt(std::max(0.f,backCone-x*x));
    const float forward=std::sqrt(std::max(0.f,forwardCone-x*x));
    for (Spring* spring:{&left,&right}) {
        const float t=std::clamp(Dot(spring->offset,tangent),-back,forward);
        const float q=x*x+t*t,height=std::sqrt(std::max(0.f,radius*radius-q));
        // Equal lateral movement prevents splay. Separate sagittal arcs preserve
        // each cheek's phase and rest length; opposite travel totals at most 5 cm.
        // Stable sqrt(r*r-q)-r retains tiny settling motion at high frame rates.
        const Vec corrected=lateral*x+tangent*t-pole*(q/(height+radius));
        spring->velocity=Limit(spring->velocity+(corrected-spring->offset)*(1.f/dt),.6f);
        spring->offset=corrected;
    }
}

void AdvanceHips(Spring& left, Spring& right, Vec leftAnchor, Vec rightAnchor,
                 float dt, bool moving, Vec rest, Vec lateral, bool bossTala=false) {
    Spring* springs[]{&left,&right};
    const Vec anchors[]{leftAnchor,rightAnchor};
    Vec forces[2];
    for (unsigned side=0;side<2;++side) {
        auto& spring=*springs[side];
        const Vec speed=(anchors[side]-spring.anchor)*(1.f/dt);
        forces[side]=moving?Limit((speed-spring.speed)*(1.f/dt),80.f)*-(bossTala?2.4f:1.8f):Vec{};
        spring.anchor=anchors[side];spring.speed=speed;
    }
    const unsigned steps=unsigned(std::ceil(dt*240.f));
    const float h=dt/steps,omega=bossTala?11.f:14.f,damping=2.f*(bossTala?.18f:.25f)*omega;
    for (unsigned step=0;step<steps;++step) {
        for (unsigned side=0;side<2;++side) {
            auto& spring=*springs[side];
            const Vec acceleration=forces[side]-spring.offset*(omega*omega)-spring.velocity*damping;
            spring.velocity=Limit(spring.velocity+acceleration*h,.6f);
            const Vec previous=spring.offset;
            spring.offset=ConstrainedOffset(previous+spring.velocity*h,rest,hipLimit);
            spring.velocity=Limit((spring.offset-previous)*(1.f/h),.6f);
        }
        // Couple during the same bounded steps as integration, feeding the
        // correction back into velocity instead of storing an outward impulse.
        ConstrainHips(left,right,rest,lateral,h);
    }
}
} // namespace

void DarkwatchCharacterSecondaryReset() { instances={}; }

void DarkwatchCharacterSecondary(X86Context& ctx, uint8_t* base) {
    uint32_t type,actor,serial,animator,pose,parent_pose,hierarchy,count,matrices,parent_map;
    float clock;
    bool bossTala=false;
    if (base!=kernel::g_base || ctx.esi!=ctx.edi+0x84 ||
        !Read(base,ctx.edi,type) || type!=0x41D258 ||
        !Read(base,uint64_t(ctx.edi)+0x0C,actor) ||
        !(DarkwatchCharacterIsCassidyPlayer(base,actor) || DarkwatchCharacterIsTalaPlayer(base,actor)) || !Name(base,actor,bossTala) ||
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
    for (unsigned i=2;i<4;++i) {
        const Vec pelvis=Position(source[i].data());
        const float* thigh=source[i+2].data();
        const Vec point=Position(thigh)+RestVector(thigh,thighCenters[i-2]);
        // Preserve the existing doubled inertial lever and actor translation.
        // At the authored bind pose the thigh and pelvis anchors coincide.
        const Vec driven=pelvis+(point-pelvis)*2.f;
        anchors[i]=(anchors[i]+driven)*.5f;
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
        for (unsigned i=0;i<2;++i) Advance(state.springs[i],anchors[i],dt,state.moving,.065f,
            RestVector(source[i].data(),centers[i]),true,false,bossTala);
        AdvanceHips(state.springs[2],state.springs[3],anchors[2],anchors[3],dt,state.moving,
                    RestVector(source[2].data(),hipRest),RestVector(source[2].data(),{1,0,0}),bossTala);
        state.moving=true; state.clock=clock;
    }
    // The original pose is rebuilt before this seam. Only private body helper bones change.
    for (unsigned i=0;i<6;++i) {
        // Each thigh follows its own cheek's offset while retaining its native animated basis.
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
