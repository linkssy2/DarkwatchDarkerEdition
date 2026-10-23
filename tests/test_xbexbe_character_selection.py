"""Actual character settings and clickable themed page, without launching the game."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import test_xbexbe_graphics_ui as graphics_ui

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"

SETTINGS = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <atomic>
#include <cassert>
#include <fstream>
#include <thread>
#include "app/app.h"
#include "core/log.h"
#include "common/character_selection.h"
const app::GameInfo app::kGame={.settings="settings.toml",.load=darkwatch::settings::LoadCharacters,.save=darkwatch::settings::SaveCharacters};
std::filesystem::path app::ExeDir(){return std::filesystem::current_path();}
void* app::Window(){return nullptr;}
void logx::Write(Level,const char*,...){}
void Write(const char* s){std::ofstream f("settings.toml");f<<s;assert(f);}
std::string Read(){std::ifstream f("settings.toml");return {std::istreambuf_iterator<char>(f),{}};}
int main(){
 using namespace darkwatch::settings;
 constexpr auto J=Character::Jericho,C=Character::Cassidy,S=Character::SpectralCassidy;
 static_assert(int(J)==0&&int(C)==1&&int(S)==2);
 app::Load();assert((characters()==std::array{J,J}));
 assert(configured_character(0)==J&&configured_character(1)==J&&configured_character(2)==J&&configured_character(~0u)==J);
 for(auto p1:{J,C,S})for(auto p2:{J,C,S}){
  const std::array expected{p1,p2};assert(set_characters(expected)&&app::Save());
  assert(set_characters({J,J}));app::Load();assert(characters()==expected);
  assert(configured_character(0)==p1&&configured_character(1)==p2);
 }
 assert(set_characters({C,J}));assert(!set_characters({Character(-1),C})&&(characters()==std::array{C,J}));
 assert(!set_characters({J,Character(3)})&&(characters()==std::array{C,J}));
 Write("player_one_character='Cassidy'\n");app::Load();assert((characters()==std::array{C,J}));
 Write("player_two_character='Cassidy'\n");app::Load();assert((characters()==std::array{J,C}));
 Write("player_one_character='Spectral Cassidy'\n");app::Load();assert((characters()==std::array{S,J}));
 Write("player_two_character='Spectral Cassidy'\n");app::Load();assert((characters()==std::array{J,S}));
 assert(app::Save()&&Read().find("Spectral Cassidy")!=std::string::npos);
 for(const char* s:{"[malformed", "player_one_character=1\nplayer_two_character=false\n", "player_one_character='cassidy'\nplayer_two_character='Tala'\n", "player_one_character=['Cassidy']\nplayer_two_character={}\n", "player_one_character='spectral cassidy'\nplayer_two_character='SpectralCassidy'\n"}){
  assert(set_characters({C,C}));Write(s);app::Load();assert((characters()==std::array{J,J}));
 }
 assert(set_characters({J,S})&&app::Save());const auto saved=Read();
 HANDLE held=CreateFileW(L"settings.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);assert(held!=INVALID_HANDLE_VALUE);
 assert(set_characters({C,J})&&!app::Save()&&Read()==saved);CloseHandle(held);
 assert((characters()==std::array{C,J}));app::Load();assert((characters()==std::array{J,S}));
 const std::array a{J,S},b{S,C};assert(set_characters(a));std::atomic<bool> done=false;
 std::thread writer([&]{for(unsigned i=0;i<10000;++i)assert(set_characters(i&1?a:b));done=true;});
 do{const auto value=characters();assert(value==a||value==b);}while(!done);writer.join();
 std::puts("character settings: original defaults/tokens, all nine pairs, spectral persistence, invalid values, failed atomic save and coherent snapshots passed");
}
'''

CHARACTERS_UI = r'''
int main(){
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
 io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad;
 ImFontConfig font;font.SizePixels=22;g_body=io.Fonts->AddFontDefault(&font);g_title=g_body;
 unsigned char* pixels;int w,h;io.Fonts->GetTexDataAsRGBA32(&pixels,&w,&h);
 using namespace darkwatch::settings;constexpr auto J=Character::Jericho,C=Character::Cassidy,S=Character::SpectralCassidy;
 route={};darkwatch::character_owner=0x123400;Frame();CHECK(!g_open);
 DarkwatchCharactersOpen(0);Poll();Frame();CHECK(!g_open);
 DarkwatchCharactersOpen(darkwatch::character_owner);
 auto p=Poll(0,255);Frame();CHECK(g_open&&g_characters&&DarkwatchGraphicsVisible()&&!p.analog[0]&&!g_pad);
 for(unsigned held=0;held<4;++held){Poll(0,255);Frame();CHECK(g_open&&!g_pad);}
 Poll();Frame();CHECK(g_released);
 CHECK(std::find(rendered_text.begin(),rendered_text.end(),"CHARACTERS")!=rendered_text.end());
 CHECK(std::find(rendered_text.begin(),rendered_text.end(),"Changes take effect when you start your next mission.")!=rendered_text.end());
 CHECK(std::find(rendered_text.begin(),rendered_text.end(),"Spectral Cassidy is available from the start.\nCassidy follows the story for player two.")!=rendered_text.end());
 CHECK((characters()==std::array{J,J}));
 constexpr const char* labels[]{"Jericho","Cassidy","Spectral Cassidy"};
 for(int one=0;one<3;++one)for(int two=0;two<3;++two){
  auto previous=characters();const auto saved=saves;
  SelectQuality("##player one character",one,labels[one]);
  CHECK(characters()==previous&&g_character_draft[0]==Character(one));
  SelectQuality("##player two character",two,labels[two]);
  CHECK(characters()==previous&&g_character_draft[1]==Character(two));
  ClickNamed("APPLY");CHECK((characters()==std::array{Character(one),Character(two)})&&saves==saved+1);
  CHECK(g_open&&g_characters&&!g_leave);
 }
 SelectQuality("##player one character",0,"Jericho");ClickNamed("BACK");
 CHECK(!g_open&&!DarkwatchGraphicsVisible()&&!g_leave&&(characters()==std::array{S,S}));
 p=Poll(0,0,255);CHECK(!p.analog[1]&&g_block_release);Poll();Frame();CHECK(!g_block_release);
 for(unsigned exit=0;exit<3;++exit){
  DarkwatchCharactersOpen(darkwatch::character_owner);Poll();Frame();Poll();Frame();
  CHECK((g_character_draft==std::array{S,S}));SelectQuality("##player two character",0,"Jericho");
  if(exit==0){io.AddKeyEvent(ImGuiKey_Escape,true);Frame();io.AddKeyEvent(ImGuiKey_Escape,false);Frame();}
  if(exit==1){io.AddMouseButtonEvent(1,true);Frame();Frame();Frame();io.AddMouseButtonEvent(1,false);Frame();}
  if(exit==2){Poll(0,0,255);Frame();Frame();Frame();}
  CHECK(!g_open&&!g_leave&&(characters()==std::array{S,S}));Poll();Frame();Frame();
 }
 DarkwatchCharactersOpen(darkwatch::character_owner);Poll();Frame();Poll();Frame();save_ok=false;
 SelectQuality("##player one character",0,"Jericho");ClickNamed("APPLY");
 CHECK((characters()==std::array{J,S})&&std::string(g_notice).find("session only")!=std::string::npos);
 // Replacing the original owner cancels the page and discards its unsaved draft.
 SelectQuality("##player two character",0,"Jericho");darkwatch::character_owner+=4;
 Poll();Frame();CHECK(!g_open&&!DarkwatchGraphicsVisible()&&!g_leave&&(characters()==std::array{J,S}));
 Poll();Frame();DarkwatchCharactersOpen(darkwatch::character_owner);Poll();Frame();CHECK((g_character_draft==std::array{J,S}));
 darkwatch::character_owner=0;Poll();Frame();CHECK(!g_open&&!DarkwatchGraphicsVisible());
 // Fallback feedback draws without opening a menu or consuming game input, then expires.
 unavailable_characters=0;Frame();const auto baseline=ImGui::GetForegroundDrawList()->VtxBuffer.Size;
 for(unsigned players:{1u,2u,3u}){
  unavailable_characters=players;Frame();CHECK(ImGui::GetForegroundDrawList()->VtxBuffer.Size>baseline);
  CHECK(!g_open&&!DarkwatchGraphicsVisible());Frame(13);
  CHECK(ImGui::GetForegroundDrawList()->VtxBuffer.Size==baseline);
 }
 unavailable_characters=0;Frame();CHECK(ImGui::GetForegroundDrawList()->VtxBuffer.Size==baseline);
 ImGui::DestroyContext();std::puts("actual Characters ImGui: both third choices/all nine pairs, draft Apply/Back, controller opening hold, keyboard/mouse/pad exit, save failure and stale owner passed");
}
'''


class CharacterSelectionTests(unittest.TestCase):
    run_fixture = graphics_ui.GraphicsUiTests.run_fixture

    def test_settings(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        with tempfile.TemporaryDirectory(prefix="character-settings-", dir=ROOT / "build") as tmp:
            folder = Path(tmp)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(SETTINGS)
            built = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK),
                "-I", str(ROOT / "xbexbe/src"), "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"),
                str(source), str(SDK / "app/settings.cpp"), str(ROOT / "xbexbe/src/common/character_selection.cpp"),
                "-luser32", "-o", str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=20)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            print(ran.stdout.strip())

    def test_actual_character_page(self):
        ran = self.run_fixture(graphics_ui.FIXTURE.split("int main(){", 1)[0] + CHARACTERS_UI)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


if __name__ == "__main__":
    unittest.main()
