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
 Write("field_of_view_scale=99999999999\nreticle_size=-99\n");app::Load();Values(200,0);
 Write("field_of_view_scale='wrong'\nreticle_size=false\nshow_fps=1\n");app::Load();Values(100,100);
 Write("field_of_view_scale=[\n");app::Load();Values(100,100);
 Apply({0,~0u});Values(50,200);Apply({~0u,0});Values(200,0);
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
 CHECK(saved["player2_view"].is_table()&&saved["player2_view"].as_table()->size()==8);
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
 app::Load();PlayerView(0,125,80,140);PlayerView(1,200,0,150);
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
 CHECK(saved["player2_view"].as_table()->size()==8&&saved["fps_cap"].value_or(0)==144&&saved["brightness"].value_or(0)==113);
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
    def test_split_layout_is_shared_defaults_horizontal_and_preserves_player_views(self):
        self.run_fixture(FIXTURE[:FIXTURE.index("int main(){")] + r'''
int main(){using namespace darkwatch::view;
 CHECK(!Snapshot().vertical_split&&!Snapshot(1).vertical_split);
 for(const char* invalid:{"", "vertical_split='true'\n", "vertical_split=1\n", "vertical_split=[]\n",
                         "[player2_view]\nvertical_split=true\n"}){
  auto s=Snapshot();s.vertical_split=true;Apply(s);Write(invalid);app::Load();
  CHECK(!Snapshot().vertical_split&&!Snapshot(1).vertical_split);
 }
 Write("vertical_split=true\nfield_of_view_scale=80\nweapon_field_of_view_scale=70\nreticle_size=60\ncamera_mode=2\nshow_hud=false\n[player2_view]\nvertical_split=false\nfield_of_view_scale=130\nweapon_field_of_view_scale=140\nreticle_size=150\ncamera_mode=1\nshow_hud=true\n");
 app::Load();CHECK(Snapshot().vertical_split&&Snapshot(1).vertical_split);CHECK(app::Save());
 const auto saved=Read();auto table=toml::parse(saved);CHECK(table["vertical_split"].value_or(false)&&!table["player2_view"]["vertical_split"]);
 Apply({});app::Load();CHECK(Snapshot().vertical_split&&Snapshot(1).vertical_split);
 for(unsigned player:{0u,1u})for(bool vertical:{false,true}){
  auto s=Snapshot(player);s.vertical_split=vertical;Apply(s,player);
  const auto a=Snapshot(),b=Snapshot(1);CHECK(a.vertical_split==vertical&&b.vertical_split==vertical);
  CHECK(a.fov_percent==80&&a.viewmodel_fov_percent==70&&a.reticle_percent==60&&!a.show_hud&&a.camera_mode==CameraMode::Shoulder);
  CHECK(b.fov_percent==130&&b.viewmodel_fov_percent==140&&b.reticle_percent==150&&b.show_hud&&b.camera_mode==CameraMode::Centered);
 }
 HANDLE held=CreateFileW(L"view.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);CHECK(held!=INVALID_HANDLE_VALUE);
 auto s=Snapshot();s.vertical_split=false;Apply(s);CHECK(!app::Save()&&Read()==saved);CloseHandle(held);
 CHECK(app::Save());Apply({});app::Load();CHECK(!Snapshot().vertical_split&&!Snapshot(1).vertical_split);
 for(unsigned flags=0;flags<256;++flags){
  auto s=Snapshot(1);s.vertical_split=flags&1;s.original_ui_aspect=flags&2;s.movie_aspect_fit=flags&4;s.forever_ragdolls=flags&8;
  s.hd_textures=flags&16;s.cutscene_borders=flags&32;s.hd_ui=flags&64;s.show_fps=flags&128;Apply(s,1);
  for(unsigned p:{0u,1u}){const auto a=Snapshot(p);CHECK(a.vertical_split==s.vertical_split&&a.original_ui_aspect==s.original_ui_aspect);
   CHECK(a.movie_aspect_fit==s.movie_aspect_fit&&a.forever_ragdolls==s.forever_ragdolls&&a.hd_textures==s.hd_textures);
   CHECK(a.cutscene_borders==s.cutscene_borders&&a.hd_ui==s.hd_ui&&a.show_fps==s.show_fps);
   CHECK(a.fov_percent==(p?130u:80u)&&a.show_hud==bool(p)&&a.camera_mode==(p?CameraMode::Centered:CameraMode::Shoulder));}
 }
 std::puts("split layout: horizontal default, shared strict bool, atomic save/failure, independent views and 256 flag combinations passed");
}
''')

    def test_camera_modes_persist_per_player_with_coherent_snapshots(self):
        self.run_fixture(FIXTURE[:FIXTURE.index("int main(){")] + r'''
int main(){using namespace darkwatch::view;
 Write("");app::Load();CHECK(Snapshot().camera_mode==CameraMode::FirstPerson&&Snapshot(1).camera_mode==CameraMode::FirstPerson);
 for(unsigned player:{0u,1u})for(auto mode:{CameraMode::FirstPerson,CameraMode::Centered,CameraMode::Shoulder}){
  const auto other=Snapshot(1-player);auto next=Snapshot(player);next.camera_mode=mode;Apply(next,player);
  CHECK(Snapshot(player).camera_mode==mode&&Snapshot(1-player).camera_mode==other.camera_mode);
  CHECK(app::Save());Apply({},player);app::Load();
  CHECK(Snapshot(player).camera_mode==mode&&Snapshot(1-player).camera_mode==other.camera_mode);
 }
 Write("camera_mode=1\n");app::Load();CHECK(Snapshot().camera_mode==CameraMode::Centered&&Snapshot(1).camera_mode==CameraMode::Centered);
 Write("camera_mode=1\n[player2_view]\ncamera_mode=2\n");app::Load();
 CHECK(Snapshot().camera_mode==CameraMode::Centered&&Snapshot(1).camera_mode==CameraMode::Shoulder);
 for(const char* invalid:{"-1","3","99999999999","'1'","1.0","true","[]"}){
  Write((std::string("camera_mode=")+invalid+"\n").c_str());app::Load();
  CHECK(Snapshot().camera_mode==CameraMode::FirstPerson&&Snapshot(1).camera_mode==CameraMode::FirstPerson);
  Write((std::string("camera_mode=2\n[player2_view]\ncamera_mode=")+invalid+"\n").c_str());app::Load();
  CHECK(Snapshot().camera_mode==CameraMode::Shoulder&&Snapshot(1).camera_mode==CameraMode::FirstPerson);
 }
 auto bad=Snapshot();bad.camera_mode=CameraMode(~0u);Apply(bad,99);
 CHECK(Snapshot().camera_mode==CameraMode::FirstPerson&&Snapshot(99).camera_mode==CameraMode::FirstPerson);
 Settings a,b;a.fov_percent=80;a.camera_mode=CameraMode::Centered;b.fov_percent=120;b.camera_mode=CameraMode::Shoulder;
 Apply(a);Apply(b,1);std::atomic<unsigned> finished=0;
 std::thread p1([&]{for(unsigned i=0;i<10000;++i)Apply(i&1?a:b,0);++finished;});
 std::thread p2([&]{for(unsigned i=0;i<10000;++i)Apply(i&1?b:a,1);++finished;});
 unsigned checked=0;do{for(unsigned player:{0u,1u}){const auto s=Snapshot(player);
  CHECK((s.fov_percent==80&&s.camera_mode==CameraMode::Centered)||(s.fov_percent==120&&s.camera_mode==CameraMode::Shoulder));
  CHECK(s.show_hud&&s.movie_aspect_fit&&s.hd_ui&&s.hd_textures&&!s.forever_ragdolls);
 }++checked;}while(finished!=2||checked<1000);p1.join();p2.join();
 CHECK(Snapshot().camera_mode==CameraMode::Centered&&Snapshot(1).camera_mode==CameraMode::Shoulder);
 std::puts("camera modes: default first-person, independent persistence, migration, strict validation, fallback owner and coherent concurrent snapshots passed");
}
''')

    def test_player_hud_and_reticle_colors_persist_independently(self):
        self.run_fixture(FIXTURE[:FIXTURE.index("int main(){")] + r'''
int main(){using namespace darkwatch::view;
 Write("");app::Load();
 for(unsigned p:{0u,1u}){const auto s=Snapshot(p);CHECK(s.show_hud&&s.reticle_normal_color==kOriginalReticleColor&&s.reticle_enemy_color==kOriginalReticleColor&&s.reticle_friendly_color==kOriginalReticleColor);}
 auto p1=Snapshot(),p2=Snapshot(1);p1.show_hud=false;p1.reticle_normal_color=0;p1.reticle_enemy_color=0x123456;p1.reticle_friendly_color=0xABCDEF;
 p2.reticle_normal_color=0x102030;p2.reticle_enemy_color=0xFFFFFF;p2.reticle_friendly_color=0x0000FF;
 Apply(p1);Apply(p2,1);CHECK(!Snapshot().show_hud&&Snapshot(1).show_hud&&Snapshot().reticle_normal_color==0&&Snapshot().reticle_enemy_color==0x123456&&Snapshot().reticle_friendly_color==0xABCDEF);
 CHECK(app::Save());Apply({});Apply({},1);app::Load();
 CHECK(!Snapshot().show_hud&&Snapshot(1).show_hud&&Snapshot().reticle_normal_color==0&&Snapshot(1).reticle_normal_color==0x102030&&Snapshot(1).reticle_enemy_color==0xFFFFFF&&Snapshot(1).reticle_friendly_color==0x0000FF);
 Write("show_hud=false\nreticle_normal_color=1193046\n[player2_view]\nshow_hud=true\nreticle_friendly_color=16777215\n");app::Load();
 CHECK(!Snapshot().show_hud&&Snapshot(1).show_hud&&Snapshot(1).reticle_normal_color==1193046&&Snapshot(1).reticle_friendly_color==0xFFFFFF);
 for(const char* invalid:{"show_hud=1\nreticle_normal_color=-1\nreticle_enemy_color=99999999999\nreticle_friendly_color=16777217\n","show_hud='false'\nreticle_normal_color='red'\nreticle_enemy_color=false\nreticle_friendly_color=[]\n"}){
  Write(invalid);app::Load();for(unsigned p:{0u,1u}){const auto s=Snapshot(p);CHECK(s.show_hud&&s.reticle_normal_color==kOriginalReticleColor&&s.reticle_enemy_color==kOriginalReticleColor&&s.reticle_friendly_color==kOriginalReticleColor);}
 }
 auto invalid=Snapshot();invalid.reticle_normal_color=~0u;invalid.reticle_enemy_color=0x1000001;invalid.reticle_friendly_color=0xFFFFFF;
 Apply(invalid,99);CHECK(Snapshot().reticle_normal_color==kOriginalReticleColor&&Snapshot().reticle_enemy_color==kOriginalReticleColor&&Snapshot().reticle_friendly_color==0xFFFFFF&&Snapshot(1).reticle_friendly_color==kOriginalReticleColor);
 CHECK(app::Save());const auto original=Read();HANDLE held=CreateFileW(L"view.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);CHECK(held!=INVALID_HANDLE_VALUE);
 Apply(p1);Apply(p2,1);CHECK(!app::Save()&&Read()==original);CloseHandle(held);
 std::puts("HUD and RGB settings: native defaults, black/white/custom colors, per-player isolation, migration, validation, persistence and atomic save failure passed");
}
''')

    def test_menu_aspect_shared_persistence_and_isolation(self):
        self.run_fixture(FIXTURE[:FIXTURE.index("int main(){")] + r'''
int main(){using namespace darkwatch::view;
 CHECK(!Snapshot().original_ui_aspect&&!Snapshot(1).original_ui_aspect);
 for(const char* invalid:{"", "original_ui_aspect='true'\n", "original_ui_aspect=1\n", "original_ui_aspect=[]\n",
                         "[player2_view]\noriginal_ui_aspect=true\n"}){
  auto s=Snapshot();s.original_ui_aspect=true;Apply(s);
  Write(invalid);app::Load();CHECK(!Snapshot().original_ui_aspect&&!Snapshot(1).original_ui_aspect);
 }
 Write("original_ui_aspect=true\nmovie_aspect_fit=false\ncamera_mode=2\nshow_hud=false\n[player2_view]\noriginal_ui_aspect=false\nfield_of_view_scale=130\ncamera_mode=1\nshow_hud=true\n");
 app::Load();CHECK(Snapshot().original_ui_aspect&&Snapshot(1).original_ui_aspect);CHECK(app::Save());
 const auto saved=Read();auto table=toml::parse(saved);
 CHECK(table["original_ui_aspect"].value_or(false)&&!table["player2_view"]["original_ui_aspect"]);
 Apply({});app::Load();CHECK(Snapshot().original_ui_aspect&&!Snapshot().movie_aspect_fit);
 auto p2=Snapshot(1);p2.original_ui_aspect=false;Apply(p2,1);
 CHECK(!Snapshot().original_ui_aspect&&!Snapshot(1).original_ui_aspect);
 CHECK(Snapshot().fov_percent==100&&Snapshot(1).fov_percent==130);
 CHECK(Snapshot().camera_mode==CameraMode::Shoulder&&Snapshot(1).camera_mode==CameraMode::Centered);
 CHECK(!Snapshot().show_hud&&Snapshot(1).show_hud&&!Snapshot().movie_aspect_fit);
 HANDLE held=CreateFileW(L"view.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
 CHECK(held!=INVALID_HANDLE_VALUE);CHECK(!app::Save()&&Read()==saved);CloseHandle(held);
 CHECK(app::Save());Apply({});app::Load();CHECK(!Snapshot().original_ui_aspect&&!Snapshot(1).original_ui_aspect);
 for(unsigned flags=0;flags<128;++flags){
  auto s=Snapshot(1);s.original_ui_aspect=flags&1;s.movie_aspect_fit=flags&2;s.forever_ragdolls=flags&4;
  s.hd_textures=flags&8;s.cutscene_borders=flags&16;s.hd_ui=flags&32;s.show_fps=flags&64;Apply(s,1);
  for(unsigned player:{0u,1u}){const auto a=Snapshot(player);
   CHECK(a.original_ui_aspect==s.original_ui_aspect&&a.movie_aspect_fit==s.movie_aspect_fit&&a.forever_ragdolls==s.forever_ragdolls);
   CHECK(a.hd_textures==s.hd_textures&&a.cutscene_borders==s.cutscene_borders&&a.hd_ui==s.hd_ui&&a.show_fps==s.show_fps);
   CHECK(a.camera_mode==(player?CameraMode::Centered:CameraMode::Shoulder)&&a.show_hud==bool(player));
  }
 }
 std::puts("menu aspect: legacy/default widescreen, strict bool, shared player flag, atomic roundtrip/failure and all packed flag combinations passed");
}
''')

    def test_movie_fit_shared_persistence(self):
        self.run_fixture(FIXTURE[:FIXTURE.index("int main(){")] + r'''
int main(){using namespace darkwatch::view;
 CHECK(Snapshot().movie_aspect_fit&&Snapshot(1).movie_aspect_fit);
 for(const char* invalid:{"", "movie_aspect_fit='false'\n", "movie_aspect_fit=0\n"}){
  Write(invalid);app::Load();CHECK(Snapshot().movie_aspect_fit&&Snapshot(1).movie_aspect_fit);
 }
 Write("movie_aspect_fit=false\n");app::Load();CHECK(!Snapshot().movie_aspect_fit);
 CHECK(app::Save());Apply({});app::Load();CHECK(!Snapshot().movie_aspect_fit&&!Snapshot(1).movie_aspect_fit);
 auto p2=Snapshot(1);p2.movie_aspect_fit=true;Apply(p2,1);
 CHECK(Snapshot().movie_aspect_fit&&Snapshot(1).movie_aspect_fit);CHECK(app::Save());
 auto table=toml::parse(Read());CHECK(table["movie_aspect_fit"].value_or(false));
 CHECK(!table["player2_view"]["movie_aspect_fit"]);
 for(bool fit:{false,true})for(bool bodies:{false,true}){
  auto s=Snapshot();s.movie_aspect_fit=fit;s.forever_ragdolls=bodies;Apply(s);
  CHECK(Snapshot().movie_aspect_fit==fit&&Snapshot(1).movie_aspect_fit==fit);
  CHECK(Snapshot().forever_ragdolls==bodies&&Snapshot().hd_ui&&Snapshot().hd_textures);
 }
 std::puts("movie fit defaults, validation, shared persistence and flag isolation passed");
}
''')

    def test_reticle_zero_and_original_size_for_each_player(self):
        self.run_fixture(COOP_FIXTURE[:COOP_FIXTURE.index("int main(){")] + r'''
int main(){using namespace darkwatch::view;
 // Old supported percentages retain their exact scale, without a migration.
 for(unsigned old:{50u,80u,100u,155u,200u}){
  Write(("reticle_size="+std::to_string(old)+"\n").c_str());app::Load();
  CHECK(Snapshot().reticle_percent==old&&Snapshot(1).reticle_percent==old);
  CHECK(ReticleScale()==float(old)/100&&ReticleScale(1)==float(old)/100);
 }
 Apply({},0);Apply({},1);CHECK(ReticleScale()==1&&ReticleScale(1)==1);
 for(unsigned player:{0u,1u})for(unsigned size:{0u,1u,25u,49u,100u,200u}){
  const auto other=Snapshot(1-player).reticle_percent;
  auto setting=Snapshot(player);setting.reticle_percent=size;Apply(setting,player);
  CHECK(Snapshot(player).reticle_percent==size&&ReticleScale(player)==float(size)/100);
  CHECK(Snapshot(1-player).reticle_percent==other);
  CHECK(app::Save());Apply({},player);app::Load();
  CHECK(Snapshot(player).reticle_percent==size&&Snapshot(1-player).reticle_percent==other);
 }
 Write("reticle_size=0\n[player2_view]\nreticle_size=100\n");app::Load();
 CHECK(ReticleScale()==0&&ReticleScale(1)==1);
 Write("reticle_size=100\n[player2_view]\nreticle_size=0\n");app::Load();
 CHECK(ReticleScale()==1&&ReticleScale(1)==0);
 std::puts("reticle settings: 0 off, 100 original, unchanged legacy sizes, both players isolated and persisted");
}
''')

    def test_forever_ragdolls_default_shared_and_persisted(self):
        self.run_fixture(FIXTURE[:FIXTURE.index("int main(){")] + r'''
int main(){using namespace darkwatch::view;
 app::Load();CHECK(!Snapshot().forever_ragdolls&&!Snapshot(1).forever_ragdolls);
 for(const char* invalid:{"", "forever_ragdolls=1\n", "forever_ragdolls='true'\n", "forever_ragdolls=[]\n"}){
  auto enabled=Snapshot();enabled.forever_ragdolls=true;Apply(enabled);
  Write(invalid);app::Load();CHECK(!Snapshot().forever_ragdolls&&!Snapshot(1).forever_ragdolls);
 }
 Write("forever_ragdolls=true\n[player2_view]\nforever_ragdolls=false\nfield_of_view_scale=130\n");
 app::Load();CHECK(Snapshot().forever_ragdolls&&Snapshot(1).forever_ragdolls);
 CHECK(Snapshot().fov_percent==100&&Snapshot(1).fov_percent==130);
 CHECK(app::Save());const auto saved=Read();auto table=toml::parse(saved);
 CHECK(table["forever_ragdolls"].is_boolean()&&table["forever_ragdolls"].value_or(false));
 CHECK(!table["player2_view"]["forever_ragdolls"]);
 Apply({});app::Load();CHECK(Snapshot().forever_ragdolls&&Snapshot(1).forever_ragdolls);
 auto p2=Snapshot(1);p2.forever_ragdolls=false;Apply(p2,1);
 CHECK(!Snapshot().forever_ragdolls&&!Snapshot(1).forever_ragdolls);
 CHECK(Snapshot().fov_percent==100&&Snapshot(1).fov_percent==130);
 HANDLE held=CreateFileW(L"view.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
 CHECK(held!=INVALID_HANDLE_VALUE);CHECK(!app::Save()&&Read()==saved);CloseHandle(held);
 CHECK(app::Save());Apply({});app::Load();CHECK(!Snapshot().forever_ragdolls&&!Snapshot(1).forever_ragdolls);
 for(bool fps:{false,true})for(bool hd:{false,true})for(bool borders:{false,true})for(bool textures:{false,true})for(bool bodies:{false,true}){
  Apply({120,80,fps,hd,110,borders,textures,bodies},1);const auto s=Snapshot();
  CHECK(s.show_fps==fps&&s.hd_ui==hd&&s.cutscene_borders==borders&&s.hd_textures==textures&&s.forever_ragdolls==bodies);
  CHECK(Snapshot(1).forever_ragdolls==bodies&&Snapshot(1).fov_percent==120);
 }
 std::puts("forever ragdolls: default off, strict booleans, shared flag, persistence, atomic failure and no flag collisions passed");
}
''')

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
