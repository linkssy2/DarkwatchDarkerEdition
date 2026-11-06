"""Execute actual viewport, frame-fit and queued-state code without a GPU.

The command list records viewport/scissor submission. This verifies backend
geometry and state transfer, not rendered pixels or live gameplay.
"""
import unittest

from test_xbexbe_graphics_cinematic import SDK, compile_and_run
from test_xbexbe_io_apc import function


class UltrawidePresentationTests(unittest.TestCase):
    def test_actual_backend_viewports_frame_fit_and_queued_safe_area(self):
        backend = (SDK / "gpu/d3d12.cpp").read_text()
        queue = (SDK / "gpu/render_thread.cpp").read_text()
        options_start = backend.index("struct BlitOptions {")
        options = backend[options_start:backend.index("\n};", options_start) + 4]
        ranges = queue[queue.index("struct Range {"):queue.index("// equal bytes")]
        methods = "\n".join(function(backend, name) for name in (
            "void D3D12Backend::SetViewportScissor(",
            "bool D3D12Backend::BlitFrame(",
            "void D3D12Backend::TrackPresentationAspect(",
            "void D3D12Backend::ClearPresentationBars(",
        ))
        compile_and_run(self, PREFIX + options + BACKEND + ranges + methods + DRIVER,
                        "ultrawide presentation passed")


PREFIX = r'''
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "app/app.h"
#include "gpu/state.h"
#define CHECK(x) do { if(!(x)){std::fprintf(stderr,"case %u line %d: %s\n",cases,__LINE__,#x);std::exit(90);} } while(0)
static unsigned cases;
using gpu::State;
using LONG = int32_t;
using DXGI_FORMAT = uint32_t;
constexpr DXGI_FORMAT kBgra = 87;
constexpr uint32_t D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE = 128;
struct D3D12_VIEWPORT {float TopLeftX,TopLeftY,Width,Height,MinDepth,MaxDepth;};
struct D3D12_RECT {LONG left,top,right,bottom;};
using D3D12_CPU_DESCRIPTOR_HANDLE = unsigned;
struct Commands {
    std::vector<D3D12_VIEWPORT> viewports;
    std::vector<D3D12_RECT> scissors;
    std::vector<D3D12_RECT> clears;
    void ClearRenderTargetView(unsigned output,const float* color,unsigned n,const D3D12_RECT* r){
        CHECK(output==7&&n==1&&color[0]==0&&color[1]==0&&color[2]==0&&color[3]==1);clears.push_back(*r);
    }
    void RSSetViewports(unsigned n,const D3D12_VIEWPORT* v){CHECK(n==1);viewports.push_back(*v);}
    void RSSetScissorRects(unsigned n,const D3D12_RECT* r){CHECK(n==1);scissors.push_back(*r);}
};
static float render_aspect;
static unsigned aspect_reads;
static app::Settings settings;
float app::RenderAspect(){++aspect_reads;return render_aspect;}
app::Settings app::Snapshot(){return settings;}
'''

BACKEND = r'''
struct Target {uint32_t w=0,h=0,gh=480,state=0,data=0;void* res=nullptr;DXGI_FORMAT fmt=kBgra;};
struct TargetRead {void* res;uint32_t* state;DXGI_FORMAT fmt;};
struct D3D12Backend {
    Target* bound_rt_=nullptr;Target* bound_ds_=nullptr;
    uint32_t bb_w_=0,bb_h_=0;
    bool gamma_=false,pipeline_ready=true;
    bool presentation_original_drawn_=false;uint32_t presentation_original_data_=0;
    Commands commands;Commands* cl_=&commands;
    unsigned pipelines=0,transitions=0,blits=0;
    std::array<float,4> uv{};BlitOptions options{};
    void SetViewportScissor(const State&,uint32_t);
    bool BlitFrame(Target&);
    void TrackPresentationAspect(const State&);
    void ClearPresentationBars(const Target*,D3D12_CPU_DESCRIPTOR_HANDLE);
    TargetRead ReadTarget(Target& t){return {t.res,&t.state,t.fmt};}
    bool EnsureBlitPipeline(DXGI_FORMAT format,bool alpha,uint32_t samples){
        CHECK(format==kBgra&&!alpha&&samples==1);++pipelines;return pipeline_ready;
    }
    void Transition(void* resource,uint32_t& state,uint32_t next){
        CHECK(resource);CHECK(next==D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        state=next;++transitions;
    }
    void Blit(void* resource,DXGI_FORMAT format,const float* source,const BlitOptions& opt){
        CHECK(resource&&format==kBgra);std::copy(source,source+4,uv.begin());options=opt;++blits;
    }
};
'''

DRIVER = r'''
static void Near(float a,float b){CHECK(std::abs(a-b)<.001f);}
static void Viewport(const D3D12_VIEWPORT& v,float x,float y,float w,float h){
    Near(v.TopLeftX,x);Near(v.TopLeftY,y);Near(v.Width,w);Near(v.Height,h);
    CHECK(v.MinDepth==0&&v.MaxDepth==1);
}
static void Rect(const D3D12_RECT& r,LONG x,LONG y,LONG right,LONG bottom){
    CHECK(r.left==x&&r.top==y&&r.right==right&&r.bottom==bottom);
}
struct Display {uint32_t w,h;float safe_left,safe_top,safe_width,safe_height;};
static constexpr Display displays[]={
    {1920,1440,0,0,1920,1440}, {1920,1080,0,0,1920,1080},
    {1280,800,0,40,1280,720}, {2560,1600,0,80,2560,1440},
    {2520,1080,300,0,1920,1080}, {2560,1080,320,0,1920,1080},
    {3440,1440,440,0,2560,1440}, {5120,1440,1280,0,2560,1440},
};
static void CheckViewports(){
    for(const auto& d:displays)for(bool overlay:{false,true})for(bool safe:{false,true})
    for(bool depth_only:{false,true})for(unsigned half:{0u,1u,2u})for(bool clipped:{false,true}){
        render_aspect=float(d.w)/d.h;
        D3D12Backend b;Target target;target.w=d.w;target.h=d.h;
        if(depth_only)b.bound_ds_=&target;else b.bound_rt_=&target;
        State s;s.presentation_overlay=overlay;s.presentation_safe_area=safe;
        unsigned y=half==2?240:0,height=half?240:480;
        s.viewport={0,y,640,height,0,1};
        if(clipped){s.scissor_count=1;s.scissors={80,y+20,560,y+height-20};}
        b.SetViewportScissor(s,640);
        CHECK(b.commands.viewports.size()==1&&b.commands.scissors.size()==1);
        const float left=safe?d.safe_left:0;
        const float top=safe?d.safe_top:0;
        const float width=safe?d.safe_width:float(d.w);
        const float target_height=safe?d.safe_height:float(d.h);
        Viewport(b.commands.viewports.back(),left,top,width,target_height);
        // Independently specified UI rectangles preserve authored proportions.
        // World and both split-screen HUD viewports keep the entire output.
        Rect(b.commands.scissors.back(),LONG(left+(clipped?width/8:0)),
             LONG(top+(y+(clipped?20:0))*target_height/480),
             LONG(left+width-(clipped?width/8:0)),
             LONG(top+(y+height-(clipped?20:0))*target_height/480));
        ++cases;
    }
    // Nonzero guest viewport and scissors intersect before target clipping.
    render_aspect=32.f/9.f;
    D3D12Backend b;Target target;target.w=5120;target.h=1440;b.bound_rt_=&target;
    State s;s.presentation_overlay=s.presentation_safe_area=true;
    s.viewport={80,240,480,240,0,1};s.scissor_count=1;s.scissors={100,260,500,460};
    b.SetViewportScissor(s,640);Rect(b.commands.scissors.back(),1680,780,3280,1380);++cases;
    // Loading UI stays native for multiplicative blending but uses the same
    // safe area. Its separate fullscreen dimmer explicitly clears the flag.
    s.presentation_overlay=false;b.SetViewportScissor(s,640);
    Rect(b.commands.scissors.back(),1680,780,3280,1380);++cases;
    s.presentation_safe_area=false;b.SetViewportScissor(s,640);
    Rect(b.commands.scissors.back(),800,780,4000,1380);++cases;
    s.presentation_overlay=s.presentation_safe_area=true;
    s.viewport={0,0,1280,960,0,1};s.scissors={0,0,1280,960};
    b.SetViewportScissor(s,640);Rect(b.commands.scissors.back(),1280,0,5120,1440);++cases;
    // 4:3 at 101% produces 646x484 after integer sizing. Those rounded target
    // dimensions must not accidentally activate the widescreen menu layout.
    render_aspect=4.f/3.f;target.w=646;target.h=484;
    s.viewport={0,0,640,480,0,1};s.scissor_count=0;
    b.SetViewportScissor(s,640);Viewport(b.commands.viewports.back(),0,0,646,484);
    Rect(b.commands.scissors.back(),0,0,646,484);++cases;
}
static void CheckFrameFit(){
    for(const auto& d:displays)for(unsigned mode:{0u,1u,2u})for(bool gamma:{false,true}){
        D3D12Backend b;b.bb_w_=d.w;b.bb_h_=d.h;b.gamma_=gamma;
        Target target;target.res=&target;
        render_aspect=mode==0?float(d.w)/d.h:mode==1?16.f/9.f:4.f/3.f;
        settings.brightness_percent=gamma?85:110;aspect_reads=0;
        CHECK(b.BlitFrame(target));CHECK(aspect_reads==1);
        CHECK(b.commands.viewports.size()==1&&b.commands.scissors.size()==1);
        if(mode==0)Viewport(b.commands.viewports.back(),0,0,float(d.w),float(d.h));
        else if(mode==1&&d.w==1920&&d.h==1440)
            Viewport(b.commands.viewports.back(),0,180,1920,1080);
        else if(mode==1)Viewport(b.commands.viewports.back(),d.safe_left,d.safe_top,d.safe_width,d.safe_height);
        else {
            const float classic_width=float(d.h)*4/3;
            Viewport(b.commands.viewports.back(),(d.w-classic_width)/2,0,classic_width,float(d.h));
        }
        Rect(b.commands.scissors.back(),0,0,d.w,d.h);
        CHECK(b.pipelines==1&&b.transitions==1&&b.blits==1);
        CHECK(target.state==D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        CHECK((b.uv==std::array<float,4>{0,0,1,1}));CHECK(b.options.gamma==gamma);
        Near(b.options.mul,gamma?.85f:1.1f);++cases;
    }
    // Failed resource/pipeline setup must not submit presentation commands.
    for(bool resource_present:{false,true}){
        D3D12Backend b;b.pipeline_ready=false;Target t;if(resource_present)t.res=&t;
        aspect_reads=0;CHECK(!b.BlitFrame(t));CHECK(aspect_reads==0);
        CHECK(b.commands.viewports.empty()&&b.commands.scissors.empty());
        CHECK(!b.transitions&&!b.blits);CHECK(b.pipelines==unsigned(resource_present));++cases;
    }
}
static void CheckQueuedState(){
    State fresh;CHECK(!fresh.presentation_overlay&&!fresh.presentation_safe_area&&!fresh.presentation_original_aspect);
    auto ranges=StateRanges();CHECK(!ranges.empty());
    const auto flag=At(fresh,&fresh.presentation_safe_area);
    unsigned covering=0;
    for(const auto& r:ranges){
        CHECK(r.len&&r.off+r.len<=sizeof(State));
        if(flag>=r.off&&flag<r.off+r.len)++covering;
        // The production queue excludes shader ownership objects from memcpy.
        for(const auto pointer_offset:{At(fresh,&fresh.vs),At(fresh,&fresh.ps)})
            CHECK(r.off+r.len<=pointer_offset||r.off>=pointer_offset+sizeof(fresh.vs));
    }
    CHECK(covering==1);CHECK(flag>=ranges.back().off&&flag<ranges.back().off+ranges.back().len);
    State sent,received;
    for(bool overlay:{false,true})for(bool enabled:{true,false,true,false})for(bool original:{false,true}){
        sent.presentation_overlay=overlay;sent.presentation_safe_area=enabled;
        sent.presentation_original_aspect=original;
        sent.viewport={0,240,640,240,0,1};sent.scissor_count=1;sent.scissors={80,260,560,460};
        for(const auto& r:ranges)
            std::memcpy(reinterpret_cast<uint8_t*>(&received)+r.off,
                        reinterpret_cast<const uint8_t*>(&sent)+r.off,r.len);
        CHECK(received.presentation_overlay==overlay&&received.presentation_safe_area==enabled);
        CHECK(received.presentation_original_aspect==original);
        CHECK(received.viewport.y==240&&received.viewport.h==240);
        CHECK(received.scissor_count==1&&received.scissors==sent.scissors);
        // Execute the state delivered by those real queue ranges, including
        // the following ordinary draw clearing the preceding overlay's flag.
        render_aspect=3440.f/1440.f;
        D3D12Backend b;Target target;target.w=3440;target.h=1440;b.bound_rt_=&target;
        b.SetViewportScissor(received,640);
        const float width=enabled?(original?1920:2560):3440;
        const float left=(3440-width)/2;
        Viewport(b.commands.viewports.back(),left,0,width,1440);
        Rect(b.commands.scissors.back(),LONG(left+width/8),780,LONG(left+width*7/8),1380);++cases;
    }
}
static void CheckOriginalCanvas(){
    for(const auto& d:displays)for(bool safe:{false,true}){
        render_aspect=float(d.w)/d.h;D3D12Backend b;Target t;t.w=d.w;t.h=d.h;b.bound_rt_=&t;
        State s;s.presentation_safe_area=safe;s.presentation_original_aspect=true;s.viewport={0,0,640,480,0,1};
        b.SetViewportScissor(s,640);
        const float w=safe?float(d.h)*4/3:float(d.w);
        Viewport(b.commands.viewports.back(),(d.w-w)/2,0,w,float(d.h));++cases;
    }
    for(const auto& d:displays)for(float aspect:{float(d.w)/d.h,4.f/3,16.f/9}){
        render_aspect=aspect;D3D12Backend b;b.bb_w_=d.w;b.bb_h_=d.h;Target t;t.data=123;b.bound_rt_=&t;
        State s;s.presentation_overlay=s.presentation_safe_area=s.presentation_original_aspect=true;
        b.TrackPresentationAspect(s);CHECK(b.presentation_original_drawn_&&b.presentation_original_data_==123);
        // Subtitle/UI overlays neither create a request nor cancel a valid frontend request.
        s.presentation_original_aspect=false;b.TrackPresentationAspect(s);CHECK(b.presentation_original_drawn_);
        b.ClearPresentationBars(&t,7);CHECK(!b.presentation_original_drawn_);
        const float outw=std::min(float(d.w),float(d.h)*aspect),outh=outw/aspect;
        const float w=std::min(outw,outh*(4.f/3)),h=w/(4.f/3);
        const LONG left=std::max(0,LONG(std::floor((d.w-w)/2))),top=std::max(0,LONG(std::floor((d.h-h)/2)));
        const LONG right=std::min(LONG(d.w),LONG(std::ceil((d.w+w)/2))),bottom=std::min(LONG(d.h),LONG(std::ceil((d.h+h)/2)));
        uint64_t area=0;
        for(auto r:b.commands.clears){
            CHECK(r.left>=0&&r.top>=0&&r.right<=LONG(d.w)&&r.bottom<=LONG(d.h));
            CHECK(r.left<r.right&&r.top<r.bottom);
            CHECK(r.right<=left||r.left>=right||r.bottom<=top||r.top>=bottom);
            area+=uint64_t(r.right-r.left)*(r.bottom-r.top);
        }
        CHECK(area==uint64_t(d.w)*d.h-uint64_t(right-left)*(bottom-top));
        const auto n=b.commands.clears.size();b.ClearPresentationBars(&t,7);CHECK(b.commands.clears.size()==n);++cases;
    }
    for(unsigned mode=0;mode<7;++mode){
        D3D12Backend b;b.bb_w_=1920;b.bb_h_=1080;Target t,other;t.data=123;other.data=456;b.bound_rt_=&t;
        State s;s.presentation_overlay=s.presentation_safe_area=s.presentation_original_aspect=true;
        if(mode!=5)b.TrackPresentationAspect(s);
        switch(mode){
        case 0:s.presentation_overlay=s.presentation_safe_area=s.presentation_original_aspect=false;b.TrackPresentationAspect(s);break;
        case 1:s.presentation_overlay=false;s.presentation_safe_area=true;s.presentation_original_aspect=false;b.TrackPresentationAspect(s);break;
        case 2:b.bound_rt_=&other;s.presentation_overlay=false;s.presentation_safe_area=s.presentation_original_aspect=false;b.TrackPresentationAspect(s);break;
        case 5:s.presentation_original_aspect=false;b.TrackPresentationAspect(s);break;
        case 6:b.presentation_original_drawn_=false;b.bound_rt_=nullptr;b.TrackPresentationAspect(s);break;
        }
        b.ClearPresentationBars(mode==3?nullptr:mode==4?&other:&t,7);
        CHECK(b.commands.clears.empty()&&!b.presentation_original_drawn_);++cases;
    }
}
int main(){
    CheckViewports();CheckFrameFit();CheckQueuedState();CheckOriginalCanvas();
    std::printf("ultrawide presentation passed: %u backend/queue cases, 4:3 through 32:9\n",cases);
}
'''


if __name__ == "__main__":
    unittest.main()
