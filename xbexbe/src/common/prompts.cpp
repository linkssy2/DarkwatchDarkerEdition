#include "prompts.h"
#include "prompt_owner.h"
#include "controls.h"
#include "language.h"
#include "hd_ui_assets.h"
#include "hd_ui_font.h"
#include "app/app.h"
#include "core/log.h"
#include "core/diag.h"
#include "cpu/x86_context.h"
#include "kernel/disc.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include "gpu/ext.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <mutex>
#include <memory>
#include <string>
#include <vector>

void DarkwatchRefreshMenuBars(uint8_t*, uint64_t);

namespace {
// Original localization/preset, font-list and RenderWare witnesses are pinned in
// Prompt identities were checked against the original resources; files remain unchanged.
constexpr std::array<uint8_t, 26> kCodes = {
    'a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p',1,2,3,4,5,6,7,8,9,11};
constexpr std::array<uint8_t, 20> kActions = {10,11,8,9,15,13,7,14,12,6,5,4,2,3,0,1,16,17,18,19};
constexpr unsigned kAtlasWidth = 1024, kCellHeight = 32;
// Input binding 256 is the wheel; atlas badge256 already means generic mouse.
constexpr unsigned kMouseWheelBadge = 261;
constexpr unsigned kControllerBadge = kMouseWheelBadge + 1, kFamilyBadges = 18;
struct Badge { uint16_t x=0,y=0,width=0; };
struct Atlas { std::vector<uint8_t> pixels; std::array<Badge,kControllerBadge+2*kFamilyBadges> badges{}; unsigned height=0; };
struct Glyph { float width; uint32_t texture; float uv[4]; uint32_t path,index; };
static_assert(sizeof(Glyph)==32);
struct Font {
    uint32_t address=0,list=0,data=0,first=0,texture=0;
    std::array<int16_t,kCodes.size()> original{};
    uint64_t revision=0;
};
std::recursive_mutex g_lock;
std::array<Font,16> g_fonts{};
Atlas g_atlas;
struct PromptHd { std::vector<uint8_t> original, pixels; uint64_t id=0; unsigned height=0; };
std::shared_ptr<const PromptHd> g_prepared_hd;
std::shared_ptr<const PromptHd> g_prompt_hd;
std::atomic<uint64_t> g_prompt_revision{0};
#ifndef XBE_RELEASE
std::atomic<bool> g_prompt_logged{false};
#endif
bool g_tried_hd=false;
uint32_t g_texture=0;
bool g_failed=false, g_have_settings=false;
uint64_t g_revision=0;
input::DeviceSnapshot g_device{};
input::PadBindings g_controller_bindings{};
darkwatch::ControlsSettings g_settings{};
thread_local bool g_in_call=false;
std::array<uint64_t,16> g_font_trace{};
unsigned g_font_traces=0;

bool Span(const uint8_t* base,uint64_t p,uint64_t size) {
    if (!base || !p || !size || p+size>uint64_t(1)<<32) return false;
    for (uint64_t page=p&~uint64_t(mem::kPage-1);page<p+size;page+=mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base,uint64_t p,T& value) {
    if (!Span(base,p,sizeof(value))) return false;
    std::memcpy(&value,base+p,sizeof(value)); return true;
}
void TraceFont(const uint8_t* base,uint32_t font,unsigned reason) {
    if(!diag::Perf())return;
    const uint64_t key=uint64_t(font)<<32|reason;
    if(g_font_traces==g_font_trace.size()||std::find(g_font_trace.begin(),g_font_trace.begin()+g_font_traces,key)!=g_font_trace.begin()+g_font_traces)return;
    g_font_trace[g_font_traces++]=key;
    uint32_t callback=0,count=0,list=0,listcount=0,stride=0,texture=0;
    Read(base,uint64_t(font)+0x138,callback);Read(base,uint64_t(font)+0x130,count);Read(base,uint64_t(font)+0x134,list);
    if(list){Read(base,uint64_t(list)+4,listcount);Read(base,uint64_t(list)+12,stride);}
    Read(base,uint64_t(font)+0x14,texture);
    char name[33]{};if(texture&&Span(base,uint64_t(texture)+16,32))std::memcpy(name,base+texture+16,32);
    for(char& c:name)if(uint8_t(c)<32||uint8_t(c)>126)c='?';name[32]=0;
    LOGI("PC prompt font: font=%08X reason=%u callback=%08X count=%u list=%08X list_count=%u stride=%u texture=%08X name=%.32s",font,reason,callback,count,list,listcount,stride,texture,name);
}
uint32_t U32(const uint8_t* p) { uint32_t v;std::memcpy(&v,p,4);return v; }
uint16_t U16(const uint8_t* p) { uint16_t v;std::memcpy(&v,p,2);return v; }
float Float(const uint8_t* p) { float v;std::memcpy(&v,p,4);return v; }
uint64_t Hash(const std::vector<uint8_t>& bytes) {
    uint64_t h=14695981039346656037ull;
    for(uint8_t b:bytes) h=(h^b)*1099511628211ull;
    return h;
}
bool Package(uint64_t offset,std::vector<uint8_t>& bytes) {
    if(const auto* disc=kernel::MountedDisc()) {
        const auto* file=disc->Find("packfile.pck");
        return file && !file->dir && offset+bytes.size()<=file->size &&
            disc->Read(*file,offset,bytes.data(),uint32_t(bytes.size()))==bytes.size();
    }
    for(auto dir=app::ExeDir();!dir.empty();) {
        std::ifstream file(dir/"assets"/"packfile.pck",std::ios::binary);
        if(file) { file.seekg(std::streamoff(offset));return bool(file.read(reinterpret_cast<char*>(bytes.data()),bytes.size())); }
        auto parent=dir.parent_path();if(parent==dir)break;dir=std::move(parent);
    }
    return false;
}
using Symbol = darkwatch::ControllerPromptSymbol;
darkwatch::ControllerPrompt ControllerBadgeInfo(unsigned key) {
    if(key<kControllerBadge||key>=kControllerBadge+2*kFamilyBadges)return {"",Symbol::None};
    const unsigned index=key-kControllerBadge,action=index%kFamilyBadges;
    if(action>=16)return {action==16?"L":"R",action==16?Symbol::LeftStick:Symbol::RightStick};
    return darkwatch::ControllerPromptInfo(index<kFamilyBadges?input::ControllerFamily::PlayStation:input::ControllerFamily::Switch,
                                          static_cast<input::PcAction>(action));
}
unsigned ControllerBadge(input::ControllerFamily family,unsigned action) {
    return kControllerBadge+(family==input::ControllerFamily::Switch?kFamilyBadges:0)+action;
}
bool StickSymbol(Symbol symbol) {
    return symbol==Symbol::LeftStick||symbol==Symbol::RightStick||
           symbol==Symbol::LeftStickPress||symbol==Symbol::RightStickPress;
}
bool PressSymbol(Symbol symbol) {return symbol==Symbol::LeftStickPress||symbol==Symbol::RightStickPress;}
std::string Label(unsigned key) {
    if(key>=kControllerBadge)return ControllerBadgeInfo(key).label;
    if(key>='A'&&key<='Z')return std::string(1,char(key));
    if(key>='0'&&key<='9')return std::string(1,char(key));
    if(key>=0x70&&key<=0x87)return "F"+std::to_string(key-0x6F);
    if(key>=0x60&&key<=0x69)return "NUM"+std::to_string(key-0x60);
    switch(key) {
        case 0:return "NONE"; case 1:return "MOUSE L";case 2:return "MOUSE R";case 4:return "MOUSE M";
        case 5:return "MOUSE 4";case 6:return "MOUSE 5";case 256:return "MOUSE";
        case 257:return "START";case 258:return "BACK";
        case 259:return "LEFT STICK";case 260:return "RIGHT STICK";
        case kMouseWheelBadge:return "MOUSE WHEEL";
        case 8:return "BKSP";case 9:return "TAB";case 13:return "ENTER";
        case 16:return "SHIFT";case 17:return "CTRL";case 18:return "ALT";
        case 19:return "PAUSE";case 20:return "CAPS";case 27:return "ESC";case 32:return "SPACE";
        case 33:return "PGUP";case 34:return "PGDN";case 35:return "END";case 36:return "HOME";
        case 37:return "LEFT";case 38:return "UP";case 39:return "RIGHT";case 40:return "DOWN";
        case 45:return "INS";case 46:return "DEL";case 91:return "LWIN";case 92:return "RWIN";
        case 106:return "NUM*";case 107:return "NUM+";case 109:return "NUM-";case 110:return "NUM.";case 111:return "NUM DIV";
        case 144:return "NUMLOCK";case 145:return "SCROLL";
        case 160:return "LSHIFT";case 161:return "RSHIFT";case 162:return "LCTRL";case 163:return "RCTRL";
        case 164:return "LALT";case 165:return "RALT";
        case 186:return ";";case 187:return "=";case 188:return ",";case 189:return "-";
        case 190:return ".";case 191:return "SLASH";case 192:return "GRAVE";case 219:return "LBRKT";
        case 220:return "BKSLASH";case 221:return "RBRKT";case 222:return "'";
    }
    char name[8];std::snprintf(name,sizeof(name),"VK%02X",key);return name;
}
bool Arrow(unsigned key) { return key>=37&&key<=40; }
bool MouseButton(unsigned key) { return key==1||key==2; }
void DrawMouseButton(std::vector<uint8_t>& pixels,unsigned stride,Badge rect,unsigned key,unsigned density) {
    for(unsigned y=0;y<32*density;++y)for(unsigned x=0;x<rect.width*density;++x) {
        unsigned sum[3]{},covered=0;
        for(unsigned sy=0;sy<4;++sy)for(unsigned sx=0;sx<4;++sx) {
            const float px=(x+(sx+.5f)/4)/density-14,py=(y+(sy+.5f)/4)/density-16;
            const float dx=std::max(std::abs(px)-2,0.f),dy=std::max(std::abs(py)-6,0.f);
            const float distance=dx*dx+dy*dy;
            if(distance>36)continue;
            const bool rim=distance>=4.6f*4.6f;
            const bool selected=py< -1.3f&&((key==1&&px<-.7f)||(key==2&&px>.7f));
            const bool wheel=key==kMouseWheelBadge?
                std::abs(px)<1.6f&&py>=-8&&py< -1:
                std::abs(px)<.55f&&py>=-8&&py< -4;
            const bool light=rim||selected||wheel;
            sum[0]+=light?250:24;sum[1]+=light?243:22;sum[2]+=light?224:21;++covered;
        }
        if(!covered)continue;
        auto* d=pixels.data()+((rect.y*density+y)*stride+rect.x*density+x)*4;
        for(unsigned c=0;c<3;++c)d[c]=uint8_t((unsigned(d[c])*(16-covered)+sum[c])/16);
        d[3]=255;
    }
}
void DrawMouseWheel(std::vector<uint8_t>& pixels,unsigned stride,Badge rect,unsigned density) {
    DrawMouseButton(pixels,stride,rect,kMouseWheelBadge,density);
    // Both arrows indicate that either wheel direction activates this binding.
    for(unsigned y=0;y<32*density;++y)for(unsigned x=0;x<rect.width*density;++x) {
        unsigned covered=0;
        for(unsigned sy=0;sy<4;++sy)for(unsigned sx=0;sx<4;++sx) {
            const float px=(x+(sx+.5f)/4)/density-30,py=std::abs((y+(sy+.5f)/4)/density-16);
            covered+=(py>=4&&py<=9&&std::abs(px)<=9-py)||(py>=1&&py<4&&std::abs(px)<1.3f);
        }
        if(!covered)continue;
        auto* d=pixels.data()+((rect.y*density+y)*stride+rect.x*density+x)*4;
        const unsigned a=covered*255/16;
        for(unsigned c=0;c<3;++c)d[c]=uint8_t((unsigned(d[c])*(255-a)+(c==0?250:c==1?243:224)*a)/255);
        d[3]=255;
    }
}
// Analytic arrow, sampled at the destination density. No font substitution or
// unsupported Unicode glyph is involved, including for the original-size atlas.
void DrawArrow(std::vector<uint8_t>& pixels,unsigned stride,Badge rect,unsigned key,unsigned density) {
    for(unsigned y=0;y<32*density;++y)for(unsigned x=0;x<rect.width*density;++x) {
        unsigned covered=0;
        for(unsigned sy=0;sy<4;++sy)for(unsigned sx=0;sx<4;++sx) {
            float px=(x+(sx+.5f)/4)/density-14,py=(y+(sy+.5f)/4)/density-16;
            if(key==37){const float t=px;px=-py;py=t;}
            if(key==39){const float t=px;px=py;py=-t;}
            if(key==40){px=-px;py=-py;}
            covered+=(py>=-9&&py<=0&&std::abs(px)<=py+9)||(py>=0&&py<9&&std::abs(px)<3);
        }
        if(!covered)continue;
        auto* d=pixels.data()+((rect.y*density+y)*stride+rect.x*density+x)*4;
        const unsigned a=covered*255/16;
        for(unsigned c=0;c<3;++c)d[c]=uint8_t((unsigned(d[c])*(255-a)+(c==0?250:c==1?243:224)*a)/255);
        d[3]=255;
    }
}
// These outlines are resampled at both atlas densities, with the same ivory ink
// as the native font. The shape and label contract is shared with Controls.
bool DrawControllerSymbol(std::vector<uint8_t>& pixels,unsigned stride,Badge rect,Symbol symbol,unsigned density) {
    if(symbol==Symbol::None)return false;
    if(symbol>=Symbol::Up&&symbol<=Symbol::Right) {
        const unsigned arrows[]={38,40,37,39};
        DrawArrow(pixels,stride,rect,arrows[unsigned(symbol)-unsigned(Symbol::Up)],density);return true;
    }
    auto line=[](float x,float y,float ax,float ay,float bx,float by) {
        const float vx=bx-ax,vy=by-ay,t=std::clamp(((x-ax)*vx+(y-ay)*vy)/(vx*vx+vy*vy),0.f,1.f);
        const float dx=x-ax-t*vx,dy=y-ay-t*vy;return dx*dx+dy*dy<=1.1f*1.1f;
    };
    for(unsigned y=0;y<kCellHeight*density;++y)for(unsigned x=0;x<rect.width*density;++x) {
        unsigned covered=0;
        for(unsigned sy=0;sy<4;++sy)for(unsigned sx=0;sx<4;++sx) {
            const float px=(x+(sx+.5f)/4)/density-14,py=(y+(sy+.5f)/4)/density-16;
            const float ax=std::abs(px),ay=std::abs(py),r2=px*px+py*py;
            bool ink=false;
            switch(symbol) {
                case Symbol::Cross: ink=ax<=8&&ay<=8&&(std::abs(px-py)<1.5f||std::abs(px+py)<1.5f);break;
                case Symbol::Circle: ink=r2>=6.5f*6.5f&&r2<=8.5f*8.5f;break;
                case Symbol::Square: ink=std::max(ax,ay)>=6.2f&&std::max(ax,ay)<=8.2f;break;
                case Symbol::Triangle: ink=line(px,py,0,-8,-8,7)||line(px,py,-8,7,8,7)||line(px,py,8,7,0,-8);break;
                case Symbol::Plus: ink=(ax<1.5f&&ay<8)||(ay<1.5f&&ax<8);break;
                case Symbol::Minus: ink=ay<1.5f&&ax<8;break;
                default:
                    if(StickSymbol(symbol)) {
                        const float stick=px*px+(py+3)*(py+3);
                        ink=(stick>=6.5f*6.5f&&stick<=8*8)||(ax<1&&py>=5&&py<8)||
                            (ax<6&&py>=8&&py<9.5f);
                        if(PressSymbol(symbol))ink|=(std::abs(px-17)<1.2f&&py>=-5&&py<3)||
                            (py>=3&&py<8&&std::abs(px-17)<8-py);
                    }
                    break;
            }
            covered+=ink;
        }
        if(!covered)continue;
        auto* d=pixels.data()+((rect.y*density+y)*stride+rect.x*density+x)*4;
        const unsigned a=covered*255/16;
        for(unsigned c=0;c<3;++c)d[c]=uint8_t((unsigned(d[c])*(255-a)+(c==0?250:c==1?243:224)*a)/255);
        d[3]=255;
    }
    return !StickSymbol(symbol); // L/R is placed inside the stick cap by the original-font renderer.
}
bool BuildAtlas(Atlas& out) {
    std::vector<uint8_t> native(66644),meta(2806);
    if(!Package(94020796,native)||!Package(94200708,meta)||
       Hash(native)!=0xE0E4E0139749CA2Aull||Hash(meta)!=0xA04471FF903BEAD8ull)return false;
    std::array<uint8_t,256*256*4> letters{};
    for(unsigned y=0;y<256;++y)for(unsigned x=0;x<256;++x) {
        unsigned swizzled=0;for(unsigned bit=0;bit<8;++bit)swizzled|=((x>>bit)&1)<<(bit*2)|((y>>bit)&1)<<(bit*2+1);
        const unsigned index=native[84+1024+swizzled];
        const auto* p=native.data()+84+index*4;
        auto* d=letters.data()+(y*256+x)*4;
        d[0]=p[2];d[1]=p[1];d[2]=p[0];d[3]=p[3];
    }
    struct Letter { int x,y,w,h,top; };
    auto letter=[&](char c) {
        int index=int16_t(U16(meta.data()+162+uint8_t(c)*2));
        if(index<0)index=int16_t(U16(meta.data()+162+'?'*2));
        const auto* p=meta.data()+418+index*21;
        const int x=int(Float(p)*256),y=int(Float(p+4)*256),
            w=int(std::lround((Float(p+8)-Float(p))*256)),h=int(std::lround((Float(p+12)-Float(p+4))*256));
        int left=w,right=-1,top=h,bottom=-1;
        for(int dy=0;dy<h;++dy)for(int dx=0;dx<w;++dx)
            if(letters[((y+dy)*256+x+dx)*4+3]>=16){left=std::min(left,dx);right=std::max(right,dx);top=std::min(top,dy);bottom=std::max(bottom,dy);}
        return right<left?Letter{0,0,0,0,0}:Letter{x+left,y+top,right-left+1,bottom-top+1,top};
    };
    // Metadata includes large transparent margins. Scale the real capital ink,
    // keeping original letter shapes while using56% of the32-pixel keycap height.
    const float scale=18.f/letter('A').h;
    auto advance=[&](const Letter& l){return l.w?int(std::lround(l.w*scale))+2:9;};
    unsigned x=1,y=1;
    for(unsigned key=0;key<out.badges.size();++key) {
        unsigned width=10;
        const auto symbol=ControllerBadgeInfo(key).symbol;
        if(key==kMouseWheelBadge)width=40;
        else if(symbol!=Symbol::None)width=PressSymbol(symbol)?40:28;
        else if(!Arrow(key)&&!MouseButton(key))for(char c:Label(key))width+=unsigned(advance(letter(c)));
        width=std::max(28u,width);
        if(x+width+1>kAtlasWidth){x=1;y+=kCellHeight;}
        out.badges[key]={uint16_t(x),uint16_t(y),uint16_t(width)};x+=width+2;
    }
    out.height=1;while(out.height<y+kCellHeight)out.height*=2;
    if(out.height>1024)return false;
    out.pixels.assign(kAtlasWidth*out.height*4,0);
    auto pixel=[&](unsigned px,unsigned py,uint8_t r,uint8_t g,uint8_t b,uint8_t a) {
        auto* p=out.pixels.data()+(py*kAtlasWidth+px)*4;p[0]=r;p[1]=g;p[2]=b;p[3]=a;
    };
    for(unsigned key=0;key<out.badges.size();++key) {
        auto rect=out.badges[key];
        // Beveled, dark iron keycaps; the lettering is sampled from Darkwatch's original atlas.
        for(unsigned py=3;py<29;++py)for(unsigned px=0;px<rect.width;++px) {
            if((px<2||px>=rect.width-2)&&(py<5||py>=27))continue;
            const bool edge=px<2||px>=rect.width-2||py<5||py>=27;
            pixel(rect.x+px,rect.y+py,edge?148:32,edge?145:28,edge?137:27,240);
        }
        for(unsigned px=3;px<std::min<unsigned>(rect.width-3,17);++px)
            pixel(rect.x+px,rect.y+27,126,29,25,255);
        if(Arrow(key)){DrawArrow(out.pixels,kAtlasWidth,rect,key,1);continue;}
        if(MouseButton(key)){DrawMouseButton(out.pixels,kAtlasWidth,rect,key,1);continue;}
        if(key==kMouseWheelBadge){DrawMouseWheel(out.pixels,kAtlasWidth,rect,1);continue;}
        const auto symbol=ControllerBadgeInfo(key).symbol;
        if(DrawControllerSymbol(out.pixels,kAtlasWidth,rect,symbol,1))continue;
        const float textScale=StickSymbol(symbol)?scale*.5f:scale;
        int top=32,bottom=0;
        for(char c:Label(key)){const auto l=letter(c);if(l.h){top=std::min(top,l.top);bottom=std::max(bottom,l.top+l.h);}}
        const int textY=int(std::lround(((StickSymbol(symbol)?26.f:kCellHeight)-(bottom-top)*textScale)*.5f));
        unsigned pen=rect.x+(StickSymbol(symbol)?unsigned(std::lround(14-letter(Label(key)[0]).w*textScale*.5f)):5);
        for(char c:Label(key)) {
            const auto src=letter(c);if(!src.w){pen+=advance(src);continue;}
            const int w=std::max(1,int(std::lround(src.w*textScale))),h=std::max(1,int(std::lround(src.h*textScale)));
            for(int dy=0;dy<h;++dy)for(int dx=0;dx<w;++dx) {
                auto* s=letters.data()+((src.y+dy*src.h/h)*256+src.x+dx*src.w/w)*4;
                const unsigned a=s[3];if(!a)continue;
                auto* d=out.pixels.data()+((rect.y+textY+int(std::lround((src.top-top)*textScale))+dy)*kAtlasWidth+pen+dx)*4;
                for(int lane=0;lane<3;++lane)d[lane]=uint8_t((unsigned(d[lane])*(255-a)+unsigned(lane==2?224:lane==1?243:250)*a)/255);
                d[3]=255;
            }
            pen+=advance(src);
        }
    }
    // Only the host copy is larger. Guest glyph metrics, UVs, raster dimensions
    // and allocation remain unchanged. Prepare once, publish after RW succeeds.
    if(!g_tried_hd) {
        g_tried_hd=true;
        try {
            auto hd=std::make_shared<PromptHd>();hd->height=out.height;
            hd->original=out.pixels;
            for(size_t i=0;i<hd->original.size();i+=4)std::swap(hd->original[i],hd->original[i+2]);
            std::vector<uint8_t> source(letters.begin(),letters.end()),font;
            for(size_t i=0;i<source.size();i+=4)std::swap(source[i],source[i+2]);
            const auto a=std::find_if(std::begin(darkwatch::hd::kAssets),std::end(darkwatch::hd::kAssets),
                [](const auto& asset){return asset.offset==94020788;});
            if(a!=std::end(darkwatch::hd::kAssets)&&darkwatch::hd_ui::ReconstructFont(*a,source,font)) {
                constexpr unsigned density=2,stride=kAtlasWidth*density;
                hd->pixels.assign(stride*out.height*density*4,0);
                for(unsigned key=0;key<out.badges.size();++key) {
                    const auto r=out.badges[key];
                    // Fresh subpixel chamfers and directional bevel lighting;
                    // this is not a nearest-expanded copy of the 32px frame.
                    for(unsigned y=0;y<32*density;++y)for(unsigned x=0;x<r.width*density;++x) {
                        unsigned sum[4]{};
                        for(unsigned sy=0;sy<4;++sy)for(unsigned sx=0;sx<4;++sx) {
                            const float px=(x+(sx+.5f)/4)/density,py=(y+(sy+.5f)/4)/density;
                            const float side=std::min(px,float(r.width)-px),end=std::min(py-3,29-py);
                            if(side<0||end<0||side+end<2)continue;
                            const bool edge=side<2||end<2,light=py<5||px<2;
                            const unsigned red=edge?(light?166:106):32,green=edge?(light?162:103):28,blue=edge?(light?151:97):27;
                            const bool accent=py>=27&&py<28&&px>=3&&px<std::min<unsigned>(r.width-3,17);
                            const unsigned alpha=accent?255:240;
                            sum[0]+=(accent?126:red)*alpha;sum[1]+=(accent?29:green)*alpha;sum[2]+=(accent?25:blue)*alpha;sum[3]+=alpha;
                        }
                        auto* d=hd->pixels.data()+((r.y*density+y)*stride+r.x*density+x)*4;
                        // Unpremultiplied storage: edge coverage belongs in alpha.
                        if(sum[3])for(unsigned c=0;c<3;++c)d[c]=uint8_t(sum[c]/sum[3]);
                        d[3]=uint8_t(sum[3]/16);
                    }
                    if(Arrow(key)){DrawArrow(hd->pixels,stride,r,key,density);continue;}
                    if(MouseButton(key)){DrawMouseButton(hd->pixels,stride,r,key,density);continue;}
                    if(key==kMouseWheelBadge){DrawMouseWheel(hd->pixels,stride,r,density);continue;}
                    const auto symbol=ControllerBadgeInfo(key).symbol;
                    if(DrawControllerSymbol(hd->pixels,stride,r,symbol,density))continue;
                    const float textScale=StickSymbol(symbol)?scale*.5f:scale;
                    int top=32,bottom=0;
                    for(char c:Label(key)){auto l=letter(c);if(l.h){top=std::min(top,l.top);bottom=std::max(bottom,l.top+l.h);}}
                    const int textY=int(std::lround(((StickSymbol(symbol)?26.f:kCellHeight)-(bottom-top)*textScale)*.5f));
                    unsigned pen=r.x+(StickSymbol(symbol)?unsigned(std::lround(14-letter(Label(key)[0]).w*textScale*.5f)):5);
                    for(char c:Label(key)) {
                        const auto src=letter(c);if(!src.w){pen+=advance(src);continue;}
                        const int w=std::max(1,int(std::lround(src.w*textScale)))*density,h=std::max(1,int(std::lround(src.h*textScale)))*density;
                        for(int dy=0;dy<h;++dy)for(int dx=0;dx<w;++dx) {
                            const unsigned alpha=font[((src.y*4+dy*src.h*4/h)*1024+src.x*4+dx*src.w*4/w)*4+3];
                            if(!alpha)continue;
                            auto* d=hd->pixels.data()+(((r.y+textY+int(std::lround((src.top-top)*textScale)))*density+dy)*stride+pen*density+dx)*4;
                            for(unsigned lane=0;lane<3;++lane)d[lane]=uint8_t((unsigned(d[lane])*(255-alpha)+(lane==0?250:lane==1?243:224)*alpha)/255);
                            d[3]=255;
                        }
                        pen+=advance(src);
                    }
                }
                for(size_t i=0;i<hd->pixels.size();i+=4)std::swap(hd->pixels[i],hd->pixels[i+2]);
                hd->id=Hash(hd->pixels);g_prepared_hd=std::move(hd);
            }
        } catch(const std::exception&) { /* Optional host artwork; original atlas remains usable. */ }
    }
    return true;
}
uint32_t Call(X86Context& ctx,uint32_t function,std::initializer_list<uint32_t> args) {
    X86Context clone=ctx;return kernel::CallGuest(clone,function,args);
}
bool EnsureAtlas(X86Context& ctx,uint8_t* base) {
    if(g_texture)return true;
    if(g_failed)return false;
    g_failed=true;
    auto failure=[](const char* stage){if(diag::Perf())LOGI("PC prompt atlas failed: stage=%s",stage);return false;};
    if(!BuildAtlas(g_atlas))return failure("package");
    if(ctx.esp<4096||!Span(base,uint64_t(ctx.esp)-4096,4096))return failure("stack");
    const uint32_t image=Call(ctx,0x122630,{kAtlasWidth,g_atlas.height,32});
    if(!image)return failure("image-create");
    uint32_t raster=0,texture=0;
    const char* stage="image-pixels";
    if(Call(ctx,0x122690,{image})&&Span(base,image,0x1C)) {
        const uint32_t stride=U32(base+image+0x10),pixels=U32(base+image+0x14);
        stage="image-span";
        if(stride>=kAtlasWidth*4&&stride<=kAtlasWidth*8&&Span(base,pixels,uint64_t(stride)*g_atlas.height)) {
            for(unsigned y=0;y<g_atlas.height;++y)std::memcpy(base+pixels+y*stride,g_atlas.pixels.data()+y*kAtlasWidth*4,kAtlasWidth*4);
            X86Context scratch=ctx;scratch.esp-=64;
            const uint32_t p=scratch.esp;std::memset(base+p,0,16);
            stage="raster-format";
            if(Call(scratch,0x1220A0,{image,4,p,p+4,p+8,p+12})) {
                stage="raster-create";
                raster=Call(scratch,0x1222C0,{U32(base+p),U32(base+p+4),U32(base+p+8),U32(base+p+12)});
                if(raster){stage="raster-upload";if(Call(scratch,0x122070,{raster,image})){stage="texture-create";texture=Call(scratch,0x11C110,{raster});}}
            }
        }
    }
    Call(ctx,0x123250,{image});
    if(!texture&&raster)Call(ctx,0x122160,{raster});
    if(!texture)return failure(stage);
    // One session-owned immutable texture. Fonts only own their original four texture references;
    // appended glyph records borrow this one. Keep it alive through all queued draws until process exit.
    g_texture=texture;
    std::atomic_store_explicit(&g_prompt_hd,g_prepared_hd,std::memory_order_release);
    g_prompt_revision.store(g_prepared_hd?1:0);
    LOGI("PC prompt atlas: %ux%u, original Darkwatch lettering",kAtlasWidth,g_atlas.height);
    return true;
}
bool TextureName(const uint8_t* base,uint32_t texture) {
    char name[33]{};if(!Span(base,uint64_t(texture)+0x10,32))return false;
    std::memcpy(name,base+texture+0x10,32);
    for(char& c:name)if(c>='A'&&c<='Z')c=char(c-'A'+'a');
    // The active font family is requested as Standard/Small by the original
    // frontend; packaged Xbox-prefixed fonts are a separate resource family.
    return !std::strcmp(name,"standard")||!std::strcmp(name,"standardglow")||
        !std::strcmp(name,"small")||!std::strcmp(name,"smallglow")||
        !std::strcmp(name,"xboxstandard")||!std::strcmp(name,"xboxstandardglow")||
        !std::strcmp(name,"xboxsmall")||!std::strcmp(name,"xboxsmallglow");
}
void Refresh(uint8_t* base) {
    const int port=darkwatch::prompt_owner::Port(base);
    const auto prompt=port<0?input::GetControllerPromptSnapshot():input::GetControllerPromptSnapshot(port);
    const auto device=prompt.device;const auto settings=darkwatch::ControlsSnapshot();
    if(!g_have_settings||device.controller!=g_device.controller||(device.controller&&device.family!=g_device.family)||
       prompt.bindings!=g_controller_bindings||
       std::memcmp(settings.bindings.data(),g_settings.bindings.data(),sizeof(settings.bindings))) {
        g_device=device;g_controller_bindings=prompt.bindings;g_settings=settings;g_have_settings=true;++g_revision;
    }
    DarkwatchRefreshMenuBars(base,g_revision);
}
unsigned Key(unsigned action) {
    const auto& binding=g_settings.bindings[action];
    const unsigned key=binding.keys[0]?binding.keys[0]:binding.keys[1];
    return key==input::kMouseWheel?kMouseWheelBadge:key<256?key:0;
}
bool CString(const uint8_t* base,uint32_t p,std::string& text,unsigned limit=80) {
    text.clear();for(unsigned i=0;i<limit;++i){char c;if(!Read(base,uint64_t(p)+i,c))return false;if(!c)return true;text+=c;}return false;
}
bool Reference(const uint8_t* base,uint32_t ref,std::string& text,unsigned limit=80) {
    uint32_t p=0;return Read(base,ref,p)&&p&&p<=UINT32_MAX-2&&CString(base,p+2,text,limit);
}
std::string Lower(std::string s) {for(char& c:s)if(c>='A'&&c<='Z')c=char(c-'A'+'a');return s;}
bool SetReference(X86Context& ctx,uint8_t* base,uint32_t output,const std::string& value) {
    if(value.size()>16384)return false;
    const uint32_t reserve=uint32_t((value.size()+64+15)&~size_t(15));
    uint32_t previous=0;
    if(!Read(base,output,previous)||(previous&&!Span(base,previous,3))||ctx.esp<reserve+1024||
       !Span(base,uint64_t(ctx.esp)-reserve-1024,reserve+1024))return false;
    X86Context call=ctx;call.esp-=reserve;const uint32_t temporary=call.esp,chars=temporary+16;
    std::memset(base+temporary,0,4);
    std::memcpy(base+chars,value.c_str(),value.size()+1);
    // Construct first: allocation failure must retain the original subtitle.
    call.ecx=temporary;kernel::CallGuest(call,0x138FA,{chars});
    uint32_t replacement=0;
    if(!Read(base,temporary,replacement)||!replacement)return false;
    call.ecx=output;kernel::CallGuest(call,0x11C1A,{});
    // Transfer the newly constructed reference; no extra retain/release pair.
    std::memcpy(base+output,&replacement,4);
    std::memset(base+temporary,0,4);return true;
}
} // namespace

uint64_t darkwatch::PromptTextureRevision() { return g_prompt_revision.load(); }
bool darkwatch::ReplacePromptTexture(const gpu::TextureDesc& d,const gpu::FormatInfo& fi,
                                    const uint8_t* source,uint32_t bytes,gpu::TextureReplacement& out) {
    const auto hd=std::atomic_load_explicit(&g_prompt_hd,std::memory_order_acquire);
    if(!hd||!source||d.width!=kAtlasWidth||d.height!=hd->height||d.depth!=1||d.levels!=1||d.cube||d.linear||
       fi.depth||fi.compressed||!fi.swizzled||fi.bits!=32||fi.host!=gpu::Host::BGRA8||
       (d.format!=6&&d.format!=0x3A&&d.format!=0x3B&&d.format!=0x3C)||bytes!=hd->original.size())return false;
    // Invoked by the renderer only on resource/revision changes. Decode with
    // its real format path, then require every original texel, not just a hash.
    std::vector<uint8_t> decoded;uint32_t pitch=0;
    gpu::DecodeLevel(d,0,0,source,nullptr,decoded,pitch);
    if(pitch!=kAtlasWidth*4||decoded!=hd->original)return false;
    out.id=hd->id;out.width=kAtlasWidth*2;out.height=hd->height*2;out.bgra=hd->pixels;
#ifndef XBE_RELEASE
    if(!g_prompt_logged.exchange(true))LOGR("HD UI: selected PC keycaps format=%02X %ux%u -> %ux%u",d.format,d.width,d.height,out.width,out.height);
#endif
    return true;
}

void DarkwatchPromptFont(X86Context& ctx,uint8_t* base) {
    if(g_in_call||base!=kernel::g_base)return;
    std::lock_guard lock(g_lock);
    uint32_t font=0,list=0,data=0,count=0,callback=0,texture=0,itemsize=0,listcount=0;
    if(!Read(base,uint64_t(ctx.esp)+4,font)||!Span(base,font,0x13C)){TraceFont(base,font,1);return;}
    if(!Read(base,uint64_t(font)+0x138,callback)||callback!=0x126B50){TraceFont(base,font,2);return;}
    if(
       !Read(base,uint64_t(font)+0x134,list)||!Span(base,list,16)||
       !Read(base,list,data)||!Read(base,uint64_t(list)+4,listcount)||!Read(base,uint64_t(list)+12,itemsize)||itemsize!=32||
       !Read(base,uint64_t(font)+0x130,count)||count!=listcount||count<16||count>512||!Span(base,data,uint64_t(count)*32)||
       !Read(base,uint64_t(font)+0x14,texture)||!texture){TraceFont(base,font,3);return;}
    if(!TextureName(base,texture)){TraceFont(base,font,4);return;}
    TraceFont(base,font,0);
    Refresh(base);
    auto it=std::find_if(g_fonts.begin(),g_fonts.end(),[&](const Font& f){return f.address==font;});
    if(it!=g_fonts.end()&&(it->list!=list||it->data!=data||it->texture!=texture||it->first+kCodes.size()!=count)) {
        *it={};it=g_fonts.end(); // Never restore a backup into a reused or independently changed font.
    }
    if(it==g_fonts.end()) {
        it=std::find_if(g_fonts.begin(),g_fonts.end(),[](const Font& f){return !f.address;});if(it==g_fonts.end())return;
        struct InCall {InCall(){g_in_call=true;}~InCall(){g_in_call=false;}} guard;
        if(!EnsureAtlas(ctx,base))return;
        Font added;added.address=font;added.list=list;added.first=count;added.texture=texture;
        for(unsigned i=0;i<kCodes.size();++i)std::memcpy(&added.original[i],base+font+0x24+kCodes[i]*2,2);
        const uint32_t records=Call(ctx,0x138190,{list,uint32_t(kCodes.size()),0x30190});
        if(!records||!Span(base,records,kCodes.size()*32))return;
        added.data=U32(base+list);
        if(records!=uint64_t(added.data)+count*32||U32(base+list+4)!=count+kCodes.size())return;
        std::memset(base+records,0,kCodes.size()*32);
        count+=uint32_t(kCodes.size());std::memcpy(base+font+0x130,&count,4);*it=added;
    }
    if(it->revision==g_revision)return;
    for(unsigned i=0;i<kCodes.size();++i) {
        int16_t map=g_device.controller?it->original[i]:int16_t(it->first+i);
        unsigned badgeKey=i<kActions.size()?Key(kActions[i]):256;
        bool custom=!g_device.controller;
        if(g_device.controller) {
            const bool alternate=g_device.family==input::ControllerFamily::PlayStation||g_device.family==input::ControllerFamily::Switch;
            // Stable reserved tokens remain readable even when the localized result was cached
            // on PC. Existing authored controller icons are restored exactly.
            if(i<16) {
                const unsigned physical=g_controller_bindings[kActions[i]];
                if(alternate){custom=true;badgeKey=ControllerBadge(g_device.family,physical);}
                else {
                    const auto original=std::find(kActions.begin(),kActions.begin()+16,physical);
                    map=it->original[size_t(original-kActions.begin())];
                    if(map<0&&(physical==4||physical==5)){custom=true;badgeKey=physical==5?258:257;}
                }
            }
            else if(i==16||i==21){custom=true;badgeKey=alternate?ControllerBadge(g_device.family,16):259;}
            else if(i==20||i==25){custom=true;badgeKey=alternate?ControllerBadge(g_device.family,17):260;}
            else if((i>=17&&i<=19)||(i>=22&&i<=24))map=-1;
            if(custom)map=int16_t(it->first+i);
        } else if(i>=21&&i<=24) {
            // Lefty uses the left stick to look. Keep the expanded token stable,
            // and resolve its four records against the current input mode.
            if(i>21){custom=false;map=-1;}
        } else if(i==25) {
            // Mouse movement always controls looking, including the Lefty preset.
            badgeKey=260;
        }
        if(custom) {
            const auto& badge=g_atlas.badges[badgeKey];
            Glyph glyph{float(badge.width)/kCellHeight,g_texture,
                {(badge.x+.5f)/kAtlasWidth,(badge.y+.5f)/g_atlas.height,
                 (badge.x+badge.width-.5f)/kAtlasWidth,(badge.y+kCellHeight-.5f)/g_atlas.height},0,0};
            std::memcpy(base+it->data+(it->first+i)*32,&glyph,32);
        }
        std::memcpy(base+font+0x24+kCodes[i]*2,&map,2);
    }
    it->revision=g_revision;
}
void DarkwatchPromptFontDestroy(X86Context& ctx,uint8_t* base) {
    std::lock_guard lock(g_lock);uint32_t font=0;if(!Read(base,uint64_t(ctx.esp)+4,font))return;
    for(auto& f:g_fonts)if(f.address==font)f={};
    // The original destructor frees its expanded list; borrowed atlas ownership stays with this module.
}
void DarkwatchPromptLocalization(X86Context& ctx,uint8_t* base) {
    if(g_in_call||base!=kernel::g_base)return;
    uint32_t key=0,identity=0,output=0;
    if(!Read(base,uint64_t(ctx.ebp)+12,key)||!Read(base,key,identity)||!Read(base,uint64_t(ctx.ebp)+8,output))return;
    // The original table resolver takes a hashed text ID, not a string reference.
    static const auto restart=darkwatch::language::NativeKey("GEN_REVERTSTORYMODE");
    static const auto start=darkwatch::language::NativeKey("GEN_PRESSSTART");
    static const auto resume=darkwatch::language::NativeKey("GEN_PRESSSTARTCONTINUE");
    if(identity==restart) {
        SetReference(ctx,base,output,darkwatch::language::Guest("Replay this chapter? Your saved campaign progress will be kept."));
    } else if(identity==start||identity==resume) {
        const bool controller=input::GetLastDevice().controller;
        SetReference(ctx,base,output,darkwatch::language::Guest(identity==start?
            (controller?"Press ^pcStart":"Press any key to start"):
            (controller?"Press ^pcStart to Continue":"Press any key to continue")));
    } else if(darkwatch::language::Spanish()) {
        std::string original;
        if(!Reference(base,output,original,16385))return;
        auto translated=darkwatch::language::Translate(identity,original);
        // Native ~literal registration strips ~ and hashes the displayed label.
        // Only known project copy whose returned text matches that identity can
        // use this fallback; ordinary game text keeps its exact context match.
        if(translated.empty()&&original.size()<=128&&identity==darkwatch::language::NativeKey(original))
            translated=darkwatch::language::Guest(original.c_str());
        if(!translated.empty()&&translated!=original)SetReference(ctx,base,output,translated);
    }
}
void DarkwatchPromptStartToken(X86Context& ctx,uint8_t* base) {
    if(uint8_t(ctx.eax))return;
    std::string token;
    if(ctx.ebp>=8&&Reference(base,ctx.ebp-8,token)&&Lower(token)=="pcstart")ctx.eax=(ctx.eax&0xFFFFFF00)|'l';
}
bool DarkwatchPromptMovementToken(X86Context& ctx,uint8_t* base) {
    if(g_in_call||base!=kernel::g_base||ctx.ebp<24)return false;
    std::string token;if(!Reference(base,ctx.ebp-8,token))return false;token=Lower(token);
    if(token!="move"&&token!="look")return false;
    uint32_t preset=0;if(!Read(base,0x4B4B5C,preset)||preset>4)return false;
    std::string text;
    // Device, bindings and direct-mouse changes must also update cached strings.
    // Reserve semantic glyphs here; their font records carry the current labels.
    if(token=="look")text=preset==2?std::string("\6 \7 \10 \11",7):std::string(1,char(5));
    else text=preset==2?std::string(1,char(11)):std::string("\1 \2 \3 \4",7);
    if(!Span(base,ctx.ebp-24,12)||ctx.esp<1024||!Span(base,uint64_t(ctx.esp)-1024,1024))return false;
    X86Context call=ctx;call.esp-=64;std::memcpy(base+call.esp,text.c_str(),text.size()+1);
    call.ecx=ctx.ebp-24;kernel::CallGuest(call,0xE6D13,{call.esp});return true;
}
