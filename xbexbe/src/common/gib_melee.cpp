#include "ragdolls.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_001DF12B);
namespace {
bool Span(const uint8_t* base,uint64_t p,uint32_t n){
    if(!base||!p||p+n>(uint64_t(1)<<32))return false;
    for(auto page=p&~uint64_t(mem::kPage-1);page<p+n;page+=mem::kPage)
        if(!mem::IsCommitted(uint32_t(page)))return false;
    return true;
}
template<class T> bool Read(const uint8_t* base,uint64_t p,T& v){
    if(!Span(base,p,sizeof(v)))return false;std::memcpy(&v,base+p,sizeof(v));return true;
}
uint32_t BodyActor(const uint8_t* base,uint32_t body){
    // Native 6CFF3 resolves property key0. Melee passes no actor-out pointer.
    uint32_t rows=0,count=0,actor=0;
    if(!body||!Read(base,uint64_t(body)+0x30,rows)||!Read(base,uint64_t(body)+0x34,count)||
        !count||count>64||!Span(base,rows,count*8))return 0;
    bool found=false;
    for(unsigned i=0;i<count;++i){
        uint32_t key=0,value=0;
        if(!Read(base,uint64_t(rows)+i*8,key)||!Read(base,uint64_t(rows)+i*8+4,value))return 0;
        if(key==0){if(found)return 0;found=true;actor=value;}
    }
    return actor;
}
}
// 1FAC7 is the native melee obstruction ray. It plays impact effects but does
// not deliver the projectile rigid-body impulse used by bullets and explosions.
X86_FUNC(sub_001DF12B){
    const auto original=ctx;
    uint32_t caller=0;
    const bool melee=Read(base,ctx.esp,caller)&&caller==0x1FB91;
    __imp__sub_001DF12B(ctx,base);
    if(!melee||(ctx.eax&255)!=1)return;
    uint32_t actor=0,body=0,motion=0,vt=0,method=0,start=0,end=0,point=0;
    float inverse_mass=0;
    if(!Read(base,0x4B4A24,body)||!(actor=BodyActor(base,body))||!DarkwatchMeleeGibBody(base,actor,body)||
        !Read(base,uint64_t(body)+0x3C,motion)||!Read(base,motion,vt)||
        !Read(base,uint64_t(vt)+0x60,method)||!method||
        !Read(base,uint64_t(motion)+0x2C,inverse_mass)||!std::isfinite(inverse_mass)||inverse_mass<=0||
        !Read(base,uint64_t(original.esp)+4,start)||!Read(base,uint64_t(original.esp)+8,end)||
        !Read(base,uint64_t(original.esp)+12,point)||original.esp<16384||
        !Span(base,uint64_t(original.esp)-16384,16384))return;
    std::array<float,3> a{},b{},hit{};std::array<float,4> impulse{},position{};
    if(!Read(base,start,a)||!Read(base,end,b)||!Read(base,point,hit))return;
    double length=0;
    for(unsigned i=0;i<3;++i){
        if(!std::isfinite(a[i])||!std::isfinite(b[i])||!std::isfinite(hit[i]))return;
        impulse[i]=b[i]-a[i];length+=double(impulse[i])*impulse[i];position[i]=hit[i];
    }
    if(!std::isfinite(length)||length<1e-8||length>100)return;
    for(unsigned i=0;i<3;++i){impulse[i]=float(impulse[i]*(3./std::sqrt(length))/inverse_mass);if(!std::isfinite(impulse[i]))return;}
    std::array<uint8_t,16384> saved;auto* stack=base+original.esp-saved.size();
    std::memcpy(saved.data(),stack,saved.size());
    struct Restore{uint8_t* p;const decltype(saved)& s;~Restore(){std::memcpy(p,s.data(),s.size());}}restore{stack,saved};
    const uint32_t data=(original.esp-256)&~15u,sp=(original.esp-512)&~15u;
    auto call=ctx;call.esp=sp;call.ecx=body;std::memset(base+sp,0,4);
    x86_icall(call,base,0x143110);
    std::memcpy(base+data,impulse.data(),16);std::memcpy(base+data+16,position.data(),16);
    const uint32_t args[]{0,data,data+16};std::memcpy(base+sp,args,sizeof(args));
    call=ctx;call.ecx=motion;call.esp=sp;x86_icall(call,base,method);
}
