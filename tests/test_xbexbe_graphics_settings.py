"""Exercise the actual settings parser, snapshots, sizing and atomic persistence."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_xbexbe_io_apc import function

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"


class GraphicsSettingsTests(unittest.TestCase):
    def test_desktop_aspect_cache_invalidates_after_window_or_display_change(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        source = (SDK / "app/settings.cpp").read_text()
        fixture = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include "app/app.h"
using HWND=void*;using HMONITOR=void*;
struct MONITORINFOEXW {unsigned cbSize;wchar_t szDevice[32];};
struct DEVMODEW {unsigned dmSize,dmPelsWidth,dmPelsHeight;};
enum {MONITOR_DEFAULTTOPRIMARY,ENUM_REGISTRY_SETTINGS,SM_CXSCREEN,SM_CYSCREEN};
static app::Mode display{3440,1440};static unsigned queries;static bool available=true;
HMONITOR MonitorFromWindow(HWND,int){return nullptr;}
bool GetMonitorInfoW(HMONITOR,MONITORINFOEXW*){return true;}
bool EnumDisplaySettingsW(const wchar_t*,int,DEVMODEW* d){++queries;d->dmPelsWidth=display.width;d->dmPelsHeight=display.height;return available;}
int GetSystemMetrics(int dimension){return dimension==SM_CXSCREEN?1920:1080;}
namespace app {std::mutex g_output_lock;Mode g_desktop{};void* Window(){return nullptr;}
'''
        fixture += "\n".join(function(source, name) for name in (
            "Mode Desktop(", "void InvalidateOutput(", "Settings Normalize(",
            "Mode OutputOf(", "Mode AspectOf(", "float RenderAspect(const Settings&"))
        fixture += r'''
}
int main(){
 app::Settings s;
 for(auto mode:{app::DisplayMode::Fullscreen,app::DisplayMode::Borderless,app::DisplayMode::Windowed}){
  s.display_mode=mode;
  for(auto aspect:{app::AspectRatio::Standard4x3,app::AspectRatio::Wide16x9,app::AspectRatio::Ultra21x9,app::AspectRatio::Super32x9,app::AspectRatio::Wide16x10}){
   s.aspect_ratio=aspect;app::InvalidateOutput();
   const float expected=aspect==app::AspectRatio::Standard4x3?4.f/3.f:aspect==app::AspectRatio::Wide16x9?16.f/9.f:aspect==app::AspectRatio::Ultra21x9?21.f/9.f:aspect==app::AspectRatio::Wide16x10?16.f/10.f:32.f/9.f;
   for(unsigned i=0;i<1000;++i)assert(app::RenderAspect(s)==expected);
   assert(queries==0);
  }
 }
 s.aspect_ratio=app::AspectRatio::Auto;s.display_mode=app::DisplayMode::Borderless;
 assert(std::abs(app::RenderAspect(s)-3440.f/1440.f)<.000001f&&queries==1);
 for(unsigned i=0;i<10000;++i){auto d=app::Desktop();assert(d.width==3440&&d.height==1440);}assert(queries==1);
 display={5120,1440};assert(app::Desktop().width==3440);app::InvalidateOutput();assert(app::Desktop().width==5120&&queries==2);
 display={2560,1600};app::InvalidateOutput();assert(app::RenderAspect(s)==1.6f&&queries==3);
 available=false;app::InvalidateOutput();auto d=app::Desktop();assert(d.width==1920&&d.height==1080&&queries==4);
 for(unsigned i=0;i<10000;++i)assert(app::Desktop().width==1920);assert(queries==4);
}
'''
        with tempfile.TemporaryDirectory(prefix="xbexbe-settings-cache-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            path, exe = folder / "test.cpp", folder / "test.exe"
            path.write_text(fixture)
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-I", str(SDK), str(path), "-o", str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_oversized_desktop_proportionally_bounds_actual_render_helper(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        source = (SDK / "app/settings.cpp").read_text()
        fixture = '#include <algorithm>\n#include <cassert>\n#include "app/app.h"\nnamespace app {\n'
        fixture += 'static Mode desktop; Mode Desktop(){return desktop;}\n'
        fixture += "\n".join(function(source, name) for name in (
            "Settings Normalize(", "Mode OutputOf(", "Mode AspectOf(", "Mode RenderSize(const Settings&"))
        fixture += r'''
}
int main(){
    app::Settings s;s.render_percent=200;s.aspect_ratio=app::AspectRatio::Wide16x9;
    app::desktop={20000,12000};auto m=app::RenderSize(s);assert(m.width==16384&&m.height==9216);
    s.aspect_ratio=app::AspectRatio::Standard4x3;m=app::RenderSize(s);assert(m.width==16384&&m.height==12288);
    app::desktop={0xFFFFFFFFu,0xFFFFFFFFu};m=app::RenderSize(s);assert(m.width==16384&&m.height==12287);
    app::desktop={0,0};m=app::RenderSize(s);assert(m.width==1&&m.height==1);
}
'''
        with tempfile.TemporaryDirectory(prefix="xbexbe-settings-bounds-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            path, exe = folder / "test.cpp", folder / "test.exe"
            path.write_text(fixture)
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-I", str(SDK), str(path), "-o", str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_settings_roundtrip_failures_sizing_and_snapshots(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        with tempfile.TemporaryDirectory(prefix="xbexbe-settings-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            path, exe = folder / "test.cpp", folder / "test.exe"
            path.write_text(FIXTURE)
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK),
                                     "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"),
                                     str(path), str(SDK / "app/settings.cpp"), "-luser32", "-o", str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("graphics settings passed", result.stdout)
            print(result.stdout.strip())


FIXTURE = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <fstream>
#include <iterator>
#include <thread>
#include <toml++/toml.hpp>
#include "app/app.h"
#include "core/log.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
static std::filesystem::path dir=std::filesystem::current_path();
std::filesystem::path app::ExeDir(){return dir;}
void* app::Window(){return nullptr;}
static bool custom_flag=true;
static uint32_t custom_value=7, custom_loaded=0, load_calls=0, save_calls=0;
static unsigned warnings=0;
void logx::Write(Level,const char*,...){++warnings;}
static void LoadCustom(const void* table){
    const auto& t=*static_cast<const toml::table*>(table);custom_loaded=t["custom_record"].value_or(0u);++load_calls;
}
static void SaveCustom(void* table){static_cast<toml::table*>(table)->insert("custom_record",int64_t(custom_loaded));++save_calls;}
const app::GameInfo app::kGame={.settings="settings.toml",.options={{"custom_flag",&custom_flag,nullptr},{"custom_value",nullptr,&custom_value}},.load=LoadCustom,.save=SaveCustom};
static std::filesystem::path File(){return dir/"settings.toml";}
static void Write(const char* s){std::ofstream f(File());f<<s;CHECK(bool(f));}
static std::string Read(){std::ifstream f(File());return {std::istreambuf_iterator<char>(f),{}};}
static void Size(app::Settings s,unsigned w,unsigned h){auto size=app::RenderSize(s);CHECK(size.width==w&&size.height==h);}
int main(){
    using namespace app;
    CHECK(Settings{}.msaa_samples==1&&Settings{}.aniso==0&&Settings{}.vsync&&Settings{}.fps_cap==60&&!Settings{}.ambient_occlusion);
    // Missing file keeps title-provided defaults rather than replacing them with library defaults.
    Get().display_mode=DisplayMode::Windowed;Get().width=1600;Get().height=900;Get().fps_cap=72;Get().render_percent=125;
    Load();auto s=Snapshot();CHECK(s.width==1600&&s.height==900&&s.fps_cap==72&&s.render_percent==125&&load_calls==1&&custom_loaded==0);
    Write("aspect_ratio='16:9'\nwidth=2560\nheight=1440\nrender_percent=100\ncustom_flag=false\ncustom_value=9\ncustom_record=23\n");
    Load();s=Snapshot();CHECK(s.aspect_ratio==AspectRatio::Wide16x9&&s.fps_cap==72&&s.width==2560&&s.height==1440);
    CHECK(!custom_flag&&custom_value==9&&custom_loaded==23&&load_calls==2);CHECK(Widescreen());Size(s,2560,1440);
    CHECK(Save());std::string first=Read();CHECK(first.find("aspect_ratio = '16:9'")!=std::string::npos);
    Apply(Settings{});custom_flag=true;custom_value=1;custom_loaded=0;Load();s=Snapshot();
    CHECK(s.aspect_ratio==AspectRatio::Wide16x9&&s.width==2560&&s.height==1440&&s.fps_cap==72);
    CHECK(!custom_flag&&custom_value==9&&custom_loaded==23&&save_calls==1&&load_calls==3);
    CHECK(unsigned(AspectRatio::Auto)==0&&unsigned(AspectRatio::Wide16x9)==1&&unsigned(AspectRatio::Standard4x3)==2);
    CHECK(unsigned(AspectRatio::Ultra21x9)==3&&unsigned(AspectRatio::Super32x9)==4&&unsigned(AspectRatio::Wide16x10)==5);
    for(auto aspect:{AspectRatio::Auto,AspectRatio::Wide16x9,AspectRatio::Standard4x3,AspectRatio::Ultra21x9,AspectRatio::Super32x9,AspectRatio::Wide16x10}){
        s.aspect_ratio=aspect;Apply(s);CHECK(Save());Apply(Settings{});Load();CHECK(Snapshot().aspect_ratio==aspect);
        if(aspect==AspectRatio::Wide16x10)CHECK(Read().find("aspect_ratio = '16:10'")!=std::string::npos);
    }
    for(unsigned samples:{1u,2u,4u})for(unsigned aniso:{0u,1u,2u,4u,8u,16u}){
        s.msaa_samples=samples;s.aniso=aniso;s.vsync=false;s.fps_cap=144;Apply(s);CHECK(Save());Apply(Settings{});Load();auto quality=Snapshot();
        CHECK(quality.msaa_samples==samples&&quality.aniso==aniso&&!quality.vsync&&quality.fps_cap==144);
        auto saved=toml::parse_file(File().string());CHECK(saved["msaa_samples"].value_or(0u)==samples&&saved["anisotropic_filtering"].value_or(99u)==aniso);
    }
    for(unsigned invalid:{0u,3u,8u,16u,~0u}){s.msaa_samples=invalid;CHECK(Normalize(s).msaa_samples==1);}
    for(bool enabled:{false,true}){
        s.ambient_occlusion=enabled;Apply(s);CHECK(Save());Apply(Settings{});Load();
        CHECK(Snapshot().ambient_occlusion==enabled);
        auto saved=toml::parse_file(File().string());CHECK(saved["ambient_occlusion"].is_boolean());
        CHECK(saved["ambient_occlusion"].value<bool>()==enabled);
    }
    for(const char* text:{"", "ambient_occlusion='true'\n", "ambient_occlusion=1\n", "ambient_occlusion=[]\n"}){
        s.ambient_occlusion=true;Apply(s);Write(text);Load();CHECK(!Snapshot().ambient_occlusion);
    }
    Write("msaa_samples=3\nanisotropic_filtering=7\n");Load();CHECK(Snapshot().msaa_samples==1&&Snapshot().aniso==0);
    Write("msaa_samples=-1\n");Load();CHECK(Snapshot().msaa_samples==1);
    Write("msaa_samples='4'\n");Load();CHECK(Snapshot().msaa_samples==1);
    // Explicit overrides are separate from the native automatic output ratio.
    s.aspect_ratio=AspectRatio::Standard4x3;s.width=2560;s.height=1440;s.render_percent=100;Apply(s);
    CHECK(!Widescreen());CHECK(Output().width==2560&&Output().height==1440);Size(s,1920,1440);
    s.display_mode=DisplayMode::Borderless;Apply(s);auto desk=Desktop();CHECK(Output().width==desk.width&&Output().height==desk.height);
    CHECK(Snapshot().width==2560&&Snapshot().height==1440);auto borderless_size=RenderSize();
    auto auto_size=s;auto_size.width=auto_size.height=0;auto expected_size=RenderSize(auto_size);
    CHECK(borderless_size.width==expected_size.width&&borderless_size.height==expected_size.height);
    s.display_mode=DisplayMode::Windowed;
    s.aspect_ratio=AspectRatio::Wide16x9;s.width=1280;s.height=1024;Apply(s);CHECK(Widescreen());Size(s,1280,720);
    s.aspect_ratio=AspectRatio::Auto;Apply(s);CHECK(!Widescreen());Size(s,1280,960);
    s.width=1500;s.height=1000;Apply(s);CHECK(Widescreen());Size(s,1500,1000);
    s.width=1499;Apply(s);CHECK(Widescreen());Size(s,1499,1000);
    // Auto uses each native shape, including 16:10 and 3440:1440, without bars.
    for(auto output:{Mode{1280,800},Mode{1920,1200},Mode{2560,1600},Mode{2560,1080},Mode{3440,1440},Mode{5120,1440}}){
        s.width=output.width;s.height=output.height;s.render_percent=100;Apply(s);
        CHECK(Widescreen());CHECK(std::abs(RenderAspect()-float(output.width)/output.height)<.000001f);
        Size(s,output.width,output.height);s.render_percent=50;Size(s,output.width/2,output.height/2);
    }
    s.width=2560;s.height=1600;s.render_percent=100;s.aspect_ratio=AspectRatio::Wide16x10;Apply(s);
    CHECK(RenderAspect()==1.6f);Size(s,2560,1600);
    s.height=1440;Size(s,2304,1440);
    s.height=1600;s.aspect_ratio=AspectRatio::Wide16x9;Size(s,2560,1440);
    s.aspect_ratio=AspectRatio::Standard4x3;Size(s,2133,1600);
    s.width=3440;s.height=1440;s.render_percent=100;s.aspect_ratio=AspectRatio::Ultra21x9;Apply(s);
    CHECK(RenderAspect()==21.f/9.f);Size(s,3360,1440);
    s.aspect_ratio=AspectRatio::Super32x9;Apply(s);CHECK(RenderAspect()==32.f/9.f);Size(s,3440,967);
    InvalidateOutput();auto refreshed=Desktop();CHECK(refreshed.width&&refreshed.height);
    s.width=2560;s.height=1440;s.aspect_ratio=AspectRatio::Wide16x9;
    s.render_percent=25;Size(s,640,360);s.render_percent=50;Size(s,1280,720);
    s.render_percent=100;Size(s,2560,1440);s.render_percent=200;Size(s,5120,2880);
    Apply(s);CHECK(RenderScale(480)==6&&RenderScale(0)==1);
    // Safe, deterministic bounds for invalid in-memory and persisted values.
    s.display_mode=DisplayMode(99);s.aspect_ratio=AspectRatio(99);s.width=8193;s.height=1440;
    s.render_percent=~0u;s.fps_cap=~0u;s.aniso=7;s=Normalize(s);
    CHECK(s.display_mode==DisplayMode::Borderless&&s.aspect_ratio==AspectRatio::Auto&&s.width==0&&s.height==0);
    CHECK(s.render_percent==200&&s.fps_cap==1000&&s.aniso==0);
    s.width=640;s.height=0;s.render_percent=0;Apply(s);s=Snapshot();CHECK(!s.width&&!s.height&&s.render_percent==25);
    auto desktop=Desktop(),output=Output();CHECK(output.width==desktop.width&&output.height==desktop.height);
    for(unsigned aniso:{0,1,2,4,8,16}){s.aniso=aniso;CHECK(Normalize(s).aniso==aniso);}
    s.display_mode=DisplayMode::Windowed;s.width=8192;s.height=8192;s.aspect_ratio=AspectRatio::Wide16x9;s.render_percent=200;Size(s,16384,9216);
    Write("width=320\nheight=240\nrender_percent=999\nfps_cap=99999\nanisotropic_filtering=3\naspect_ratio='bad'\n");
    Apply(Settings{});Load();s=Snapshot();CHECK(s.width==320&&s.height==240&&s.render_percent==200&&s.fps_cap==1000&&s.aniso==0&&s.aspect_ratio==AspectRatio::Auto);
    Write("width=640\nheight=0\nrender_percent=0\n");Load();s=Snapshot();CHECK(s.width==0&&s.height==0&&s.render_percent==25);
    Write("aspect_ratio=123\nrender_percent=-1\nwidth=-100\n");Load();CHECK(Snapshot().aspect_ratio==AspectRatio::Auto&&Snapshot().render_percent==25&&Snapshot().width==0);
    auto before=Snapshot();unsigned calls=load_calls;Write("width = [\n");Load();CHECK(Snapshot().render_percent==before.render_percent&&Snapshot().width==before.width&&load_calls==calls+1&&custom_loaded==0);
    // A failed replacement cannot truncate the existing settings; failed temp creation is also reported.
    s=Settings{};s.display_mode=DisplayMode::Windowed;s.width=1920;s.height=1080;Apply(s);CHECK(Save());first=Read();
    HANDLE held=CreateFileW(File().c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);CHECK(held!=INVALID_HANDLE_VALUE);
    s.width=2560;s.height=1440;s.msaa_samples=4;s.aniso=16;s.vsync=false;s.fps_cap=144;s.ambient_occlusion=true;Apply(s);CHECK(!Save());CHECK(Read()==first);CloseHandle(held);
    CHECK(Save());CHECK(Read()!=first);auto original_dir=dir;dir/="missing-parent";CHECK(!Save());dir=original_dir;
    for(auto& entry:std::filesystem::directory_iterator(dir))CHECK(entry.path().filename().string().find(".tmp.")==std::string::npos);
    CHECK(warnings>=2);
    // Snapshots and derived render dimensions never observe half of another thread's update.
    Settings a{},b{};a.display_mode=b.display_mode=DisplayMode::Windowed;a.width=640;a.height=480;a.aspect_ratio=AspectRatio::Standard4x3;a.join_ip="a";
    b.width=2560;b.height=1440;b.aspect_ratio=AspectRatio::Wide16x9;b.render_percent=50;b.join_ip=std::string(128,'b');b.msaa_samples=4;b.aniso=16;b.vsync=false;b.fps_cap=144;
    Apply(a);std::atomic<bool> done=false;
    std::thread writer([&]{for(unsigned i=0;i<12000;i++)Apply(i&1?a:b);done=true;});
    unsigned checked=0;do{
        auto copy=Snapshot();CHECK((copy.width==640&&copy.height==480&&copy.join_ip=="a")||(copy.width==2560&&copy.height==1440&&copy.join_ip==std::string(128,'b')));
        CHECK(copy.width==640?(copy.msaa_samples==1&&copy.aniso==0&&copy.vsync&&copy.fps_cap==60):(copy.msaa_samples==4&&copy.aniso==16&&!copy.vsync&&copy.fps_cap==144));
        auto dimensions=RenderSize();CHECK((dimensions.width==640&&dimensions.height==480)||(dimensions.width==1280&&dimensions.height==720));++checked;
    }while(!done||checked<1000);writer.join();
    CHECK(Save());auto parsed=toml::parse_file(File().string());auto w=parsed["width"].value_or(0u),h=parsed["height"].value_or(0u);
    CHECK((w==640&&h==480)||(w==2560&&h==1440));
    app::Apply({});CHECK(app::Snapshot().brightness_percent==100);
    Write("brightness=75\n");app::Load();CHECK(app::Snapshot().brightness_percent==75);
    CHECK(app::Save());app::Apply({});app::Load();CHECK(app::Snapshot().brightness_percent==75);
    Write("brightness=-1\n");app::Load();CHECK(app::Snapshot().brightness_percent==50);
    Write("brightness=99999\n");app::Load();CHECK(app::Snapshot().brightness_percent==150);
    app::Apply({});Write("brightness='dark'\n");app::Load();CHECK(app::Snapshot().brightness_percent==100);
    std::puts("graphics settings passed: actual TOML/callback roundtrip, defaults/validation, aspect/render sizing, failed atomic replacement, coherent threaded snapshots");
}
'''


if __name__ == "__main__":
    unittest.main()
