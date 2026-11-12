#include "ejected_clips.h"
#include "character_runtime.h"
#include "cpu/x86_ops.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>
#include <cstdio>

X86_EXTERN_FUNC(__imp__sub_000AA19F);
X86_EXTERN_FUNC(__imp__sub_00215D9F);
X86_EXTERN_FUNC(__imp__sub_00260D40);
bool DarkwatchPrivateClipBody(const uint8_t*,uint32_t);

namespace {
using darkwatch::clips::Kind;
using darkwatch::clips::Matrix;
struct Release {
    const char* name; Kind kind; uint32_t item, bones, bone;
    float outbound, incoming, duration; Matrix local;
};
// The original rigid-island transform at the first outgoing key. The replacement
// uses the same source bone later; never suppress that incoming portion.
constexpr Release releases[]{
    {"Revolver",Kind::Redeemer,0x418390,5,2,.1415929347f,.2654867172f,1.8833333254f,
        {-.016635877f,.033006981f,-.999316660f,0,-.081231168f,.996106527f,.034253228f,0,
          .996556443f,.081745492f,-.013889910f,0,.202031020f,.003667140f,-.005918377f,0}},
    {"DoublePistol",Kind::DualPistol,0x417E90,5,2,.1641791016f,.4328358173f,2.2333333492f,
        {0,0,-1,0,.043234688f,.999064944f,0,0,.999064944f,-.043234688f,0,0,
          .222785824f,.026920721f,-.0000000044f,0}},
    // Authored body handoff: discard, then retrieve the replacement. The source
    // weapon clip stays intact; its translation matches body_reload_parts.inc.
    {"Crossbow",Kind::Crossbow,0x418390,8,1,.4f,.525f,3.3333332539f,
        {.627190684f,.776780706f,.056952441f,0,.301063973f,-.309224890f,.902075635f,0,
         .718326061f,-.548627106f,-.427803656f,0,.537050945f,-.252443253f,-.071772186f,0}},
    {"SniperRifle",Kind::Sniper,0x418390,4,2,.1872146130f,.39f,3.6500000954f,
        {.989144692f,-.146944813f,0,0,.146944813f,.989144692f,0,0,0,0,1,0,
         .119752408f,.078961531f,.000556035f,0}},
    {"RocketLauncher",Kind::Rocket,0x418390,5,2,.0808823556f,.2205882370f,4.5333333015f,
        {-.002158359f,.000006912f,-.999997671f,0,.046383145f,.998923718f,-.000093207f,0,
         .998921391f,-.046383238f,-.002156357f,0,.085567072f,.275803378f,.047330631f,0}}
};
bool Span(const uint8_t* base,uint64_t at,uint64_t bytes) {
    if (!base || !at || !bytes || at+bytes>(uint64_t(1)<<32)) return false;
    for (auto p=at&~(uint64_t(mem::kPage)-1);p<at+bytes;p+=mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base,uint64_t at,T& value) {
    if (!Span(base,at,sizeof(value))) return false;
    std::memcpy(&value,base+at,sizeof(value)); return true;
}
bool Name(const uint8_t* base,uint64_t at,const char* text) {
    uint32_t p=0; const auto bytes=std::strlen(text)+1;
    return Read(base,at,p) && p && Span(base,uint64_t(p)+2,bytes) &&
        !std::memcmp(base+uint64_t(p)+2,text,bytes);
}
uint32_t Component(const uint8_t* base,uint32_t actor,uint32_t wanted) {
    uint16_t count=0;uint32_t list=0,result=0;
    if (!actor || !Read(base,uint64_t(actor)+0x60,count) || !count || count>128 ||
        !Read(base,uint64_t(actor)+0x64,list) || !Span(base,list,count*8)) return 0;
    for (unsigned i=0;i<count;++i) {
        uint32_t c=0,type=0,owner=0;
        if (!Read(base,uint64_t(list)+i*8+4,c) || !Read(base,c,type)) return 0;
        if (type!=wanted) continue;
        if (result || !Read(base,uint64_t(c)+0xC,owner) || owner!=actor) return 0;
        result=c;
    }
    return result;
}
bool Players(const uint8_t* base,std::array<uint32_t,2>& out) {
    uint32_t game=0,players=0,rows=0,seen=0;uint16_t count=0;
    if (!Read(base,0x4AC9A0,game) || !game || !Read(base,uint64_t(game)+0x44,players) ||
        !players || players>2 || !Read(base,uint64_t(game)+0x50,count) || count<players || count>64 ||
        !Read(base,uint64_t(game)+0x54,rows) || !Span(base,rows,count*0x130)) return false;
    out={};
    for (unsigned i=0;i<count;++i) {
        const uint64_t row=uint64_t(rows)+i*0x130;uint32_t ordinal=0,actor=0;uint8_t local=0;
        if (!Read(base,row+0x10C,ordinal)) return false;
        if (ordinal>=players) continue;
        if ((seen&(1u<<ordinal)) || !Read(base,row+0x118,actor) || !actor ||
            !Read(base,row+0x128,local) || local!=1) return false;
        seen|=1u<<ordinal;out[ordinal]=actor;
    }
    return seen==(1u<<players)-1;
}
using darkwatch::clips::FootBox;
using darkwatch::clips::Vec;
struct Feet {uint32_t actor=0,pose=0,world=0,zone=0;float dt=0;bool valid=false;std::array<FootBox,2> boxes{};};
std::array<Feet,2> feet;
bool FootPose(const uint8_t* base,uint32_t actor,Feet& out) {
    uint32_t flags=0,hierarchy=0,bones=0,matrices=0;
    // These bounds are measured from this model's actual weighted foot vertices.
    if (!(Name(base,uint64_t(actor)+0x50,"CassidySpectralSolo") ||
          Name(base,uint64_t(actor)+0x50,"CassidySpectralPlayerTwo")) ||
        !Read(base,uint64_t(actor)+0x90,flags) || (flags&2) || !Component(base,actor,0x4227A4) ||
        !Component(base,actor,0x41F878)) return false;
    const auto animation=Component(base,actor,0x41D258);
    if (!animation || !Read(base,uint64_t(animation)+0x34,out.pose) || !out.pose ||
        !Read(base,uint64_t(out.pose)+0x10,hierarchy) || !Read(base,uint64_t(hierarchy)+4,bones) || bones!=51 ||
        !Read(base,uint64_t(hierarchy)+8,matrices) || !Span(base,matrices,bones*64) ||
        !Read(base,uint64_t(actor)+0x68,out.zone) || !out.zone ||
        !Read(base,uint64_t(actor)+0x6C,out.world) || !out.world) return false;
    constexpr Vec centers[]{{.087656712f,-.071008179f,-.007934446f},{.087708508f,-.071022289f,.008423716f}};
    for(unsigned foot=0;foot<2;++foot) {
        Matrix m{};if(!Read(base,uint64_t(matrices)+(foot?6:3)*64,m))return false;
        auto& b=out.boxes[foot];b.center={m[12],m[13],m[14]};
        b.half={.100306f,.134860f,.054279f};
        for(unsigned axis=0;axis<3;++axis) {
            b.axes[axis]={m[axis*4],m[axis*4+1],m[axis*4+2]};
            if(!std::isfinite(darkwatch::clips::Dot(b.axes[axis],b.axes[axis])) ||
               std::abs(darkwatch::clips::Dot(b.axes[axis],b.axes[axis])-1)>.01f)return false;
            b.center=darkwatch::clips::Add(b.center,darkwatch::clips::Scale(b.axes[axis],centers[foot][axis]));
        }
        for(auto x:b.center)if(!std::isfinite(x)||std::abs(x)>1000000)return false;
    }
    out.actor=actor;out.valid=true;return true;
}
void KickFeet(const X86Context& ctx,uint8_t* base,const std::array<uint32_t,2>& players) {
    for(unsigned p=0;p<2;++p) {
        auto previous=feet[p];feet[p]={};
        if(!FootPose(base,players[p],feet[p]))continue;
        const auto& current=feet[p];const float dt=previous.dt;
        if(!previous.valid || previous.actor!=current.actor || previous.pose!=current.pose ||
           previous.world!=current.world || previous.zone!=current.zone || !(dt>0 && dt<=.1f))continue;
        uint32_t manager=0,groups=0;uint16_t count=0;
        if(!Read(base,0x4AC118,manager)||!Read(base,manager,count)||!count||count>256||
           !Read(base,uint64_t(manager)+4,groups)||!Span(base,groups,count*4))continue;
        unsigned total=0;
        for(unsigned g=0;g<count;++g) {
            uint32_t group=0,rows=0;uint16_t n=0;
            if(!Read(base,uint64_t(groups)+g*4,group)||!Read(base,uint64_t(group)+0x20,n)||
               (total+=n)>8192 || !Read(base,uint64_t(group)+0x24,rows)|| (n&&!Span(base,rows,n*4)))break;
            for(unsigned i=0;i<n;++i) {
                uint32_t actor=0,world=0,zone=0,body=0;
                if(!Read(base,uint64_t(rows)+i*4,actor)||!actor||
                   !Read(base,uint64_t(actor)+0x6C,world)||world!=current.world||
                   !Read(base,uint64_t(actor)+0x68,zone)||zone!=current.zone)continue;
                const auto motion=Component(base,actor,0x41D648);
                if(!motion||!Read(base,uint64_t(motion)+0x9C,body)||!DarkwatchPrivateClipBody(base,body))continue;
                for(unsigned f=0;f<2;++f) {
                    const auto displacement=darkwatch::clips::Sub(current.boxes[f].center,previous.boxes[f].center);
                    if(darkwatch::clips::Dot(displacement,displacement)>.25f)continue; // Teleport, never a kick.
                    darkwatch::clips::KickNativeProp(ctx,base,body,current.boxes[f],previous.boxes[f].center,dt);
                }
            }
        }
    }
}
struct Held { uint32_t owner=0,weapon=0,item=0;const Release* release=nullptr; };
bool Owned(const uint8_t* base,uint32_t actor,unsigned hand,Held& out) {
    uint32_t flags=0;
    if (hand>1 || !Read(base,uint64_t(actor)+0x90,flags) || (flags&2) ||
        !Component(base,actor,0x4227A4)) return false;
    const auto inventory=Component(base,actor,0x41F29C);
    uint32_t mode=0,slots=0,categories=0,index=0,slot=0,type=0,owner=0,weapon=0,parent=0;
    uint16_t count=0,ncategory=0;
    if (!inventory || !Read(base,uint64_t(inventory)+0x64,mode) || mode ||
        !Read(base,uint64_t(inventory)+0x88,count) || !count || count>64 ||
        !Read(base,uint64_t(inventory)+0x8C,slots) || !Span(base,slots,count*4) ||
        !Read(base,uint64_t(inventory)+0x78,ncategory) || !ncategory || ncategory>4 ||
        !Read(base,uint64_t(inventory)+0x7C,categories) || !Read(base,categories,index) || index>=count ||
        !Read(base,uint64_t(slots)+index*4,slot) || !Read(base,slot,type) || type!=0x41F570 ||
        !Name(base,uint64_t(slot)+4,"loc_RightHand") || !Read(base,uint64_t(slot)+8,owner) || owner!=inventory ||
        !Read(base,uint64_t(slot)+0xC,weapon) || !weapon || !Read(base,uint64_t(slot)+0x1C,parent) || parent!=actor) return false;
    const Release* release=nullptr;
    for (const auto& candidate:releases) if (Name(base,uint64_t(weapon)+0x50,candidate.name)) release=&candidate;
    if (!release) return false;
    uint32_t item=Component(base,weapon,release->item),item_owner=0;
    if (!item || !Read(base,uint64_t(item)+0x58,item_owner) || item_owner!=actor ||
        !Name(base,uint64_t(item)+0x24,release->name)) return false;
    if (release->kind==Kind::DualPistol) {
        uint8_t master=0;
        if (!Read(base,uint64_t(item)+0x330,master) || master!=1) return false;
        if (hand) {
            uint32_t child=0,child_item=0;uint8_t child_flag=1;
            if (!Read(base,uint64_t(item)+0x338,child) || !child ||
                !Read(base,uint64_t(item)+0x348,child_item) || child_item!=Component(base,child,release->item) ||
                !Name(base,uint64_t(child)+0x50,release->name) ||
                !Read(base,uint64_t(child_item)+0x58,item_owner) || item_owner!=actor ||
                !Read(base,uint64_t(child_item)+0x330,child_flag) || child_flag) return false;
            unsigned matches=0;
            for (unsigned i=0;i<count;++i) {
                uint32_t left=0,attached=0;
                if (!Read(base,uint64_t(slots)+i*4,left)) return false;
                if (!Name(base,uint64_t(left)+4,"loc_LeftHandDualWield")) continue;
                if (++matches!=1 || !Read(base,left,type) || type!=0x41F570 ||
                    !Read(base,uint64_t(left)+8,owner) || owner!=inventory ||
                    !Read(base,uint64_t(left)+0xC,attached) || attached!=child ||
                    !Read(base,uint64_t(left)+0x1C,parent) || parent!=actor) return false;
            }
            if (matches!=1) return false;
            weapon=child;item=child_item;
        }
    } else if (hand) return false;
    out={actor,weapon,item,release};return true;
}
struct Reload { uint32_t controller=0,hierarchy=0,clock=0,resource=0;float phase=0; };
bool Clock(const uint8_t* base,const Held& held,Reload& result) {
    const auto animation=Component(base,held.weapon,0x41D258);
    uint32_t pose=0,controller=0,owner=0,controller_pose=0,mode=0,slots=0,groups=0,hierarchy=0,bones=0;
    uint16_t count=0;
    constexpr unsigned limits[]{4,14,24};
    if (!animation || !Read(base,uint64_t(animation)+0x34,pose) || !pose ||
        !Read(base,uint64_t(pose)+0x10,hierarchy) || !Read(base,uint64_t(hierarchy)+4,bones) || bones!=held.release->bones ||
        !Read(base,uint64_t(animation)+0x60,controller) || !controller ||
        !Read(base,uint64_t(controller)+0x88,owner) || owner!=held.weapon ||
        !Read(base,uint64_t(controller)+0x58,controller_pose) || controller_pose!=pose ||
        !Read(base,uint64_t(controller)+0xE4,owner) || owner!=controller ||
        !Read(base,uint64_t(controller)+0x160,mode) || mode>=3 ||
        !Read(base,uint64_t(controller)+0xE0,slots) || !Span(base,slots,limits[mode]*0x3C) ||
        !Read(base,uint64_t(controller)+0x28,count) || !count || count>8 ||
        !Read(base,uint64_t(controller)+0x2C,groups) || !Span(base,groups,count*0x3C)) return false;
    float best=0;
    for (unsigned g=0;g<count;++g) {
        const uint64_t group=uint64_t(groups)+g*0x3C;uint32_t resource=0,rows=0;uint16_t n=0;
        if (!Read(base,group+0xC,owner) || owner!=controller || !Read(base,group+0x14,resource) || !resource ||
            !Read(base,resource,n) || !n || n>128 || !Read(base,uint64_t(resource)+4,rows) || !Span(base,rows,n*0x8C)) return false;
        for (unsigned r=0;r<n;++r) {
            const uint64_t row=uint64_t(rows)+r*0x8C;uint32_t key=0;
            if (!Name(base,row+0x70,"RELOAD") || !Read(base,row+0x6C,key) || !key) continue;
            for (unsigned s=0;s<limits[mode];++s) {
                const uint64_t slot=uint64_t(slots)+s*0x3C;
                uint32_t active=0,clock=0,clip_resource=0,clip=0;float weight=0,phase=0,duration=0;
                if (!Read(base,slot+0x10,active) || active!=key || !Read(base,slot,weight) ||
                    !std::isfinite(weight) || weight<=best || weight>1.001f ||
                    !Read(base,slot+0x20,clock) || !clock || !Read(base,clock,phase) ||
                    !std::isfinite(phase) || phase<0 || phase>1.001f ||
                    !Read(base,uint64_t(clock)+0x1C,clip_resource) || !clip_resource ||
                    !Read(base,uint64_t(clip_resource)+0x10,clip) || !clip ||
                    !Read(base,uint64_t(clip)+4,duration) || !std::isfinite(duration) ||
                    std::abs(duration-held.release->duration)>.001f) continue;
                best=weight;result={controller,hierarchy,clock,clip_resource,phase};
            }
        }
    }
    return best>0;
}
struct State {
    Held held{};Reload reload{};Matrix placement{};
    uint32_t zone=0,world=0;bool attempted=false,pending=false,spawned=false;
};
std::array<State,4> states;
bool MatrixValid(const Matrix& matrix) {
    for (unsigned r=0;r<4;++r) for (unsigned a=0;a<3;++a)
        if (!std::isfinite(matrix[r*4+a]) || std::abs(matrix[r*4+a])>1000000.f) return false;
    for (unsigned r=0;r<3;++r) {
        float length=0;for (unsigned a=0;a<3;++a) length+=matrix[r*4+a]*matrix[r*4+a];
        if (!std::isfinite(length) || std::abs(length-1.f)>.02f) return false;
    }
    return true;
}
Matrix Placement(const Release& release,const Matrix& gun) {
    Matrix result{};
    for (unsigned r=0;r<3;++r) for (unsigned a=0;a<3;++a)
        for (unsigned k=0;k<3;++k) result[r*4+a]+=release.local[r*4+k]*gun[k*4+a];
    for (unsigned a=0;a<3;++a) {
        result[12+a]=gun[12+a];
        for (unsigned k=0;k<3;++k) result[12+a]+=release.local[12+k]*gun[k*4+a];
    }
    return result;
}
bool AttachedRow(const uint8_t* base,uint32_t row,const Held& held,unsigned hand) {
    const auto locator=Component(base,held.owner,0x422590);
    uint16_t n=0;uint32_t rows=0;
    if (!locator || !Read(base,uint64_t(locator)+0x20,n) || !n || n>128 ||
        !Read(base,uint64_t(locator)+0x24,rows) || !Span(base,rows,n*0x40) ||
        row<rows || uint64_t(row)>=uint64_t(rows)+n*0x40 || (row-rows)%0x40 ||
        !Name(base,uint64_t(row)+0x10,hand?"loc_LeftHandDualWield":"loc_RightHand")) return false;
    uint32_t refs=0;uint16_t count=0;
    if (!Read(base,row,count) || !count || count>64 || !Read(base,uint64_t(row)+4,refs) || !Span(base,refs,count*16)) return false;
    unsigned found=0;
    for (unsigned i=0;i<count;++i) {uint32_t a=0;if (!Read(base,uint64_t(refs)+i*16,a)) return false;found+=a==held.weapon;}
    return found==1;
}
void Observe(const X86Context& entry,uint8_t* base) {
    uint32_t actor=0,pose=0;
    if (base!=kernel::g_base || !Read(base,uint64_t(entry.esp)+4,actor) ||
        !Read(base,uint64_t(entry.esp)+8,pose)) return;
    const auto animation=Component(base,actor,0x41D258);
    if (!animation || uint64_t(animation)+0x30!=pose) return;
    std::array<uint32_t,2> players{};
    if (!Players(base,players)) return;
    for (unsigned p=0;p<2;++p) if (players[p] && players[p]==actor) for (unsigned hand=0;hand<2;++hand) {
        Held held;Reload reload;Matrix gun;
        if (!Owned(base,actor,hand,held) || !AttachedRow(base,entry.ecx,held,hand)) continue;
        auto& state=states[p*2+hand];
        if (!Clock(base,held,reload)) {state={};continue;}
        uint32_t zone=0,world=0;
        if (!Read(base,uint64_t(actor)+0x68,zone) || !Read(base,uint64_t(actor)+0x6C,world) ||
            !Read(base,uint64_t(held.weapon)+0x10,gun) || !MatrixValid(gun)) continue;
        if (state.held.owner!=actor || state.held.weapon!=held.weapon || state.reload.controller!=reload.controller ||
            state.zone!=zone || state.world!=world ||
            reload.phase+.01f<state.reload.phase) state={};
        state.held=held;state.reload=reload;state.zone=zone;state.world=world;
        const auto& release=*held.release;
        if (!state.attempted && reload.phase>=release.outbound) {
            state.attempted=true;
            state.pending=reload.phase<release.incoming;
        }
        if (state.pending) state.placement=Placement(release,gun);
    }
}
void Flush(const X86Context& ctx,uint8_t* base) {
    std::array<uint32_t,2> players{};
    if (!Players(base,players)) {states={};feet={};return;}
    KickFeet(ctx,base,players);
    for (unsigned i=0;i<states.size();++i) {
        auto& state=states[i];
        if (!state.held.weapon) continue;
        Held held;Reload reload;uint32_t zone=0,world=0;
        if (players[i/2]!=state.held.owner || !Owned(base,players[i/2],i%2,held) ||
            held.weapon!=state.held.weapon || !Clock(base,held,reload) ||
            reload.controller!=state.reload.controller ||
            reload.phase+.01f<state.reload.phase ||
            !Read(base,uint64_t(held.owner)+0x68,zone) || zone!=state.zone ||
            !Read(base,uint64_t(held.owner)+0x6C,world) || world!=state.world) {state={};continue;}
        state.reload=reload;
        if (!state.pending) continue;
        state.pending=false;
        if (reload.phase>=held.release->incoming) continue;
        state.spawned=darkwatch::clips::CreateNativeProp(ctx,base,held.owner,held.release->kind,state.placement)!=0;
    }
}
}

bool DarkwatchClipFootPlayer(const uint8_t* base,uint32_t actor) {
    Feet pose;std::array<uint32_t,2> players{};
    return base==kernel::g_base && DarkwatchPrivateClipFixtureReady() && Players(base,players) &&
        (players[0]==actor || players[1]==actor) && FootPose(base,actor,pose);
}
void DarkwatchClipFootClock(const X86Context& ctx,uint8_t* base) {
    uint32_t type=0,actor=0;float dt=0;
    if(base!=kernel::g_base || !DarkwatchPrivateClipFixtureReady() || ctx.ecx<0x1E8 ||
       !Read(base,ctx.ecx-0x1E8,type)||type!=0x41F878||
       !Read(base,uint64_t(ctx.ecx)-0x1E8+12,actor)||
       !Read(base,uint64_t(ctx.esp)+4,dt)||!std::isfinite(dt)||dt<0||dt>.1f)return;
    for(auto& state:feet)if(state.valid&&state.actor==actor) {
        state.dt+=dt;
#ifndef XBE_RELEASE
        static unsigned witnesses=0;
        if(witnesses++<8)std::fprintf(stderr,"[clip-foot-clock] actor=%08X dt=%.6f accumulated=%.6f\n",actor,dt,state.dt);
#endif
    }
}

X86_FUNC(sub_000AA19F) {
    const auto entry=ctx;
    __imp__sub_000AA19F(ctx,base);
    if (DarkwatchPrivateClipFixtureReady()) Observe(entry,base);
}

X86_FUNC(sub_00215D9F) {
    uint32_t caller=0,manager=0;
    const bool frame=base==kernel::g_base && Read(base,ctx.esp,caller) && caller==0x1E8C41 &&
        Read(base,0x4AC118,manager) && ctx.ecx==manager;
    __imp__sub_00215D9F(ctx,base);
    // Native component traversal and its queued actor removals have finished.
    // Do not mutate actors from AA19F's additional draw-time refreshes.
    if (frame && DarkwatchPrivateClipFixtureReady()) Flush(ctx,base);
}

bool DarkwatchEjectedClipSkinPalette(X86Context& ctx,uint8_t* base) {
    if (base!=kernel::g_base || !DarkwatchPrivateClipFixtureReady()) return false;
    uint32_t atomic=0,offset=0,hierarchy=0,bones=0,flags=0,matrices=0,skin=0,count=0,output=0;
    if (!Read(base,uint64_t(ctx.esp)+8,atomic) || !atomic || !Read(base,0x4BA834,offset) || !offset || offset>=0x1000 ||
        !Read(base,uint64_t(atomic)+offset,hierarchy) || !hierarchy ||
        !Read(base,hierarchy,flags) || (flags&2) || !Read(base,uint64_t(hierarchy)+4,bones) || (bones!=4 && bones!=5 && bones!=8) ||
        !Read(base,uint64_t(hierarchy)+8,matrices) || !Span(base,matrices,bones*64) ||
        !Read(base,uint64_t(ctx.esp)+4,output) || !Read(base,uint64_t(ctx.esp)+12,skin) || !skin ||
        !Read(base,uint64_t(skin)+0x81C,count) || !count || count>bones || !Span(base,output,count*48) ||
        (uint64_t(output)<uint64_t(matrices)+bones*64 && uint64_t(matrices)<uint64_t(output)+count*48)) return false;
    for (unsigned i=0;i<states.size();++i) {
        const auto& state=states[i];Held held;Reload reload;
        if (!state.spawned || state.reload.hierarchy!=hierarchy ||
            !Owned(base,state.held.owner,i%2,held) || held.weapon!=state.held.weapon ||
            !Clock(base,held,reload) || reload.controller!=state.reload.controller || reload.hierarchy!=hierarchy ||
            reload.clock!=state.reload.clock || reload.resource!=state.reload.resource ||
            reload.phase<held.release->outbound || reload.phase>=held.release->incoming) continue;
        const auto address=uint64_t(matrices)+held.release->bone*64;
        Matrix saved,hidden;
        if (!Read(base,address,saved)) return false;
        hidden=saved;
        for (unsigned r=0;r<3;++r) for (unsigned a=0;a<3;++a) hidden[r*4+a]=0;
        struct Restore { uint8_t* at;const Matrix& saved;~Restore(){std::memcpy(at,saved.data(),sizeof(saved));} } restore{base+address,saved};
        std::memcpy(base+address,hidden.data(),sizeof(hidden));
        __imp__sub_00260D40(ctx,base);return true;
    }
    return false;
}
