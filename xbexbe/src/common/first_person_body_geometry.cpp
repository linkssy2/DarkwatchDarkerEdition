#include "graphics_camera.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <vector>

extern "C" void __imp__sub_00262D38(X86Context&,uint8_t*);
extern "C" void __imp__sub_00131950(X86Context&,uint8_t*);
namespace {
bool Span(const uint8_t* base,uint64_t at,uint64_t size){
    if(!base || !at || !size || at+size>(uint64_t(1)<<32))return false;
    for(auto p=at&~uint64_t(mem::kPage-1);p<at+size;p+=mem::kPage)
        if(!mem::IsCommitted(uint32_t(p)))return false;
    return true;
}
template<class T> bool Read(const uint8_t* base,uint64_t at,T& value){
    if(!Span(base,at,sizeof(value)))return false;
    std::memcpy(&value,base+at,sizeof(value));return true;
}
struct BodyDraw {uint32_t skin=0;uint64_t upper=0,head=0;};
thread_local BodyDraw active;

bool Filter(uint8_t* base,const X86Context& ctx,std::vector<uint16_t>& out){
    uint32_t primitive=0,count=0,indices=0,stride=0,header=0,data=0,banked=0,palette=0;
    if(!active.skin || !Read(base,ctx.esp+4,primitive) || (primitive!=5 && primitive!=6) ||
       !Read(base,ctx.esp+8,count) || count<3 || count>65536 || (primitive==5 && count%3) ||
       !Read(base,ctx.esp+12,indices) || !Span(base,indices,count*2) ||
       !Read(base,active.skin+0x83C,banked) || banked ||
       !Read(base,active.skin+0x81C,palette) || !palette || palette>51 ||
       !Read(base,active.skin+0x828,stride) || stride<3 || stride>12 || stride%3 ||
       !Read(base,active.skin+0x824,header) || !Read(base,uint64_t(header)+4,data))return false;
    data=mem::VirtualFromPhysical(data);
    const unsigned influences=stride/3;
    std::vector<uint16_t> source(count);
    std::memcpy(source.data(),base+indices,count*2);
    const auto maximum=*std::max_element(source.begin(),source.end());
    if(!Span(base,data,(uint64_t(maximum)+1)*stride))return false;
    std::vector<int8_t> hidden(size_t(maximum)+1,-1);
    std::vector<uint8_t> head(size_t(maximum)+1,0),body(size_t(maximum)+1,0);
    for(auto vertex:source){
        if(hidden[vertex]>=0)continue;
        unsigned upper=0,total=0,head_weight=0;
        const uint64_t at=uint64_t(data)+vertex*stride;
        for(unsigned i=0;i<influences;++i){
            const unsigned weight=base[at+i];
            if(!weight)continue;
            uint16_t slot=0;uint32_t bone=0;
            if(!Read(base,at+influences+i*2,slot) || slot%3 || slot/3>=palette ||
               !Read(base,uint64_t(active.skin)+0x1C+(slot/3)*4,bone) || bone>=51)return false;
            total+=weight;
            if(active.upper&(uint64_t(1)<<bone))upper+=weight;
            if(active.head&(uint64_t(1)<<bone))head_weight+=weight;
        }
        if(total<254 || total>256)return false;
        hidden[vertex]=upper*2>=total;
        head[vertex]=head_weight!=0;body[vertex]=head_weight<total;
    }
    out.reserve(count*3);
    const unsigned step=primitive==5?3:1;
    for(unsigned i=0;i+2<count;i+=step){
        auto a=source[i],b=source[i+1],c=source[i+2];
        if(a==b || b==c || a==c || hidden[a] || hidden[b] || hidden[c])continue;
        if(primitive==6 && (i&1))std::swap(a,b);
        out.insert(out.end(),{a,b,c});
        // Collapsing the hidden head folds some neck transition faces inward.
        // Keep only this closure two-sided; ordinary body/arm faces stay unchanged.
        if((head[a]||head[b]||head[c]) && (body[a]||body[b]||body[c]))
            out.insert(out.end(),{c,b,a});
    }
    return true;
}
}

// Native 262D38 follows palette production and encloses only this atomic's
// material draws. Never carry a last-seen skin into another actor or viewport.
extern "C" void sub_00262D38(X86Context& ctx,uint8_t* base){
    const auto saved=active;active={};
    uint32_t atomic=0,offset=0,hierarchy=0;
    if(base==kernel::g_base && Read(base,ctx.esp+4,atomic) && atomic &&
       Read(base,0x4BA834,offset) && offset && offset<0x1000 &&
       Read(base,uint64_t(atomic)+offset,hierarchy) && hierarchy &&
       hierarchy==DarkwatchFirstPersonBodyHierarchy(base))
    {
        DarkwatchFirstPersonFrame frame{};
        if(DarkwatchFirstPersonBodyFrame(base,hierarchy,frame))
            active={ctx.ebx,DarkwatchFirstPersonHiddenBones(base),frame.head};
    }
    struct Restore {BodyDraw value;~Restore(){active=value;}} restore{saved};
    __imp__sub_00262D38(ctx,base);
}

extern "C" void sub_00131950(X86Context& ctx,uint8_t* base){
    std::vector<uint16_t> indices;
    if(base!=kernel::g_base || !active.upper || !Filter(base,ctx,indices)){
        __imp__sub_00131950(ctx,base);return;
    }
    if(indices.empty()){ctx.eax=0;ctx.esp+=4;return;}
    const uint32_t bytes=uint32_t(indices.size()*2),buffer=mem::AllocSystem(bytes);
    if(!buffer){__imp__sub_00131950(ctx,base);return;}
    struct Free {uint32_t at;~Free(){mem::FreeSystem(at);}} free{buffer};
    if(!Span(base,buffer,bytes)){__imp__sub_00131950(ctx,base);return;}
    std::memcpy(base+buffer,indices.data(),bytes);
    const uint32_t args=ctx.esp+4;
    std::array<uint32_t,3> saved{};
    std::memcpy(saved.data(),base+args,sizeof(saved));
    struct RestoreArgs {uint8_t* at;std::array<uint32_t,3> values;
        ~RestoreArgs(){std::memcpy(at,values.data(),sizeof(values));}} restore{base+args,saved};
    const uint32_t replacement[]{5,uint32_t(indices.size()),buffer};
    std::memcpy(base+args,replacement,sizeof(replacement));
    // Draw snapshots the index bytes before returning; shared mesh data stays intact.
    __imp__sub_00131950(ctx,base);
}
