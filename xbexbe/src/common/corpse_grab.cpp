#include "corpse_grab.h"
#include "ragdolls.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <mutex>

namespace {
using Vec = std::array<float, 3>;
struct Grab {
    uint64_t epoch = 0, sample = 0, started = 0, tick = 0;
    uint32_t actor = 0, candidate = 0, corpse = 0, body = 0, world = 0, motion = 0;
    bool down = false, latched = true, toggle = false;
    float distance = 0;
    Vec previous{}, previous_target{};
};
std::array<Grab, 4> grabs;
std::mutex grab_mutex;
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~uint64_t(mem::kPage - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& v) {
    if (!Span(base, at, sizeof(v))) return false;
    std::memcpy(&v, base + at, sizeof(v)); return true;
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t type) {
    uint16_t count = 0; uint32_t entries = 0, result = 0;
    if (!Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, entries) || !Span(base, entries, count * 8)) return 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t item = 0, vt = 0, owner = 0;
        if (!Read(base, uint64_t(entries) + i * 8 + 4, item) || !Read(base, item, vt)) return 0;
        if (vt != type) continue;
        if (result || !Read(base, uint64_t(item) + 12, owner) || owner != actor) return 0;
        result = item;
    }
    return result;
}
bool Finite(const Vec& v) {return std::all_of(v.begin(), v.end(), [](float n){return std::isfinite(n);});}
float Length(const Vec& v) {return std::sqrt(v[0]*v[0]+v[1]*v[1]+v[2]*v[2]);}
void Drop(Grab& g) {g.corpse = g.body = g.world = g.motion = 0; g.distance = 0;}
bool Pose(const uint8_t* base, uint32_t actor, Vec& eye, Vec& forward) {
    uint32_t flags = 0, phase = 0, manager = 0; uint8_t enabled = 0, inhibited = 0;
    const auto control = Component(base, actor, 0x41F878);
    return control && Component(base, actor, 0x4227A4) &&
        Read(base, uint64_t(actor)+0x90, flags) && !(flags & 2) &&
        Read(base, 0x4B7A4C, phase) && !(phase >= 1 && phase <= 3) &&
        Read(base, 0x4AC174, manager) && manager &&
        Read(base, uint64_t(manager)+0x120, enabled) && enabled &&
        Read(base, uint64_t(manager)+0x121, inhibited) && !inhibited &&
        Read(base, uint64_t(control)+0x1A8, eye) && Finite(eye) &&
        Read(base, uint64_t(control)+0x170, forward) && Finite(forward) &&
        std::abs(Length(forward)-1.f) < .01f;
}
struct Scratch {
    uint8_t* base; uint32_t at; std::array<uint8_t,16384> saved;
    Scratch(uint8_t* b, uint32_t sp):base(b),at(sp-16384){std::memcpy(saved.data(),base+at,saved.size());}
    ~Scratch(){std::memcpy(base+at,saved.data(),saved.size());}
};
// Native 1DF12B returns the first obstruction's actor and physical body; walls
// remain obstructions. Restore its transient hit global after this private query.
bool Ray(const X86Context& ctx, uint8_t* base, uint32_t actor, const Vec& eye,
         const Vec& end, uint32_t& hit_actor, uint32_t& body) {
    uint32_t manager = 0, world = 0, collision = 0, old_hit = 0;
    if (!Read(base,0x4ACA3C,manager) || !manager || !Read(base,uint64_t(manager)+12,world) || !world ||
        !Read(base,uint64_t(world)+0xC4,collision) || !Span(base,collision,4) ||
        !Span(base,0x49A254,8) || !Span(base,0x4ACA40,4) || !Read(base,0x4B4A24,old_hit)) return false;
    const uint32_t data=(ctx.esp-256)&~15u, stack=(ctx.esp-512)&~15u;
    std::memset(base+data,0,96);
    std::memcpy(base+data,eye.data(),12); std::memcpy(base+data+16,end.data(),12);
    std::memcpy(base+data+80,&actor,4);
    auto call=ctx; call.esp=stack;
    const uint32_t mask_args[]{0,actor}; std::memcpy(base+stack,mask_args,sizeof(mask_args));
    x86_icall(call,base,0x228EF);
    const uint32_t args[]{0,data,data+16,data+32,data+48,data+64,data+68,data+72,0,data+76,data+80,0,call.eax|2u,0,0,1};
    call=ctx;call.esp=stack;std::memcpy(base+stack,args,sizeof(args));
    x86_icall(call,base,0x1DF12B);
    Read(base,0x4B4A24,body); Read(base,data+76,hit_actor);
    std::memcpy(base+0x4B4A24,&old_hit,4);
    return (call.eax&255)==1;
}
bool Body(const uint8_t* base, const Grab& g, Vec& p, float& inverse_mass, uint32_t& method) {
    uint32_t world=0,motion=0,vt=0;
    return DarkwatchGrabbableBody(base,g.corpse,g.body) &&
        Read(base,uint64_t(g.body)+8,world) && world==g.world &&
        Read(base,uint64_t(g.body)+0x3C,motion) && motion==g.motion &&
        Read(base,motion,vt) && Read(base,uint64_t(vt)+0x60,method) && method &&
        Read(base,uint64_t(motion)+0xB0,p) && Finite(p) &&
        Read(base,uint64_t(motion)+0x2C,inverse_mass) && std::isfinite(inverse_mass) && inverse_mass>0;
}
}

void DarkwatchCorpseGrabInput(int port,input::Pad& pad,uint32_t actor,int action) {
    if(port<0||port>=4)return;
    const auto frame=input::GetMouseSnapshot();
    const bool down=action>=0&&action<16&&(action<8?(pad.buttons&(1u<<action)):pad.analog[action-8]>0);
    std::lock_guard lock(grab_mutex);auto& g=grabs[port];
    if(!actor||!pad.connected||!frame.active||!frame.published_us||g.actor!=actor||g.epoch!=frame.active_epoch){
        g={};g.actor=pad.connected?actor:0;g.epoch=frame.active_epoch;g.down=down;g.latched=down;g.sample=frame.published_us;return;
    }
    g.sample=frame.published_us;
    if(!down){g.started=0;g.latched=false;}
    else if(!g.down){g.started=frame.published_us;}
    if(down&&!g.latched&&g.started&&frame.published_us>=g.started+600000){
        g.toggle=true;g.latched=true;
    }
    g.down=down;
    // Only reserve Interact while already holding a corpse or looking at one.
    if(down&&g.latched&&(g.body||g.candidate)&&g.tick&&frame.published_us-g.tick<250000){
        if(action<8)pad.buttons&=uint16_t(~(1u<<action));else pad.analog[action-8]=0;
    }
}
void DarkwatchResetCorpseGrab(){std::lock_guard lock(grab_mutex);grabs={};}

void DarkwatchCorpseGrabTick(const X86Context& ctx,uint8_t* base) {
    if(ctx.esp<16384||!Span(base,uint64_t(ctx.esp)-16384,16384))return;
    const auto frame=input::GetMouseSnapshot();
    std::lock_guard lock(grab_mutex);
    for(auto& g:grabs){
        if(!g.actor||g.tick==frame.published_us)continue;
        Vec eye{},forward{};
        if(!frame.active||g.epoch!=frame.active_epoch||g.sample!=frame.published_us||!Pose(base,g.actor,eye,forward)){
            Drop(g);g.candidate=0;g.toggle=false;g.latched=true;continue;
        }
        const float dt=g.tick&&frame.published_us>g.tick?float(frame.published_us-g.tick)*1e-6f:0;
        g.tick=frame.published_us;
        if(dt>.25f)Drop(g);
        if(g.toggle&&g.body){Drop(g);g.toggle=false;g.candidate=0;continue;}
        if(!g.body&&!g.toggle){g.candidate=0;continue;}
        Scratch scratch(base,ctx.esp);
        if(!g.body){
            g.candidate=0;
            if(!g.toggle)continue;
            Vec end{};for(unsigned i=0;i<3;++i)end[i]=eye[i]+forward[i]*2.5f;
            uint32_t actor=0,body=0;
            const bool hit=Ray(ctx,base,g.actor,eye,end,actor,body);
            g.candidate=hit&&DarkwatchGrabbableBody(base,actor,body)?actor:0;
            if(g.toggle&&g.candidate){
                bool owned=false;for(const auto& other:grabs)if(&other!=&g&&other.corpse==actor)owned=true;
                if(!owned){g.corpse=actor;g.body=body;Read(base,uint64_t(body)+8,g.world);Read(base,uint64_t(body)+0x3C,g.motion);
                    float inverse_mass=0;uint32_t method=0;
                    if(Body(base,g,g.previous,inverse_mass,method)){
                        Vec offset{};for(unsigned i=0;i<3;++i)offset[i]=g.previous[i]-eye[i];
                        g.distance=std::clamp(Length(offset),.8f,2.5f);
                        for(unsigned i=0;i<3;++i)g.previous_target[i]=eye[i]+forward[i]*g.distance;
                    }else Drop(g);
                }
            }
            g.toggle=false;continue;
        }
        Vec p{};float inverse_mass=0;uint32_t method=0;
        if(!Body(base,g,p,inverse_mass,method)){Drop(g);continue;}
        Vec target{},error{},acceleration{},target_velocity{};
        for(unsigned i=0;i<3;++i)target[i]=eye[i]+forward[i]*g.distance;
        if(dt<=0||dt>.25f){g.previous=p;g.previous_target=target;continue;}
        for(unsigned i=0;i<3;++i)target_velocity[i]=(target[i]-g.previous_target[i])/dt;
        const float target_gain=std::min(1.f,8.f/std::max(Length(target_velocity),.001f));
        // Damp relative to the moving hand, not the ground: walking should
        // carry the grabbed body rather than continuously braking its motion.
        for(unsigned i=0;i<3;++i){error[i]=target[i]-p[i];
            acceleration[i]=120.f*error[i]+20.f*(target_velocity[i]*target_gain-(p[i]-g.previous[i])/dt);}
        g.previous_target=target;
        g.previous=p;
        if(!Finite(acceleration)||Length(error)>3.f){Drop(g);continue;}
        // Let native contacts stop the body at walls; break a stretched grab.
        const float gain=std::min(1.f,120.f/std::max(Length(acceleration),.001f));
        std::array<float,4> impulse{},point{p[0],p[1],p[2],0};
        for(unsigned i=0;i<3;++i)impulse[i]=acceleration[i]*gain*std::min(dt,.033333f)/inverse_mass;
        if(!std::all_of(impulse.begin(),impulse.end(),[](float v){return std::isfinite(v);})){Drop(g);continue;}
        const uint32_t data=(ctx.esp-256)&~15u,stack=(ctx.esp-512)&~15u;
        auto call=ctx;call.ecx=g.body;call.esp=stack;std::memset(base+stack,0,4);
        x86_icall(call,base,0x143110); // original rigid-body wake
        std::memcpy(base+data,impulse.data(),16);std::memcpy(base+data+16,point.data(),16);
        const uint32_t args[]{0,data,data+16};std::memcpy(base+stack,args,sizeof(args));
        call=ctx;call.ecx=g.motion;call.esp=stack;x86_icall(call,base,method);
    }
}
