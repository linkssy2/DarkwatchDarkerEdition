#include "weapon_wheel.h"
#include "carry_all_weapons.h"
#include "controls.h"
#include "settings_skin.h"
#include "graphics_view.h"
#include "language.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <algorithm>
#include <atomic>
#include <bit>
#include <cmath>
#include <cstring>
#include <mutex>

X86_EXTERN_FUNC(__imp__sub_0021C387);
namespace {
constexpr float pi=3.14159265358979323846f;
struct Wheel {
    DarkwatchWeaponChoices choices;
    uint64_t epoch=0,generation=0,x=0,y=0;
    float dx=0,dy=0;
    unsigned selected=0;
    bool down=false,open=false;
};
Wheel wheel;
std::mutex wheel_mutex;
std::atomic<bool> open{false},slow{false};
std::atomic<uint64_t> consumed{0};
unsigned Select(uint32_t mask,float x,float y) {
    if (x*x+y*y<18*18) return 0;
    unsigned count=std::popcount(mask);if(!count)return 0;
    float angle=std::atan2(y,x)+pi/2+pi/count;
    if(angle<0)angle+=2*pi;if(angle>=2*pi)angle-=2*pi;
    unsigned index=std::min(count-1,unsigned(angle*count/(2*pi)));
    for(unsigned id=1;id<=9;++id)if(mask&(1u<<id)){if(!index--)return id;}
    return 0;
}
void Close(){wheel.open=false;wheel.selected=0;open=false;slow=false;}
void WeaponOutline(ImDrawList* draw,unsigned id,ImVec2 at,float scale){
    const auto ivory=IM_COL32(242,238,224,255);
    auto line=[&](std::initializer_list<ImVec2> points,bool closed=false,float ox=0,float oy=0,float zoom=1){
        ImVec2 vertices[64];unsigned count=0;
        IM_ASSERT(points.size()<=std::size(vertices));
        for(auto p:points)vertices[count++]={at.x+(p.x*zoom+ox)*scale,at.y+(p.y*zoom+oy)*scale};
        const auto flags=closed?ImDrawFlags_Closed:ImDrawFlags_None;
        draw->AddPolyline(vertices,count,IM_COL32(0,0,0,210),flags,std::max(1.8f,3.2f*scale));
        draw->AddPolyline(vertices,count,ivory,flags,std::max(.8f,1.3f*scale));
    };
    auto pistol=[&](float ox,float oy,float zoom){
        line({{-29,17},{-27,7},{-22,-3},{-14,-9},{-9,-11},{-9,-16},{-5,-12},{4,-12},{4,-10},{32,-10},{32,-5},{5,-5},{5,2},{-5,2},{-10,8},{-10,15},{-4,20},{4,23},{-16,22}},true,ox,oy,zoom);
        line({{-23,13},{-21,4},{-15,-2},{-13,3},{-16,12},{-12,18}},false,ox,oy,zoom);
        line({{-9,-10},{2,-10},{2,0},{-9,0}},true,ox,oy,zoom);
        line({{-6,-8},{-6,-2},{-3,-2},{-3,-8}},false,ox,oy,zoom);
        line({{7,-8},{28,-8}},false,ox,oy,zoom);
        line({{-13,2},{-9,7},{-3,7},{0,2}},false,ox,oy,zoom);
        line({{27,-10},{29,-14},{32,-10}},false,ox,oy,zoom);
    };
    if(id==1){pistol(0,-3,1.1f);return;}
    if(id==3){pistol(-10,-11,.88f);pistol(12,9,.88f);return;}
    if(id==2){
        line({{-42,18},{-38,5},{-30,-6},{-20,-12},{-18,-17},{-12,-12},{3,-12},{3,-14},{39,-14},{44,-18},{46,-14},{46,-7},{31,-7},{31,8},{-9,8},{-17,3},{-23,8},{-27,18},{-23,24},{-13,28},{-34,26}},true);
        line({{-9,-8},{30,-8},{30,5},{-9,5}},true);
        line({{-6,-4},{5,-4},{9,0},{15,-4},{21,-4},{25,0},{29,-4}});
        line({{4,-11},{40,-11}});line({{-13,-10},{-13,3}});
        line({{-23,2},{-19,10},{-12,10},{-8,5}});line({{-34,15},{-29,5},{-24,0}});return;
    }
    if(id==4){
        line({{-49,7},{-44,-2},{-31,0},{-19,-6},{-12,-12},{-9,-8},{23,-8},{28,-5},{44,-3},{32,1},{28,6},{11,6},{11,14},{-5,14},{-5,5},{-17,2},{-30,8},{-32,15},{-39,10},{-49,14}},true);
        line({{-15,-4},{24,-4}});line({{-8,1},{24,1}});line({{-4,6},{8,6},{8,11},{-4,11}},true);
        line({{17,-5},{12,-17},{3,-25},{-4,-27},{5,-22},{10,-14},{13,-3}});
        line({{17,0},{12,15},{3,25},{-4,28},{5,22},{10,13},{13,0}});
        line({{-4,-27},{22,-2},{-4,28}});line({{22,-2},{49,-2},{45,-5}});
        line({{-43,3},{-34,4},{-35,9}});return;
    }
    if(id==5){
        line({{-49,-16},{-46,-21},{-44,-16},{-40,-22},{-37,-16},{-34,-21},{-32,-16},{-32,14},{-36,19},{-38,14},{-42,20},{-45,14},{-49,14}},true);
        line({{-46,-12},{-35,-12},{-35,10},{-46,10}},true);
        line({{-45,-10},{-36,8},{-45,8},{-36,-10}},true);
        line({{-32,-7},{-5,-7},{-5,-12},{4,-12},{4,-7},{39,-7},{46,-14},{46,12},{39,5},{19,5},{19,10},{25,22},{19,22},{11,9},{0,9},{-8,18},{-13,16},{-8,6},{-32,6}},true);
        line({{-29,-3},{42,-3}});line({{-29,2},{42,2}});
        line({{-6,-7},{-6,6},{11,6},{11,-7}},true);
        line({{36,-7},{36,6}});line({{39,-7},{39,6}});
        line({{-3,9},{-3,14},{5,14},{8,9}});return;
    }
    if(id==6){
        line({{-49,17},{-44,7},{-46,-1},{-31,0},{-20,-4},{-10,-11},{-8,-7},{5,-7},{5,-5},{45,-5},{45,-9},{49,-5},{49,-1},{15,-1},{12,3},{-8,3},{-19,10},{-25,17},{-50,23}},true);
        line({{-40,4},{-29,5},{-20,2}});line({{-43,17},{-29,12},{-23,8}});
        line({{-17,6},{-21,15},{-17,17},{-7,12},{-2,6},{-7,3}},true);
        line({{-8,-5},{1,-5},{1,1},{-8,1}},true);
        line({{5,-2},{43,-2}});line({{7,2},{16,2}});return;
    }
    if(id==7){
        line({{-49,13},{-39,18},{-34,9},{-30,-1},{-19,-9},{-16,-14},{-15,-9},{-7,-9},{-7,-7},{47,-7},{47,0},{22,0},{22,5},{18,10},{14,5},{-7,5},{-11,2},{-17,8},{-18,16},{-13,25},{-28,23},{-39,20}},true);
        line({{-25,8},{-23,2},{-17,-2},{-17,4},{-20,12},{-17,18}});
        line({{-7,-4},{45,-4}});line({{2,1},{2,5},{16,5},{16,1}},true);
        line({{5,1},{5,5}});line({{9,1},{9,5}});line({{13,1},{13,5}});
        line({{-15,-7},{-9,-7},{-9,0},{-15,0}},true);line({{-19,3},{-13,8},{-8,6},{-7,2}});return;
    }
    if(id==8){
        line({{-50,18},{-42,12},{-43,1},{-32,1},{-25,6},{-16,-3},{-12,-5},{41,-5},{49,-6},{49,-1},{39,-1},{-9,-1},{-18,9},{-25,10},{-24,15},{-42,17}},true);
        line({{-25,6},{-24,12},{-17,9},{-14,3}});line({{-39,5},{-33,6},{-29,11},{-39,13}});
        line({{-17,-8},{-17,-13},{-3,-13},{-3,-9},{-17,-9}},true);
        line({{-21,-14},{-20,-17},{-14,-17},{-14,-14},{-3,-14},{-3,-17},{4,-17},{4,-10},{-3,-10},{-3,-12},{-14,-12},{-14,-10},{-20,-10}},true);
        line({{-12,-8},{-12,-5}});line({{0,-8},{0,-5}});
        line({{8,-3},{36,-3}});line({{40,-5},{40,-1}});return;
    }
    if(id==9){
        line({{-43,21},{15,-9},{18,-4},{-40,25}},true);
        line({{-32,17},{-29,21}});line({{-25,13},{-22,17}});line({{-18,9},{-15,13}});
        line({{10,-10},{12,-19},{17,-22},{20,-29},{23,-20},{30,-17},{39,-18},{35,-11},{36,-4},{41,1},{33,3},{28,9},{23,5},{17,6},{17,-2}},true);
        line({{18,-15},{24,-17},{31,-12},{31,-5},{27,0},{20,-2},{17,-8}},true);
        line({{19,-11},{23,-10},{22,-7}},true);line({{26,-13},{29,-11},{26,-8}},true);
        line({{23,-5},{26,-5},{25,-2}});line({{20,1},{22,4},{25,2},{28,5}});return;
    }
}
template<class T>bool Read(const uint8_t* base,uint32_t at,T& out){
    if(!base||!at||uint64_t(at)+sizeof(T)>(uint64_t(1)<<32))return false;
    for(uint64_t p=at&~uint64_t(mem::kPage-1);p<uint64_t(at)+sizeof(T);p+=mem::kPage)if(!mem::IsCommitted(uint32_t(p)))return false;
    std::memcpy(&out,base+at,sizeof(T));return true;
}
bool CutsceneActive(){
    // Native cinematic manager: entering, playing, leaving (sub_0021B841).
    uint32_t phase=0;
    return Read(kernel::g_base,0x4B7A4C,phase)&&phase>=1&&phase<=3;
}
}
bool DarkwatchWeaponWheelOpen(){return open.load()&&!CutsceneActive();}
std::array<float,4> DarkwatchWeaponWheelViewport(){std::lock_guard lock(wheel_mutex);return wheel.choices.viewport;}
bool DarkwatchWeaponWheelBlocksLook(uint64_t generation){return !CutsceneActive()&&(open.load()||(generation && consumed.load()==generation));}
unsigned DarkwatchWeaponWheelInput(int port,input::Pad& pad){
    if(port!=0)return 0;
    const auto frame=input::GetMouseSnapshot();
    const bool down=input::PcKeyDown(4);
    const auto settings=darkwatch::ControlsSnapshot();
    const bool enabled=settings.weapon_wheel&&settings.carry_all_weapons;
    std::lock_guard lock(wheel_mutex);
    if(!enabled||CutsceneActive()||!frame.active||!frame.published_us||frame.active_epoch!=wheel.epoch){
        Close();wheel={};wheel.epoch=frame.active_epoch;wheel.down=down;return 0;
    }
    unsigned result=0;
    if(down&&!wheel.down){
        auto choices=DarkwatchGetWeaponChoices(0);
        if(choices.mask){wheel.choices=choices;wheel.dx=wheel.dy=0;wheel.x=frame.accumulated_x;wheel.y=frame.accumulated_y;wheel.open=true;open=true;slow=choices.solo;}
    }
    if(wheel.open){
        const auto choices=DarkwatchGetWeaponChoices(0);
        if(!choices.mask||choices.actor!=wheel.choices.actor){Close();wheel.down=down;return 0;}
        wheel.choices=choices;slow=choices.solo;
        if(frame.generation!=wheel.generation){
            wheel.dx+=float(std::bit_cast<int64_t>(frame.accumulated_x-wheel.x));
            wheel.dy+=float(std::bit_cast<int64_t>(frame.accumulated_y-wheel.y));
            float length=std::hypot(wheel.dx,wheel.dy);
            if(length>120){wheel.dx*=120/length;wheel.dy*=120/length;}
            wheel.x=frame.accumulated_x;wheel.y=frame.accumulated_y;wheel.generation=frame.generation;
        }
        wheel.selected=Select(choices.mask,wheel.dx,wheel.dy);consumed=frame.generation;
        // Keep movement available, but do not fire, reload, or aim behind the wheel.
        pad.buttons&=uint16_t((1u<<4)|(1u<<5));std::fill(std::begin(pad.analog),std::end(pad.analog),0);pad.rx=pad.ry=0;
        if(!down){result=wheel.selected;Close();}
    }
    wheel.down=down;return result;
}

void DarkwatchWeaponWheelDraw(){
    if(CutsceneActive()){std::lock_guard lock(wheel_mutex);Close();return;}
    Wheel state;{std::lock_guard lock(wheel_mutex);state=wheel;}if(!state.open)return;
    auto* draw=ImGui::GetForegroundDrawList();const auto size=ImGui::GetIO().DisplaySize;
    const auto view=state.choices.viewport;
    const ImVec2 extent{size.x*view[2],size.y*view[3]};
    const float scale=std::min(extent.x/960.f,extent.y/720.f),r=224*scale,inner=86*scale;
    if(scale<=0)return;
    const ImVec2 center{size.x*view[0]+extent.x*.5f,size.y*view[1]+extent.y*.5f};
    const unsigned count=std::popcount(state.choices.mask);if(!count)return;
    const auto fonts=darkwatch::skin::Select(darkwatch::view::Snapshot().hd_ui);
    auto* font=fonts.body?fonts.body:ImGui::GetFont();
    auto text=[&](const char* label,ImVec2 at,float height,ImU32 color,float width){
        label=darkwatch::language::Text(label);
        const float available=std::max(1.f,std::min(width,2*std::min(at.x-size.x*view[0],size.x*(view[0]+view[2])-at.x)-8));
        auto measured=font->CalcTextSizeA(height,10000,0,label);
        if(measured.x>available){height*=available/measured.x;measured=font->CalcTextSizeA(height,10000,0,label);}
        draw->AddText(font,height,{at.x-measured.x*.5f,at.y-measured.y*.5f},color,label);
    };
    const auto ivory=IM_COL32(231,229,215,255),steel=IM_COL32(119,128,132,255);
    draw->AddCircleFilled(center,r+10*scale,IM_COL32(3,4,5,245),96);
    draw->AddCircle(center,r+7*scale,steel,96,5*scale);
    draw->AddCircle(center,r+10*scale,IM_COL32(198,204,201,255),96,scale);
    draw->AddCircle(center,r+3*scale,IM_COL32(31,37,42,255),96,2*scale);
    constexpr const char* names[]{"","Revolver","Redeemer","Dual Pistols","Crossbow","Rocket Launcher","Carbine","Shotgun","Sniper Rifle","Scepter"};
    unsigned index=0;
    for(unsigned id=1;id<=9;++id)if(state.choices.mask&(1u<<id)){
        float angle=-pi/2+2*pi*index++/count,half=pi/count;
        auto point=[&](float radius,float a){return ImVec2{center.x+radius*std::cos(a),center.y+radius*std::sin(a)};};
        const auto flags=draw->Flags;draw->Flags&=~ImDrawListFlags_AntiAliasedFill;
        for(unsigned step=0;step<24;++step){
            const float a=angle-half+.015f+(2*half-.03f)*step/24,b=angle-half+.015f+(2*half-.03f)*(step+1)/24;
            draw->AddQuadFilled(point(inner,a),point(r,a),point(r,b),point(inner,b),
                state.selected==id?IM_COL32(125,7,12,245):IM_COL32(12,14,16,240));
        }
        draw->Flags=flags;
        if(count>1)draw->AddLine(point(inner,angle-half),point(r,angle-half),steel,scale);
        auto rivet=point(r+7*scale,angle-half);
        draw->AddCircleFilled(rivet,3*scale,IM_COL32(20,23,26,255),8);
        draw->AddCircle(rivet,2*scale,ivory,8,scale);
        ImVec2 at=point((inner+r)*.5f,angle);
        WeaponOutline(draw,id,at,scale*.9f);
        if(scale>=.65f)text(names[id],{at.x,at.y+32*scale},12*scale,ivory,100*scale);
        if(id==state.choices.current)draw->AddLine({at.x-12*scale,at.y-31*scale},{at.x+12*scale,at.y-31*scale},ivory,2*scale);
    }
    draw->AddCircleFilled(center,inner-2*scale,IM_COL32(6,7,9,250),64);
    draw->AddCircle(center,inner,steel,64,2*scale);
    darkwatch::skin::Row(draw,{center.x-78*scale,center.y-19*scale},{center.x+78*scale,center.y+19*scale},state.selected!=0);
    text("WEAPONS",{center.x,center.y-43*scale},14*scale,ivory,130*scale);
    text(state.selected?names[state.selected]:names[state.choices.current],center,16*scale,ivory,140*scale);
    text("Release to select",{center.x,center.y+40*scale},11*scale,ivory,132*scale);
    draw->AddCircleFilled({center.x+state.dx*scale,center.y+state.dy*scale},3*scale,ivory);

}

X86_FUNC(sub_0021C387){
    uint32_t caller=0,mode=0;float factor=1;
    const bool scale=base==kernel::g_base&&slow.load()&&DarkwatchWeaponWheelOpen()&&input::GetMouseSnapshot().active&&
        ctx.ecx==0x4B7AC0&&Read(base,ctx.esp,caller)&&caller==0x1E8C67&&
        Read(base,0x4B7B00,mode)&&mode<=1&&Read(base,0x49CE44,factor)&&std::isfinite(factor)&&factor>0&&factor<=8;
    if(!scale){__imp__sub_0021C387(ctx,base);return;}
    const float reduced=(mode?factor:1.f)*.2f;const uint32_t scaled_mode=1;
    std::memcpy(base+0x4B7B00,&scaled_mode,4);std::memcpy(base+0x49CE44,&reduced,4);
    struct Restore{uint8_t* b;uint32_t m;float f;~Restore(){std::memcpy(b+0x4B7B00,&m,4);std::memcpy(b+0x49CE44,&f,4);}}restore{base,mode,factor};
    __imp__sub_0021C387(ctx,base);
}
