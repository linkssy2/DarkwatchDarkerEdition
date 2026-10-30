"""Actual Controls persistence/capture and input integration, with controlled SDL."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_xbexbe_native_input import SDL

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
#include <thread>
#include <toml++/toml.hpp>
#include "app/app.h"
#include "core/log.h"
#include "common/controls.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
const app::GameInfo app::kGame={.settings="settings.toml",.load=darkwatch::ControlsLoad,.save=darkwatch::ControlsSave,.message=darkwatch::ControlsMessage};
std::filesystem::path app::ExeDir(){return std::filesystem::current_path();}
void* app::Window(){return nullptr;}
void logx::Write(Level,const char*,...){}
static void Write(const char* text){std::ofstream f("settings.toml");f<<text;CHECK(bool(f));}
static std::string Read(){std::ifstream f("settings.toml");return {std::istreambuf_iterator<char>(f),{}};}
static uint32_t Capture(uint32_t msg,uintptr_t wp=0,intptr_t lp=0){intptr_t result=-99;CHECK(darkwatch::ControlsMessage(nullptr,msg,wp,lp,&result));return darkwatch::ControlsTakeCapture();}
int main(){
 using namespace darkwatch;using input::PcAction;
 constexpr auto fire=size_t(PcAction::RightTrigger),forward=size_t(PcAction::MoveForward);
 input::Init();input::SetActive(true);app::Load();auto defaults=ControlsSnapshot();
 CHECK(defaults.zoom_sensitivity_percent==100);
 CHECK(defaults.aim_assistance&&defaults.aim_centering&&defaults.mouse_millidegrees==50);
 CHECK(defaults.bindings[size_t(PcAction::Start)].keys[0]==VK_ESCAPE&&defaults.bindings[size_t(PcAction::Start)].keys[1]==VK_RETURN);
 CHECK(defaults.bindings[size_t(PcAction::B)].keys[0]=='B');
 input::Key(VK_ESCAPE,true);input::AdvanceFrame(80000);CHECK((input::Poll(0).buttons&0x10)&&!input::Poll(0).analog[1]);
 input::Key(VK_ESCAPE,false);input::AdvanceFrame(90000);
 // Legacy scalar settings load without a new bindings table.
 Write("direct_mouse=false\nmouse_millidegrees_per_count=75\n");app::Load();
 input::Mouse(8,-4);input::AdvanceFrame(16667);CHECK(!input::Poll(0).rx&&!input::Poll(0).ry);
 auto s=ControlsSnapshot();CHECK(s.mouse_millidegrees==75&&s.bindings[fire].keys[0]==VK_LBUTTON);
 CHECK(s.zoom_sensitivity_percent==100);s.zoom_sensitivity_percent=35;
 s.aim_assistance=false;s.aim_centering=false;s.mouse_millidegrees=87;
 s.bindings[fire].keys[0]='P';s.bindings[fire].keys[1]=VK_XBUTTON1;
 s.bindings[forward].keys[0]='I';CHECK(ControlsApply(s));
 auto epoch=input::GetMouseSnapshot().active_epoch;
 input::Key('I',true);input::AdvanceFrame(100000);CHECK(input::Poll(0).ly==32767);
 CHECK(ControlsApply(s));CHECK(input::GetMouseSnapshot().active_epoch>epoch&&!input::Poll(0).ly);
 input::Key(VK_LBUTTON,true);input::AdvanceFrame(120000);CHECK(!input::Poll(0).analog[7]);
 input::Key('P',true);input::Key('P',false);input::AdvanceFrame(140000);CHECK(input::Poll(0).analog[7]==255);
 input::AdvanceFrame(160000);CHECK(!input::Poll(0).analog[7]);
 auto graphics=app::Snapshot();graphics.width=2560;graphics.height=1440;graphics.aspect_ratio=app::AspectRatio::Wide16x9;app::Apply(graphics);
 CHECK(app::Save());auto saved=Read();CHECK(saved.find("direct_mouse")==std::string::npos);CHECK(saved.find("key_bindings")!=std::string::npos);
 CHECK(ControlsApply(defaults));app::Load();auto restored=ControlsSnapshot();
 CHECK(restored.zoom_sensitivity_percent==35);
 CHECK(!restored.aim_assistance&&!restored.aim_centering&&restored.mouse_millidegrees==87);
 CHECK(restored.bindings[fire].keys[0]=='P'&&restored.bindings[fire].keys[1]==VK_XBUTTON1&&restored.bindings[forward].keys[0]=='I');
 CHECK(app::Snapshot().width==2560&&app::Snapshot().height==1440);
 // Switch Weapons retains the existing primary/alternate slots without migrating saved bindings.
 {
  constexpr auto down=size_t(PcAction::DpadDown),y=size_t(PcAction::Y);
  Write("mouse_millidegrees_per_count=87\naim_assistance=false\n[key_bindings]\ndpad_down=[49,0]\nright_trigger=[80,5]\nmove_forward=[73,0]\n");
  app::Load();auto legacy=ControlsSnapshot();
  CHECK(legacy.bindings[down].keys[0]=='1'&&!legacy.bindings[down].keys[1]);
  CHECK(legacy.bindings[fire].keys[0]=='P'&&legacy.bindings[fire].keys[1]==VK_XBUTTON1&&legacy.bindings[forward].keys[0]=='I');
  auto cycle=legacy;cycle.bindings[down].keys[1]='2';CHECK(ControlsApply(cycle)&&app::Save());
  CHECK(ControlsApply(defaults));app::Load();auto reloaded=ControlsSnapshot();
  for(size_t action=0;action<legacy.bindings.size();++action)for(size_t slot=0;slot<2;++slot)
   CHECK(reloaded.bindings[action].keys[slot]==(action==down&&slot==1?'2':legacy.bindings[action].keys[slot]));
  CHECK(reloaded.mouse_millidegrees==87&&!reloaded.aim_assistance);
  // Chieftain's cycle action uses Y, whose slots retain the same persistence contract.
  cycle=reloaded;cycle.bindings[y]={{'3','4'}};CHECK(ControlsApply(cycle)&&app::Save());
  CHECK(ControlsApply(defaults));app::Load();reloaded=ControlsSnapshot();
  for(size_t action=0;action<cycle.bindings.size();++action)for(size_t slot=0;slot<2;++slot)
   CHECK(reloaded.bindings[action].keys[slot]==cycle.bindings[action].keys[slot]);
  uint64_t frame=200000;
  for(uint32_t key:{uint32_t('1'),uint32_t('2'),uint32_t('3'),uint32_t('4')}){
   input::Key(key,true);input::Key(key,false);input::AdvanceFrame(frame+=16667);
   for(unsigned query=0;query<8;++query){const auto pad=input::Poll(0);
    CHECK(pad.buttons==(key<='2'?2:0)&&pad.analog[3]==(key>='3'?255:0));}
   CHECK(!input::Poll(1).buttons&&!input::Poll(1).analog[3]);
   input::AdvanceFrame(frame+=16667);CHECK(!input::Poll(0).buttons&&!input::Poll(0).analog[3]);
  }
  input::Key('2',true);input::Key('2',false);input::SetActive(false);input::SetActive(true);
  input::AdvanceFrame(frame+=16667);CHECK(!input::Poll(0).buttons);
  CHECK(ControlsApply(restored));
 }
 // Either scroll direction persists as one binding and lasts beyond the original 0.1s gate.
 {
  constexpr auto down=size_t(PcAction::DpadDown);
  auto wheel=restored;wheel.bindings[down]={{'1',input::kMouseWheel}};
  CHECK(ControlsApply(wheel)&&app::Save());CHECK(ControlsApply(defaults));app::Load();
  auto loaded=ControlsSnapshot();
  for(size_t action=0;action<wheel.bindings.size();++action)for(size_t slot=0;slot<2;++slot)
   CHECK(loaded.bindings[action].keys[slot]==wheel.bindings[action].keys[slot]);
  auto conflict=wheel;conflict.bindings[fire].keys[1]=input::kMouseWheel;
  CHECK(!ControlsApply(conflict)&&ControlsSnapshot().bindings[down].keys[1]==input::kMouseWheel);
  uint64_t now=1000000;
  for(int delta:{120,-120}){
   CHECK(ControlsApply(wheel));input::SetActive(true);input::Wheel(delta);input::AdvanceFrame(now);
   CHECK(input::Poll(0).buttons==2&&!input::Poll(1).buttons);
   input::AdvanceFrame(now+100001);
   for(int query=0;query<8;++query)CHECK(input::Poll(0).buttons==2);
   input::AdvanceFrame(now+150001);CHECK(!input::Poll(0).buttons);now+=200000;
  }
  CHECK(ControlsApply(restored));
 }

 // Carry-all is opt-in and controller cycle overrides are independent per player.
 {
  auto extra=restored;CHECK(!extra.carry_all_weapons&&!GetCarryAllWeapons());
  extra.carry_all_weapons=true;extra.weapon_buttons[0]={2,3};extra.weapon_buttons[1]={12,13};
  extra.bindings[size_t(PcAction::NextWeapon)]={{input::kMouseWheelUp,0}};
  extra.bindings[size_t(PcAction::PreviousWeapon)]={{input::kMouseWheelDown,0}};
  CHECK(ControlsApply(extra)&&GetCarryAllWeapons()&&app::Save());
  CHECK(ControlsApply(defaults));app::Load();auto saved_extra=ControlsSnapshot();
  CHECK(saved_extra.carry_all_weapons&&saved_extra.weapon_buttons==extra.weapon_buttons);
  for(int invalid:{-2,4,5,16}){auto bad=extra;bad.weapon_buttons[1][0]=invalid;CHECK(!ControlsApply(bad));}
  auto duplicate=extra;duplicate.weapon_buttons[0]={2,2};CHECK(!ControlsApply(duplicate));
  CHECK(ControlsSnapshot().weapon_buttons==extra.weapon_buttons);
  uint64_t now=3000000;
  for(int direction:{120,-120}) {
   CHECK(ControlsApply(extra));input::SetActive(true);input::Wheel(direction);input::AdvanceFrame(now+=100000);
   CHECK(input::PcActionDown(PcAction::NextWeapon)==(direction>0));
   CHECK(input::PcActionDown(PcAction::PreviousWeapon)==(direction<0));
   CHECK(!input::Poll(0).buttons);
   input::AdvanceFrame(now+=150001);CHECK(!input::PcActionDown(PcAction::NextWeapon)&&!input::PcActionDown(PcAction::PreviousWeapon));
  }
  auto collision=extra;collision.bindings[fire].keys[1]=input::kMouseWheel;CHECK(!ControlsApply(collision));
  input::Wheel(120);input::SetMenuMode(true);input::AdvanceFrame(now+=16667);
  CHECK(!input::PcActionDown(PcAction::NextWeapon));input::SetMenuMode(false);
  input::AdvanceFrame(now+=16667);CHECK(!input::PcActionDown(PcAction::NextWeapon));
  input::Wheel(-120);input::SetActive(false);input::SetActive(true);input::AdvanceFrame(now+=16667);
  CHECK(!input::PcActionDown(PcAction::PreviousWeapon));
  // An existing custom bracket assignment remains intact instead of resetting every key.
  Write("[key_bindings]\nright_trigger=[221,0]\n");app::Load();
  CHECK(ControlsSnapshot().bindings[fire].keys[0]==221&&!ControlsSnapshot().bindings[size_t(PcAction::NextWeapon)].keys[0]);
  CHECK(ControlsApply(restored));
 }
 // Invalid live draft must leave both controls and actual input unchanged.
 s=restored;s.bindings[fire].keys[0]='I';CHECK(!ControlsApply(s));
 CHECK(ControlsSnapshot().bindings[fire].keys[0]=='P'&&input::GetPcBindings()[fire].keys[0]=='P');
 for(const char* bad:{"[malformed", "[key_bindings]\nright_trigger=[259,0]\n","[key_bindings]\nright_trigger=[112,0]\n","[key_bindings]\nright_trigger=[87,0]\n","[key_bindings]\nright_trigger=[1]\n","[key_bindings]\nright_trigger=['P',0]\n","key_bindings=3\n"}){
   Write(bad);app::Load();auto value=ControlsSnapshot();CHECK(value.bindings[fire].keys[0]==VK_LBUTTON&&value.bindings[forward].keys[0]=='W');
 }
 Write("mouse_millidegrees_per_count=-7\naim_assistance=false\naim_centering=true\n");app::Load();CHECK(ControlsSnapshot().mouse_millidegrees==1&&!ControlsSnapshot().aim_assistance&&ControlsSnapshot().aim_centering);
 Write("mouse_millidegrees_per_count=9000\n");app::Load();CHECK(ControlsSnapshot().mouse_millidegrees==1000);
 Write("zoom_sensitivity_percent=-1\n");app::Load();CHECK(ControlsSnapshot().zoom_sensitivity_percent==10);
 Write("zoom_sensitivity_percent=9999\n");app::Load();CHECK(ControlsSnapshot().zoom_sensitivity_percent==200);
 Write("zoom_sensitivity_percent='bad'\n");app::Load();CHECK(ControlsSnapshot().zoom_sensitivity_percent==100);
 auto zoom_limits=restored;zoom_limits.zoom_sensitivity_percent=0;CHECK(ControlsApply(zoom_limits)&&ControlsSnapshot().zoom_sensitivity_percent==10);
 zoom_limits.zoom_sensitivity_percent=9999;CHECK(ControlsApply(zoom_limits)&&ControlsSnapshot().zoom_sensitivity_percent==200);
 CHECK(ControlsApply(restored));CHECK(app::Save());saved=Read();
 HANDLE held=CreateFileW(L"settings.toml",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);CHECK(held!=INVALID_HANDLE_VALUE);
 CHECK(ControlsApply(defaults));CHECK(!app::Save()&&Read()==saved);CloseHandle(held);
 // Native capture consumes real buttons/keys, ignores repeats, and cancels on focus loss.
 CHECK(!ControlsCapturing());ControlsBeginCapture();CHECK(ControlsCapturing());
 CHECK(Capture(WM_KEYDOWN,'K',intptr_t(1)<<30)==0&&ControlsCapturing());
 CHECK(Capture(WM_KEYDOWN,VK_F1)==kCaptureReserved&&ControlsCapturing());
 CHECK(Capture(WM_KEYDOWN,VK_F3)==kCaptureReserved&&ControlsCapturing());
 CHECK(Capture(WM_KEYDOWN,'K')=='K'&&!ControlsCapturing()&&ControlsTakeCapture()==0);
 ControlsBeginCapture();CHECK(Capture(WM_KEYDOWN,VK_ESCAPE)==kCaptureCancelled&&!ControlsCapturing());
 ControlsBeginCapture();CHECK(Capture(WM_KEYDOWN,VK_BACK)==kCaptureClear&&!ControlsCapturing());
 ControlsBeginCapture();CHECK(Capture(WM_LBUTTONDOWN)==VK_LBUTTON);
 ControlsBeginCapture();CHECK(Capture(WM_RBUTTONDOWN)==VK_RBUTTON);
 ControlsBeginCapture();CHECK(Capture(WM_MBUTTONDOWN)==VK_MBUTTON);
 ControlsBeginCapture();CHECK(Capture(WM_XBUTTONDOWN,uintptr_t(XBUTTON1)<<16)==VK_XBUTTON1);
 ControlsBeginCapture();CHECK(Capture(WM_XBUTTONDOWN,uintptr_t(XBUTTON2)<<16)==VK_XBUTTON2);
 for(int delta:{120,-120,30,-30}){
  ControlsBeginCapture();CHECK(Capture(WM_MOUSEWHEEL,uintptr_t(uint16_t(delta))<<16)==(delta>0?input::kMouseWheelUp:input::kMouseWheelDown)&&!ControlsCapturing());
 }
 ControlsBeginCapture();CHECK(Capture(WM_MOUSEWHEEL,0)==0&&ControlsCapturing());
 CHECK(Capture(WM_KEYDOWN,VK_ESCAPE)==kCaptureCancelled);
 ControlsBeginCapture();intptr_t result=0;CHECK(!ControlsMessage(nullptr,WM_KILLFOCUS,0,0,&result));CHECK(ControlsTakeCapture()==kCaptureCancelled&&!ControlsCapturing());
 ControlsBeginCapture();ControlsCancelCapture();CHECK(!ControlsCapturing()&&ControlsTakeCapture()==0);
 CHECK(ControlsKeyName(0)=="Unbound"&&ControlsKeyName(VK_XBUTTON2)=="Mouse 5"&&ControlsKeyName(input::kMouseWheel)=="Mouse Wheel"&&!ControlsKeyName('K').empty());
 // Settings readers cannot observe half an Apply, including bindings and aim flags.
 auto a=defaults,b=restored;CHECK(ControlsApply(a));std::atomic<bool> done=false;
 std::thread writer([&]{for(int i=0;i<4000;++i)CHECK(ControlsApply(i&1?a:b));done=true;});
 do{auto v=ControlsSnapshot();CHECK((v.aim_assistance&&v.mouse_millidegrees==50&&v.bindings[fire].keys[0]==VK_LBUTTON)||(!v.aim_assistance&&v.mouse_millidegrees==87&&v.bindings[fire].keys[0]=='P'));}while(!done);writer.join();
 std::puts("actual Controls: TOML roundtrip, legacy weapon-slot preservation and frame-latched aliases, invalid/conflicting bindings, atomic-save failure, raw capture, live input and coherent snapshots passed");
}
'''


class ControlsSettingsTests(unittest.TestCase):
    def test_actual_persistence_capture_and_input(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        with tempfile.TemporaryDirectory(prefix="controls-settings-", dir=ROOT / "build") as tmp:
            folder = Path(tmp)
            (folder / "SDL3").mkdir()
            (folder / "SDL3/SDL.h").write_text(SDL, encoding="utf-8")
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(FIXTURE, encoding="utf-8")
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(folder), "-I", str(SDK),
                "-I", str(ROOT / "xbexbe/src"), "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"),
                str(source), str(SDK / "core/input.cpp"), str(SDK / "app/settings.cpp"), str(ROOT / "xbexbe/src/common/controls.cpp"),
                "-luser32", "-o", str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
