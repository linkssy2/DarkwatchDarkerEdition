"""Title view preferences through the actual atomic settings file and callback path."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"

FIXTURE = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <thread>
#include <toml++/toml.hpp>
#include "app/app.h"
#include "core/log.h"
#include "common/graphics_view.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line%d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
std::filesystem::path app::ExeDir(){return std::filesystem::current_path();}
void* app::Window(){return nullptr;}
void logx::Write(Level,const char*,...){}
const app::GameInfo app::kGame{.settings="view.toml",.load=darkwatch::view::Load,.save=darkwatch::view::Save};
static void Write(const char* text){std::ofstream f("view.toml");f<<text;CHECK(bool(f));}
static std::string Read(){std::ifstream f("view.toml");return {std::istreambuf_iterator<char>(f),{}};}
static void Values(unsigned f,unsigned r,bool fps=false,bool hd=true,unsigned weapon=100,bool borders=true){auto s=darkwatch::view::Snapshot();if(s.fov_percent!=f||s.reticle_percent!=r)std::fprintf(stderr,"actual%u/%u expected%u/%u\n",s.fov_percent,s.reticle_percent,f,r);CHECK(s.fov_percent==f&&s.reticle_percent==r&&s.show_fps==fps&&s.hd_ui==hd&&s.viewmodel_fov_percent==weapon&&s.cutscene_borders==borders);CHECK(darkwatch::view::ReticleScale()==float(r)/100);}
int main(){using namespace darkwatch::view;
 app::Load();Values(100,100);
 Write("field_of_view_scale=125\nreticle_size=80\nshow_fps=true\nhd_ui=false\n");app::Load();Values(125,80,true,false);
 CHECK(app::Save());auto original=Read();Apply({50,200});app::Load();Values(125,80,true,false);
 auto table=toml::parse(original);CHECK(table["field_of_view_scale"].value_or(0)==125&&table["reticle_size"].value_or(0)==80&&table["show_fps"].value_or(false)&&table["hd_ui"].is_boolean()&&!table["hd_ui"].value_or(true));
 for(const char* invalid:{"hd_ui=0\n","hd_ui='false'\n","hd_ui=[]\n"}){Write(invalid);app::Load();Values(100,100);}
 Write("field_of_view_scale=120\nreticle_size=50\nhd_ui=true\n");app::Load();Values(120,50);CHECK(app::Save());Apply({});app::Load();Values(120,50);
 Write("field_of_view_scale=-1\nreticle_size=99999999999\n");app::Load();Values(50,200);
 Write("field_of_view_scale=99999999999\nreticle_size=-99\n");app::Load();Values(200,50);
 Write("field_of_view_scale='wrong'\nreticle_size=false\nshow_fps=1\n");app::Load();Values(100,100);
 Write("field_of_view_scale=[\n");app::Load();Values(100,100);
 Apply({0,~0u});Values(50,200);Apply({~0u,0});Values(200,50);
 Apply({110,90,true});CHECK(app::Save());original=Read();
 HANDLE held=CreateFileW(L"view.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);CHECK(held!=INVALID_HANDLE_VALUE);
 Apply({130,75,false,false});CHECK(!app::Save());CHECK(Read()==original);Values(130,75,false,false);CloseHandle(held);
 CHECK(app::Save());Apply({});app::Load();Values(130,75,false,false);
 Write("field_of_view_scale=125\nreticle_size=80\nshow_fps=true\nhd_ui=false\nweapon_field_of_view_scale=140\ncutscene_borders=false\n");app::Load();Values(125,80,true,false,140,false);
 CHECK(app::Save());original=Read();Apply({});app::Load();Values(125,80,true,false,140,false);
 table=toml::parse(original);CHECK(table["weapon_field_of_view_scale"].is_integer()&&table["weapon_field_of_view_scale"].value_or(0)==140&&table["cutscene_borders"].is_boolean()&&!table["cutscene_borders"].value_or(true));
 held=CreateFileW(L"view.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);CHECK(held!=INVALID_HANDLE_VALUE);
 Apply({130,75,false,false,60,true});CHECK(!app::Save());CHECK(Read()==original);Values(130,75,false,false,60,true);CloseHandle(held);
 Apply({});app::Load();Values(125,80,true,false,140,false);
 for(const char* invalid:{"weapon_field_of_view_scale='150'\n","weapon_field_of_view_scale=false\n","weapon_field_of_view_scale=150.0\n","weapon_field_of_view_scale=[]\n","cutscene_borders=0\n","cutscene_borders='false'\n","cutscene_borders=[]\n"}){Write(invalid);app::Load();Values(100,100);}
 Write("weapon_field_of_view_scale=-1\ncutscene_borders=false\n");app::Load();Values(100,100,false,true,50,false);
 Write("weapon_field_of_view_scale=99999999999\ncutscene_borders=true\n");app::Load();Values(100,100,false,true,150,true);
 Apply({120,80,true,false,0,false});Values(120,80,true,false,50,false);Apply({120,80,true,false,~0u,false});Values(120,80,true,false,150,false);
 Apply({50,200,true,true,150,false});std::atomic<bool> done=false;
 std::thread writer([&]{for(unsigned i=0;i<10000;++i)Apply(i&1?Settings{50,200,true,true,150,false}:Settings{150,50,false,false,50,true});done=true;});
 unsigned checked=0;do{auto s=Snapshot();CHECK((s.fov_percent==50&&s.reticle_percent==200&&s.show_fps&&s.hd_ui&&s.viewmodel_fov_percent==150&&!s.cutscene_borders)||(s.fov_percent==150&&s.reticle_percent==50&&!s.show_fps&&!s.hd_ui&&s.viewmodel_fov_percent==50&&s.cutscene_borders));++checked;}while(!done||checked<1000);writer.join();
 for(bool fps:{false,true})for(bool hd:{false,true})for(bool borders:{false,true})for(unsigned weapon:{50u,100u,150u}){Apply({120,50,fps,hd,weapon,borders});Values(120,50,fps,hd,weapon,borders);}
 Apply({});CHECK(Snapshot().hd_textures);
 Write("hd_textures=false\n");app::Load();CHECK(!Snapshot().hd_textures);CHECK(app::Save());Apply({});app::Load();CHECK(!Snapshot().hd_textures&&Snapshot().hd_ui);
 Write("hd_textures='false'\n");app::Load();CHECK(Snapshot().hd_textures);
 std::puts("view settings: defaults, bounds, malformed input, actual atomic save failure and coherent snapshots passed");
}
'''

COOP_FIXTURE = FIXTURE[:FIXTURE.index("int main(){")] + r'''
static void PlayerView(unsigned player,unsigned fov,unsigned reticle,unsigned weapon){
 const auto s=darkwatch::view::Snapshot(player);
 CHECK(s.fov_percent==fov&&s.reticle_percent==reticle&&s.viewmodel_fov_percent==weapon);
 CHECK(darkwatch::view::ReticleScale(player)==float(reticle)/100);
}
static void Shared(bool fps,bool hd,bool borders,bool textures){
 for(unsigned player:{0u,1u}){const auto s=darkwatch::view::Snapshot(player);
  CHECK(s.show_fps==fps&&s.hd_ui==hd&&s.cutscene_borders==borders&&s.hd_textures==textures);}
}
int main(){using namespace darkwatch::view;
 app::Load();PlayerView(0,100,100,100);PlayerView(1,100,100,100);Shared(false,true,true,true);
 const std::string legacy="field_of_view_scale=125\nreticle_size=80\nweapon_field_of_view_scale=140\nshow_fps=true\nhd_ui=false\ncutscene_borders=false\nhd_textures=false\nfps_cap=144\nbrightness=113\n";
 Write(legacy.c_str());app::Load();PlayerView(0,125,80,140);PlayerView(1,125,80,140);Shared(true,false,false,false);
 CHECK(app::Save());auto saved=toml::parse(Read());
 CHECK(saved["player2_view"].is_table()&&saved["player2_view"].as_table()->size()==3);
 CHECK(saved["field_of_view_scale"].value_or(0)==125&&saved["player2_view"]["field_of_view_scale"].value_or(0)==125);

 // A partial or malformed override inherits the loaded legacy view, never stale runtime values.
 Write((legacy+"[player2_view]\nreticle_size=160\nshow_fps=false\nhd_ui=true\ncutscene_borders=true\nhd_textures=true\n").c_str());
 app::Load();PlayerView(0,125,80,140);PlayerView(1,125,160,140);Shared(true,false,false,false);
 for(const char* invalid:{"player2_view='bad'\n","player2_view=false\n","player2_view=[]\n","player2_view=42\n",
   "[player2_view]\nfield_of_view_scale='90'\nreticle_size=false\nweapon_field_of_view_scale=75.0\n",
   "[player2_view]\nfield_of_view_scale=[]\nreticle_size={}\nweapon_field_of_view_scale='75'\n"}){
  Write((legacy+invalid).c_str());app::Load();PlayerView(0,125,80,140);PlayerView(1,125,80,140);Shared(true,false,false,false);
 }
 Write((legacy+"[player2_view]\nfield_of_view_scale=-1\nreticle_size=99999999999\nweapon_field_of_view_scale=-1\n").c_str());
 app::Load();PlayerView(0,125,80,140);PlayerView(1,50,200,50);
 Write((legacy+"[player2_view]\nfield_of_view_scale=99999999999\nreticle_size=-1\nweapon_field_of_view_scale=99999999999\n").c_str());
 app::Load();PlayerView(0,125,80,140);PlayerView(1,200,50,150);
 Write("[player2_view]\nfield_of_view_scale=110\n");app::Load();PlayerView(0,100,100,100);PlayerView(1,110,100,100);
 Write("player2_view=[\n");app::Load();PlayerView(0,100,100,100);PlayerView(1,100,100,100);

 // Updating either player preserves the other view; display flags remain shared.
 Apply({115,85,true,false,135,false,false},0);
 Apply({165,155,false,true,65,true,true},1);
 PlayerView(0,115,85,135);PlayerView(1,165,155,65);Shared(false,true,true,true);
 Apply({120,90,true,false,140,false,false},0);
 PlayerView(0,120,90,140);PlayerView(1,165,155,65);Shared(true,false,false,false);
 CHECK(app::Save());const auto original=Read();saved=toml::parse(original);
 CHECK(saved["field_of_view_scale"].value_or(0)==120&&saved["weapon_field_of_view_scale"].value_or(0)==140&&saved["reticle_size"].value_or(0)==90);
 CHECK(saved["player2_view"]["field_of_view_scale"].value_or(0)==165&&saved["player2_view"]["weapon_field_of_view_scale"].value_or(0)==65&&saved["player2_view"]["reticle_size"].value_or(0)==155);
 CHECK(saved["player2_view"].as_table()->size()==3&&saved["fps_cap"].value_or(0)==144&&saved["brightness"].value_or(0)==113);
 Apply({},0);Apply({},1);app::Load();PlayerView(0,120,90,140);PlayerView(1,165,155,65);Shared(true,false,false,false);
 CHECK(app::Snapshot().fps_cap==144&&app::Snapshot().brightness_percent==113);
 toml::table callback_table{{"unrelated",123}};Save(&callback_table);CHECK(callback_table["unrelated"].value_or(0)==123);

 // A locked destination leaves the entire previous two-player file intact.
 HANDLE held=CreateFileW(L"view.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);CHECK(held!=INVALID_HANDLE_VALUE);
 Apply({150,110,false,true,110,true,true},0);Apply({70,65,false,true,55,true,true},1);
 CHECK(!app::Save());CHECK(Read()==original);PlayerView(0,150,110,110);PlayerView(1,70,65,55);
 CloseHandle(held);app::Load();PlayerView(0,120,90,140);PlayerView(1,165,155,65);Shared(true,false,false,false);
 Apply({0,~0u,false,true,~0u,true,true},1);PlayerView(0,120,90,140);PlayerView(1,50,200,150);
 Apply({130,95,false,true,75,true,true},99);PlayerView(0,130,95,75);PlayerView(99,130,95,75);PlayerView(1,50,200,150);

 // Concurrent player updates cannot overwrite the other player's triple or tear a snapshot.
 Apply({50,200,false,true,150,true,true},0);Apply({60,190,false,true,140,true,true},1);
 std::atomic<unsigned> finished=0;
 std::thread p1([&]{for(unsigned i=0;i<10000;++i)Apply(i&1?Settings{50,200,false,true,150}:Settings{150,50,false,true,50},0);++finished;});
 std::thread p2([&]{for(unsigned i=0;i<10000;++i)Apply(i&1?Settings{60,190,false,true,140}:Settings{160,60,false,true,60},1);++finished;});
 unsigned checked=0;do{
  auto a=Snapshot(0),b=Snapshot(1);
  CHECK((a.fov_percent==50&&a.reticle_percent==200&&a.viewmodel_fov_percent==150)||(a.fov_percent==150&&a.reticle_percent==50&&a.viewmodel_fov_percent==50));
  CHECK((b.fov_percent==60&&b.reticle_percent==190&&b.viewmodel_fov_percent==140)||(b.fov_percent==160&&b.reticle_percent==60&&b.viewmodel_fov_percent==60));
  ++checked;
 }while(finished!=2||checked<1000);
 p1.join();p2.join();PlayerView(0,50,200,150);PlayerView(1,60,190,140);
 std::puts("two-player view settings: legacy migration, partial/invalid overrides, isolation, shared flags, roundtrip, atomic save failure and concurrent snapshots passed");
}
'''


class GraphicsViewTests(unittest.TestCase):
    def test_actual_title_settings_persistence_and_snapshots(self):
        self.run_fixture(FIXTURE)

    def test_independent_player_views_migrate_and_persist(self):
        self.run_fixture(COOP_FIXTURE)

    def run_fixture(self, fixture):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="graphics-view-", dir=ROOT / "build") as name:
            folder = Path(name)
            cpp, exe = folder / "test.cpp", folder / "test.exe"
            cpp.write_text(fixture)
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK),
                "-I", str(ROOT / "xbexbe/src"), "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"),
                str(cpp), str(SDK / "app/settings.cpp"), str(ROOT / "xbexbe/src/common/graphics_view.cpp"),
                "-luser32", "-o", str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
