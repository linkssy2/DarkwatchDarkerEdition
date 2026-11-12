#include "character_runtime.h"
#include "cpu/x86_ops.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <cmath>
#include <cstring>
#include <array>

X86_EXTERN_FUNC(__imp__sub_00287EB0);
X86_EXTERN_FUNC(__imp__sub_0026EF30);
X86_EXTERN_FUNC(__imp__sub_00288610);
X86_EXTERN_FUNC(__imp__sub_002882D0);
X86_EXTERN_FUNC(__imp__sub_00287FD0);
X86_EXTERN_FUNC(__imp__sub_00281310);
X86_EXTERN_FUNC(__imp__sub_00281410);
X86_EXTERN_FUNC(__imp__sub_00281640);
X86_EXTERN_FUNC(__imp__sub_00282130);
X86_EXTERN_FUNC(__imp__sub_002824C0);
X86_EXTERN_FUNC(__imp__sub_002819E0);
X86_EXTERN_FUNC(__imp__sub_0028C920);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t bytes) {
    if (!base || !at || !bytes || at+bytes > (uint64_t(1)<<32)) return false;
    for (auto p=at&~(uint64_t(mem::kPage)-1); p<at+bytes; p+=mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base+at, sizeof(value)); return true;
}
bool PrivateName(const uint8_t* base, uint32_t actor) {
    uint32_t name=0;
    if (!Read(base, uint64_t(actor)+0x50, name)) return false;
    for (const auto* wanted : {"DarkerPrivateRedeemerDroppedClip", "DarkerPrivateDualPistolDroppedClip",
                              "DarkerPrivateCrossbowDroppedClip", "DarkerPrivateSniperDroppedCylinder",
                              "DarkerPrivateRocketDroppedClip"}) {
        const auto size=std::strlen(wanted)+1;
        if (Span(base, uint64_t(name)+2, size) && !std::memcmp(base+uint64_t(name)+2, wanted, size)) return true;
    }
    return false;
}
bool PrivateBody(const uint8_t* base, uint32_t cdBody) {
    // Native hkCdBody is embedded at rigidBody+0xC. Only root rigid bodies;
    // property 0 is the actor, verified back through its HavokMotion component.
    if (cdBody<0xC) return false;
    const uint32_t body=cdBody-0xC;
    uint32_t type=0,parent=0,shape=0,properties=0,count=0,actor=0;
    float radius=0;
    if (!Read(base,body,type) || type!=0x4328EC || !Read(base,uint64_t(cdBody)+0xC,parent) || parent ||
        !Read(base,cdBody,shape) || !Read(base,shape,type) || type!=0x432280 ||
        !Read(base,uint64_t(shape)+0xC,radius) || !std::isfinite(radius) || std::abs(radius-.001f)>.000001f ||
        !Read(base,uint64_t(body)+0x30,properties) || !Read(base,uint64_t(body)+0x34,count) ||
        !count || count>64 || !Span(base,properties,count*8)) return false;
    for (unsigned i=0; i<count; ++i) {
        uint32_t key=0,value=0;
        if (!Read(base,uint64_t(properties)+i*8,key) || !Read(base,uint64_t(properties)+i*8+4,value)) return false;
        if (!key) { if (actor) return false; actor=value; }
    }
    uint16_t components=0; uint32_t rows=0;
    if (!actor || !PrivateName(base,actor) || !Read(base,uint64_t(actor)+0x60,components) || components!=2 ||
        !Read(base,uint64_t(actor)+0x64,rows) || !Span(base,rows,16)) return false;
    unsigned motions=0,renders=0;
    for (unsigned i=0;i<2;++i) {
        uint32_t component=0,owner=0,actual=0;
        if (!Read(base,uint64_t(rows)+i*8+4,component) || !Read(base,component,type) ||
            !Read(base,uint64_t(component)+0xC,owner) || owner!=actor) return false;
        if (type==0x41D648) {
            if (++motions!=1 || !Read(base,uint64_t(component)+0x9C,actual) || actual!=body) return false;
        } else if (type==0x41E3E0) ++renders;
        else return false;
    }
    return motions==1 && renders==1;
}
uint32_t TerrainMesh(const uint8_t* base, uint32_t cdBody) {
    uint32_t shape=0,type=0,mesh=0;
    float radius=0;
    if (!Read(base,cdBody,shape) || !Read(base,shape,type) || type!=0x44A470 ||
        !Read(base,uint64_t(shape)+0xC,mesh) || !Read(base,mesh,type) || type!=0x43908C ||
        !Read(base,uint64_t(mesh)+0x20,radius) || !std::isfinite(radius) || std::abs(radius-.05f)>.000001f) return 0;
    return mesh;
}
thread_local uint32_t contactMesh=0;
struct PairScope {
    uint32_t saved=contactMesh;
    explicit PairScope(uint32_t mesh) { contactMesh=mesh; }
    ~PairScope() { contactMesh=saved; }
};
using Native = void(*)(X86Context&,uint8_t*);
void MeshPair(X86Context& ctx, uint8_t* base, Native original) {
    uint32_t a=0,b=0,mesh=0;
    if (base==kernel::g_base && DarkwatchPrivateClipFixtureReady() &&
        Read(base,uint64_t(ctx.esp)+4,a) && Read(base,uint64_t(ctx.esp)+8,b) && PrivateBody(base,a))
        mesh=TerrainMesh(base,b);
    const PairScope scope(mesh);
    original(ctx,base);
}
bool FixedBox(const uint8_t* base,uint32_t cdBody,uint32_t& shape) {
    uint32_t type=0,root=cdBody,parent=0,motion=0;
    float radius=0;
    if (!Read(base,cdBody,shape) || !Read(base,shape,type) || type!=0x432280 ||
        !Read(base,uint64_t(shape)+0xC,radius) || radius!=.05f) return false;
    // Transform agents pass a stack child CD-body. Resolve its original owner;
    // only fixed/keyframed props qualify, never dynamic boxes or characters.
    for (unsigned i=0;i<4;++i) {
        if (!Read(base,uint64_t(root)+0xC,parent)) return false;
        if (!parent) break;
        root=parent;
        if (i==3) return false;
    }
    return root>=0xC && Read(base,root-0xC,type) && type==0x4328EC &&
        Read(base,uint64_t(root)+0x30,motion) && Read(base,motion,type) &&
        (type==0x433AC0 || type==0x433B68);
}
void BoxPair(X86Context& ctx,uint8_t* base,Native original,unsigned argumentBytes) {
    uint32_t a=0,b=0,shape=0;
    unsigned adjusted=0;
    if (base==kernel::g_base && DarkwatchPrivateClipFixtureReady() &&
        Read(base,uint64_t(ctx.esp)+4,a) && Read(base,uint64_t(ctx.esp)+8,b)) {
        if (PrivateBody(base,a) && FixedBox(base,b,shape)) adjusted=8;
        else if (PrivateBody(base,b) && FixedBox(base,a,shape)) adjusted=4;
    }
    if (!adjusted || ctx.esp<0x10000 || !Span(base,uint64_t(ctx.esp)-0x10000,0x10020) ||
        !Span(base,shape,0x20)) { original(ctx,base); return; }
    // Give the original agent an equivalent temporary CD-body/box. Shared
    // shapes stay untouched, including across nested calls or physics threads.
    const auto old=uint32_t(ctx.esp),at=(old-0x200)&~15u;
    const auto body=at+0x80,box=at+0xA0;
    std::array<uint8_t,0xC0> saved{};
    std::memcpy(saved.data(),base+at,saved.size());
    std::memcpy(base+at,base+old,argumentBytes+4);
    const uint32_t source=adjusted==8?b:a;
    std::memcpy(base+body,base+source,16);
    std::memcpy(base+box,base+shape,32);
    std::memcpy(base+body,&box,4);
    std::memcpy(base+body+12,&source,4);
    constexpr float radius=.001f;
    std::memcpy(base+box+12,&radius,4);
    std::memcpy(base+at+adjusted,&body,4);
    ctx.esp=at;
    try { original(ctx,base); }
    catch (...) { std::memcpy(base+at,saved.data(),saved.size()); ctx.esp=old; throw; }
    ctx.esp=old+(uint32_t(ctx.esp)-at);
    std::memcpy(base+at,saved.data(),saved.size());
}
}

bool DarkwatchPrivateClipBody(const uint8_t* base,uint32_t body) {
    return base==kernel::g_base && DarkwatchPrivateClipFixtureReady() && body<=UINT32_MAX-12 && PrivateBody(base,body+12);
}

// All four MOPP query paths can create/reuse child agents. They must agree about
// the pair's radius before the processCollision callback sees the cached agent.
X86_FUNC(sub_00287EB0) { MeshPair(ctx,base,__imp__sub_00287EB0); }
X86_FUNC(sub_00288610) { MeshPair(ctx,base,__imp__sub_00288610); }
X86_FUNC(sub_002882D0) { MeshPair(ctx,base,__imp__sub_002882D0); }
X86_FUNC(sub_00287FD0) { MeshPair(ctx,base,__imp__sub_00287FD0); }
X86_FUNC(sub_00281310) { BoxPair(ctx,base,__imp__sub_00281310,16); }
X86_FUNC(sub_00281410) { BoxPair(ctx,base,__imp__sub_00281410,16); }
X86_FUNC(sub_00281640) { BoxPair(ctx,base,__imp__sub_00281640,16); }
X86_FUNC(sub_00282130) { BoxPair(ctx,base,__imp__sub_00282130,16); }
X86_FUNC(sub_002824C0) { BoxPair(ctx,base,__imp__sub_002824C0,16); }
X86_FUNC(sub_002819E0) { BoxPair(ctx,base,__imp__sub_002819E0,16); }
X86_FUNC(sub_0028C920) { BoxPair(ctx,base,__imp__sub_0028C920,20); }

X86_FUNC(sub_0026EF30) {
    uint32_t output=0;
    const bool candidate=contactMesh && ctx.ecx==contactMesh && base==kernel::g_base &&
        Read(base,uint64_t(ctx.esp)+8,output);
    __imp__sub_0026EF30(ctx,base);
    uint32_t type=0;float radius=0;
    if (candidate && output && ctx.eax==output && Read(base,output,type) && type==0x44A098 &&
        Read(base,uint64_t(output)+0xC,radius) && std::isfinite(radius) && std::abs(radius-.05f)<.000001f) {
        // Original terrain has a 5 cm convex shell: too large for these small
        // clips. Adjust only this temporary contact triangle, never its shared
        // mesh, world tolerance, render transform or other bodies' contacts.
        constexpr float clipTerrainRadius=.001f;
        std::memcpy(base+uint64_t(output)+0xC,&clipTerrainRadius,sizeof(clipTerrainRadius));
    }
}
