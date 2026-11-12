#include "ejected_clips.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <cmath>
#include <cstring>
#include <cstdio>
bool DarkwatchPrivateClipBody(const uint8_t*,uint32_t);

namespace darkwatch::clips {
namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base + at, sizeof(value)); return true;
}
bool Name(const uint8_t* base, uint64_t at, const char* name) {
    uint32_t p = 0;
    const auto bytes = std::strlen(name) + 1;
    return Read(base, at, p) && p && Span(base, uint64_t(p)+2, bytes) &&
        !std::memcmp(base + uint64_t(p)+2, name, bytes);
}
uint32_t Motion(const uint8_t* base, uint32_t actor) {
    uint16_t count = 0; uint32_t list = 0, motion = 0, render = 0;
    if (!Read(base, uint64_t(actor)+0x60, count) || count != 2 ||
        !Read(base, uint64_t(actor)+0x64, list) || !Span(base, list, count*8)) return 0;
    for (unsigned i=0; i<count; ++i) {
        uint32_t component=0, type=0, owner=0;
        if (!Read(base, uint64_t(list)+i*8+4, component) || !Read(base, component, type) ||
            !Read(base, uint64_t(component)+0xC, owner) || owner != actor) return 0;
        if (type == 0x41D648 && !motion) motion = component;
        else if (type == 0x41E3E0 && !render) render = component;
        else return 0;
    }
    return render ? motion : 0;
}
struct Scratch {
    X86Context call; uint8_t* base; uint32_t at; std::array<uint8_t,0x200> saved;
    Scratch(const X86Context& ctx, uint8_t* b) : call(ctx), base(b), at((ctx.esp-0x300)&~15u) {
        std::memcpy(saved.data(), base+at, saved.size());
        std::memset(base+at, 0, saved.size()); call.esp=at-0x20;
    }
    ~Scratch() { std::memcpy(base+at, saved.data(), saved.size()); }
    uint32_t Invoke(uint32_t fn, uint32_t object, std::initializer_list<uint32_t> args={}) {
        call.ecx=object; return kernel::CallGuest(call, fn, args);
    }
};
}

uint32_t CreateNativeProp(const X86Context& ctx, uint8_t* base, uint32_t owner,
                          Kind kind, const Matrix& placement) {
    const char* name = nullptr;
    switch(kind) {
        case Kind::Redeemer: name="DarkerPrivateRedeemerDroppedClip"; break;
        case Kind::DualPistol: name="DarkerPrivateDualPistolDroppedClip"; break;
        case Kind::Crossbow: name="DarkerPrivateCrossbowDroppedClip"; break;
        case Kind::Sniper: name="DarkerPrivateSniperDroppedCylinder"; break;
        case Kind::Rocket: name="DarkerPrivateRocketDroppedClip"; break;
        default: return 0;
    }
    uint32_t zone=0, world=0;
    if (base!=kernel::g_base || ctx.esp<0x10000 ||
        !Span(base, uint64_t(ctx.esp)-0x10000, 0x10010) ||
        !Read(base, uint64_t(owner)+0x68, zone) || !zone ||
        !Read(base, uint64_t(owner)+0x6C, world) || !world) return 0;
    for (unsigned r=0; r<4; ++r) for (unsigned a=0; a<3; ++a)
        if (!std::isfinite(placement[r*4+a]) || std::abs(placement[r*4+a])>1000000.f) return 0;
    Scratch s(ctx,base);
    std::memcpy(base+s.at+0x20, name, std::strlen(name)+1);
    s.Invoke(0x138FA, s.at, {s.at+0x20});
    const auto prop=s.Invoke(0x2168A4, 0, {s.at,zone,world,1,1,s.at+4,1});
    s.Invoke(0x11C1A, s.at); s.Invoke(0x11C1A, s.at+4);
    if (!prop) return 0;
    const auto component=Motion(base,prop);
    uint32_t body=0, actual_zone=0, actual_world=0;
    if (!component || !Name(base,uint64_t(prop)+0x50,name) ||
        !Read(base,uint64_t(prop)+0x68,actual_zone) || actual_zone!=zone ||
        !Read(base,uint64_t(prop)+0x6C,actual_world) || actual_world!=world ||
        !Read(base,uint64_t(component)+0x9C,body) || !Span(base,body,0x60)) {
        s.Invoke(0x215932,s.Invoke(0x12731,0),{prop}); return 0;
    }
    std::memcpy(base+s.at+0x100,placement.data(),sizeof(placement));
    s.Invoke(0x216244,prop,{s.at+0x100});
    s.Invoke(0x71CB4,component);
    return prop;
}

void KickNativeProp(const X86Context& ctx,uint8_t* base,uint32_t body,
                    const FootBox& foot,Vec previous,float dt) {
    uint32_t motion=0,type=0,shape=0,world=0;
    Matrix matrix{};Vec half{},linear{},angular{},center{};float inverseMass=0;
    if (!DarkwatchPrivateClipBody(base,body) || !(dt>0 && dt<=.1f) || ctx.esp<0x10000 ||
        !Span(base,uint64_t(ctx.esp)-0x10000,0x10010) ||
        !Read(base,uint64_t(body)+8,world) || !world ||
        !Read(base,uint64_t(body)+0x3C,motion) || !Read(base,motion,type) || type!=0x433C68 ||
        !Read(base,uint64_t(body)+0xC,shape) || !Read(base,uint64_t(shape)+0x10,half) ||
        !Read(base,uint64_t(motion)+0x80,matrix) || !Read(base,uint64_t(motion)+0x70,center) ||
        !Read(base,uint64_t(motion)+0x40,linear) || !Read(base,uint64_t(motion)+0x50,angular) ||
        !Read(base,uint64_t(motion)+0x2C,inverseMass) || !std::isfinite(inverseMass) || inverseMass<=0) return;
    FootBox box{ {matrix[12],matrix[13],matrix[14]}, {{{matrix[0],matrix[1],matrix[2]},
        {matrix[4],matrix[5],matrix[6]},{matrix[8],matrix[9],matrix[10]}}},half};
    for (unsigned i=0;i<3;++i) {
        if (!std::isfinite(half[i]) || half[i]<=0 || half[i]>.5f ||
            !std::isfinite(center[i]) || !std::isfinite(linear[i]) || !std::isfinite(angular[i]) ||
            !std::isfinite(box.center[i]) || std::abs(Dot(box.axes[i],box.axes[i])-1)>.01f) return;
        box.half[i]+=.001f;
    }
    // Clip-relative sweep includes translation during the preceding game step.
    Vec prior=Add(previous,Scale(linear,dt)),normal{};float time=0;
    if (!SweepFoot(foot,prior,box,time,normal)) return;
    Vec velocity=Scale(Sub(foot.center,previous),1/dt);
    if (!std::isfinite(Dot(velocity,velocity)) || Dot(velocity,velocity)>400) return;
    // A sole strike against a floor-resting prop slides it along the foot's travel.
    if (std::abs(normal[1])>.70710678f) {
        normal={velocity[0]-linear[0],0,velocity[2]-linear[2]};
        const float length=std::sqrt(Dot(normal,normal));if(length<.05f)return;
        normal=Scale(normal,1/length);
    }
    const Vec contact=Closest(box,Add(prior,Scale(Sub(foot.center,prior),time)));
    Scratch s(ctx,base);
    s.Invoke(0x152650,motion,{s.at+0x100});
    Matrix inertia{};if(!Read(base,s.at+0x100,inertia))return;
    std::array<Vec,3> inverseInertia{{{inertia[0],inertia[1],inertia[2]},
        {inertia[4],inertia[5],inertia[6]},{inertia[8],inertia[9],inertia[10]}}};
    Vec impulse=FootImpulse(velocity,linear,angular,Sub(contact,center),normal,inverseMass,inverseInertia);
    const float magnitude=Dot(impulse,impulse);
    if (!(magnitude>1e-12f) || !std::isfinite(magnitude)) return;
    std::memcpy(base+s.at,impulse.data(),12);std::memcpy(base+s.at+16,contact.data(),12);
    s.Invoke(0x143110,body);
    s.Invoke(0x152940,motion,{s.at,s.at+16});
#ifndef XBE_RELEASE
    static unsigned witnesses=0;
    if(witnesses++<32)std::fprintf(stderr,"[clip-foot] body=%08X dt=%.6f foot=(%.4f,%.4f,%.4f) impulse=(%.4f,%.4f,%.4f)\n",
        body,dt,foot.center[0],foot.center[1],foot.center[2],impulse[0],impulse[1],impulse[2]);
#endif
}
}
