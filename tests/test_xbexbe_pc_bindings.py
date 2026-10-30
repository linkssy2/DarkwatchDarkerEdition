"""Editable bindings through the real input mapper and native mouse message bridge."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_xbexbe_native_input import SDL

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"

FIXTURE = r'''
#include <atomic>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include "core/input.cpp"
#define CHECK(x) do { if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);} } while(0)
const app::GameInfo app::kGame={};
void logx::Write(Level,const char*,...){}
using namespace input;
static uint64_t clock_us=100000;
static void Frame(uint64_t elapsed=16667){AdvanceFrame(clock_us+=elapsed);}
static void Tap(uint32_t k){Key(k,true);Key(k,false);}
static PcBinding& At(PcBindings& b,PcAction a){return b[unsigned(a)];}
static bool Same(const PcBindings& a,const PcBindings& b){
 for(unsigned i=0;i<a.size();++i)for(unsigned j=0;j<2;++j)if(a[i].keys[j]!=b[i].keys[j])return false;
 return true;
}
static void Equal(const Pad& a,const Pad& b){
 CHECK(a.connected==b.connected&&a.buttons==b.buttons&&a.lx==b.lx&&a.ly==b.ly&&a.rx==b.rx&&a.ry==b.ry);
 for(unsigned i=0;i<8;++i)CHECK(a.analog[i]==b.analog[i]);
}
enum {WM_LBUTTONDOWN=0x201,WM_LBUTTONUP=0x202,WM_RBUTTONDOWN=0x204,WM_RBUTTONUP=0x205,
 WM_MBUTTONDOWN=0x207,WM_MBUTTONUP=0x208,WM_XBUTTONDOWN=0x20B,WM_XBUTTONUP=0x20C,WM_MOUSEWHEEL=0x20A,
 VK_LBUTTON=1,VK_RBUTTON=2,VK_MBUTTON=4,VK_XBUTTON1=5,VK_XBUTTON2=6,XBUTTON1=1,XBUTTON2=2};
static unsigned HIWORD(uintptr_t p){return unsigned((p>>16)&0xFFFF);}
static void NativeMouse(unsigned msg,uintptr_t wp){ NATIVE_MOUSE_BRIDGE }
int main(){
 Init();SetActive(true);Frame();
 auto defaults=DefaultPcBindings();CHECK(defaults.size()==22&&Same(defaults,GetPcBindings()));
 CHECK(At(defaults,PcAction::A).keys[0]==0x20&&At(defaults,PcAction::A).keys[1]=='E');
 auto copy=GetPcBindings();At(copy,PcAction::A).keys[0]='Z';CHECK(Same(GetPcBindings(),defaults));
 Tap(0x20);Frame();CHECK(Poll(0).analog[0]==255);Frame();Tap('E');Frame();CHECK(Poll(0).analog[0]==255);
 // Successful replacement drops held, pressed and published keys plus mouse motion.
 auto changed=defaults;At(changed,PcAction::A)={{'Z','V'}};At(changed,PcAction::MoveForward)={{'I',0}};
 Key('W',true);Key('E',true);Mouse(9,-8);Frame();Tap('Q');Mouse(7,6);
 const auto before=GetMouseSnapshot();CHECK(before.dx==9&&Poll(0).ly==32767);
 CHECK(SetPcBindings(changed));CHECK(Same(GetPcBindings(),changed));
 auto raw=GetMouseSnapshot();CHECK(raw.active_epoch!=before.active_epoch&&raw.active&&!raw.dx&&!raw.dy);
 CHECK(!raw.accumulated_x&&!raw.accumulated_y&&!Poll(0).analog[0]&&!Poll(0).ly&&!Poll(0).rx);
 Frame();CHECK(!Poll(0).analog[3]&&!GetMouseSnapshot().dx); // old queued Q/mouse were discarded
 Tap(0x20);Tap('E');Tap('W');Frame();CHECK(!Poll(0).analog[0]&&!Poll(0).ly);
 Tap('Z');Frame();Pad pulse=Poll(0);CHECK(pulse.analog[0]==255);
 for(unsigned n=0;n<16;++n)Equal(Poll(0),pulse);Frame();CHECK(!Poll(0).analog[0]);
 Key('V',true);Frame();Frame();CHECK(Poll(0).analog[0]==255);Key('V',false);Frame();CHECK(!Poll(0).analog[0]);
 // Invalid maps do not clamp, partially apply, clear held keys, or change mouse epochs.
 Key('Z',true);Frame();const auto epoch=GetMouseSnapshot().active_epoch;
 for(uint32_t bad:{259u,UINT32_MAX,0x70u,0x72u}){
  auto invalid=changed;At(invalid,PcAction::A).keys[0]='N';At(invalid,PcAction::MoveRight).keys[0]=bad;
  CHECK(!SetPcBindings(invalid));CHECK(Same(GetPcBindings(),changed));
  CHECK(GetMouseSnapshot().active_epoch==epoch&&Poll(0).analog[0]==255);
 }
 auto conflict=changed;At(conflict,PcAction::X).keys[1]='Z';CHECK(!SetPcBindings(conflict));
 CHECK(Same(GetPcBindings(),changed)&&GetMouseSnapshot().active_epoch==epoch);
 // Same-action aliases are harmless; zero never selects key-state slot zero.
 auto empty=changed;At(empty,PcAction::A)={{0,0}};CHECK(SetPcBindings(empty));
 Tap('Z');Tap('V');Tap(0);Frame();CHECK(!Poll(0).analog[0]);
 auto edge=empty;At(edge,PcAction::A)={{255,255}};CHECK(SetPcBindings(edge));Tap(255);Frame();CHECK(Poll(0).analog[0]==255);
 // All digital and analog slots are editable through the actual report merger.
 PcBindings unique{};for(unsigned i=0;i<20;++i)unique[i].keys[0]=0x90+i;CHECK(SetPcBindings(unique));
 for(unsigned i=0;i<16;++i){Tap(0x90+i);Frame();Pad p=Poll(0);if(i<8)CHECK(p.buttons==(1u<<i));else CHECK(p.analog[i-8]==255);Frame();}
 // Remapped movement keeps diagonal normalization and opposing-key cancellation.
 auto movement=defaults;At(movement,PcAction::MoveForward)={{'I',0}};At(movement,PcAction::MoveBackward)={{'K',0}};
 At(movement,PcAction::MoveLeft)={{'J',0}};At(movement,PcAction::MoveRight)={{'L',0}};CHECK(SetPcBindings(movement));
 Tap('W');Frame();CHECK(!Poll(0).ly);Key('I',true);Frame();CHECK(Poll(0).ly==32767);
 Key('J',true);Frame();CHECK(Poll(0).lx==-23170&&Poll(0).ly==23170);
 Key('L',true);Frame();CHECK(Poll(0).lx==0&&Poll(0).ly==32767);
 Key('K',true);Frame();CHECK(!Poll(0).lx&&!Poll(0).ly);
 Key('I',false);Key('L',false);Frame();CHECK(Poll(0).lx==-23170&&Poll(0).ly==-23170);
 SetActive(false);SetActive(true);Frame();CHECK(!Poll(0).lx&&!Poll(0).ly);
 // Native middle and extra mouse messages reach the selected actions, including releases.
 auto mouse=defaults;At(mouse,PcAction::Y)={{4,0}};At(mouse,PcAction::Black)={{5,0}};At(mouse,PcAction::White)={{6,0}};
 CHECK(SetPcBindings(mouse));
 const unsigned down[]={WM_MBUTTONDOWN,WM_XBUTTONDOWN,WM_XBUTTONDOWN};
 const unsigned up[]={WM_MBUTTONUP,WM_XBUTTONUP,WM_XBUTTONUP};
 const uintptr_t wp[]={0,uintptr_t(XBUTTON1)<<16,uintptr_t(XBUTTON2)<<16};
 for(unsigned i=0;i<3;++i){NativeMouse(down[i],wp[i]);NativeMouse(up[i],wp[i]);Frame();CHECK(Poll(0).analog[3+i]==255);Frame();CHECK(!Poll(0).analog[3+i]);}
 SetActive(false);NativeMouse(WM_XBUTTONDOWN,uintptr_t(XBUTTON1)<<16);SetActive(true);Frame();CHECK(!Poll(0).analog[4]);
 // One wheel binding accepts either direction and is not a Windows key-state index.
 auto wheel=defaults;At(wheel,PcAction::DpadDown)={{0x28,kMouseWheel}};
 SetWheelPulseDuration(150000);CHECK(SetPcBindings(wheel));
 auto duplicate=wheel;At(duplicate,PcAction::X).keys[1]=kMouseWheel;CHECK(!SetPcBindings(duplicate)&&Same(GetPcBindings(),wheel));
 Tap(kMouseWheel);Frame();CHECK(!Poll(0).buttons);
 Wheel(30);Wheel(-30);Wheel(59);Frame();CHECK(!Poll(0).buttons);
 Wheel(-1);CHECK(!Poll(0).buttons);Frame();CHECK(Poll(0).buttons==2);
 for(unsigned i=0;i<16;++i)CHECK(Poll(0).buttons==2&&!Poll(1).buttons);
 // Original switchprimary requires AfterDuration=0.1 seconds; the title's 150ms
 // pulse remains held past that threshold, unlike a single 60Hz frame.
 Frame(100001);CHECK(Poll(0).buttons==2);
 SetWheelPulseDuration(150000);CHECK(Poll(0).buttons==2); // unchanged configuration preserves the current pulse
 Frame(49999);CHECK(!Poll(0).buttons);Frame();CHECK(!Poll(0).buttons);
 // The actual WM_MOUSEWHEEL bridge preserves signed high-word deltas.
 for(int16_t delta:{int16_t(120),int16_t(-120)}){
  NativeMouse(WM_MOUSEWHEEL,uintptr_t(uint16_t(delta))<<16);Frame();CHECK(Poll(0).buttons==2);
  Frame(150000);CHECK(!Poll(0).buttons);Frame();CHECK(!Poll(0).buttons);
 }
 // Bursts coalesce to current + one pending pulse, separated by a full release frame.
 Wheel(120);Frame();CHECK(Poll(0).buttons==2);
 for(unsigned i=0;i<100;++i)Wheel(i&1?INT32_MIN:INT32_MAX);
 Frame(150000);CHECK(!Poll(0).buttons);CHECK(!Poll(0).buttons);
 Frame();CHECK(Poll(0).buttons==2);Frame(150000);CHECK(!Poll(0).buttons);
 for(unsigned i=0;i<30;++i){Frame();CHECK(!Poll(0).buttons);}
 // Focus, host capture, rebind and timing gaps discard pending work and partial notches.
 Wheel(90);SetActive(false);Wheel(120);SetActive(true);Wheel(30);Frame();CHECK(!Poll(0).buttons);
 Wheel(90);Frame();CHECK(Poll(0).buttons==2);Wheel(120);CHECK(SetPcBindings(wheel));Frame();CHECK(!Poll(0).buttons);
 Wheel(120);Frame();CHECK(Poll(0).buttons==2);Wheel(120);Frame(250001);CHECK(!Poll(0).buttons);Frame();CHECK(!Poll(0).buttons);
 CHECK(SetPcBindings(defaults));Wheel(120);Frame();CHECK(!Poll(0).buttons);
 CHECK(SetPcBindings(wheel));Frame();CHECK(!Poll(0).buttons); // unbound scroll cannot survive a rebind
 SetWheelPulseDuration(0);Wheel(120);Frame();CHECK(Poll(0).buttons==2);Frame();CHECK(!Poll(0).buttons);
 Wheel(120);Frame();CHECK(Poll(0).buttons==2);Wheel(120);SetWheelPulseDuration(150000);Frame();CHECK(!Poll(0).buttons);
 auto wheel_y=defaults;At(wheel_y,PcAction::Y).keys[1]=kMouseWheel;CHECK(SetPcBindings(wheel_y));
 Wheel(-120);Frame();CHECK(!Poll(0).buttons&&Poll(0).analog[3]==255);
 Frame(150000);CHECK(!Poll(0).analog[3]); // Chieftain uses the same wheel pulse through its Y action.
 // Direction-specific wheel bindings must still satisfy original held-action gates.
 for(uint32_t wheel_key:{kMouseWheelUp,kMouseWheelDown}){
  auto directional=defaults;At(directional,PcAction::DpadDown).keys[1]=wheel_key;CHECK(SetPcBindings(directional));
  Wheel(wheel_key==kMouseWheelUp?120:-120);Frame();CHECK(Poll(0).buttons==2);
  Frame(100001);CHECK(Poll(0).buttons==2);Frame(49999);CHECK(!Poll(0).buttons);
  Wheel(wheel_key==kMouseWheelUp?-120:120);Frame();CHECK(!Poll(0).buttons);
 }
 CHECK(SetPcBindings(defaults));
 // No PC action preserves the physical pad exactly; mapped actions merge on port0 only.
 fake_init=true;fake_count=2;fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_BACK]=true;
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_LEFTX]=1234;fake_pads[0].axes[SDL_GAMEPAD_AXIS_LEFTY]=-2345;
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTX]=-3456;fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTY]=4567;
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_LEFT_TRIGGER]=8000;fake_pads[1]=fake_pads[0];fake_pads[1].id=2;
 Init();Frame();const Pad physical=Poll(0);Equal(Poll(1),physical);
 CHECK(SetPcBindings(changed));Equal(Poll(0),physical);Tap('Z');Frame();Pad merged=Poll(0);
 CHECK(merged.analog[0]==255&&merged.analog[6]==62&&merged.lx==physical.lx&&merged.ly==physical.ly&&merged.rx==physical.rx&&merged.ry==physical.ry&&merged.buttons==physical.buttons);
 Equal(Poll(1),physical);Frame();Equal(Poll(0),physical);
 Key('I',true);Frame();CHECK(Poll(0).lx==0&&Poll(0).ly==32767&&Poll(0).rx==physical.rx);
 CHECK(SetPcBindings(defaults));Equal(Poll(0),physical);CHECK(Same(GetPcBindings(),DefaultPcBindings()));
 CHECK(SetPcBindings(wheel));Wheel(-120);Frame();merged=Poll(0);
 CHECK(merged.buttons==(physical.buttons|2)&&merged.lx==physical.lx&&merged.ly==physical.ly&&merged.rx==physical.rx&&merged.ry==physical.ry);
 for(unsigned i=0;i<8;++i)CHECK(merged.analog[i]==physical.analog[i]);Equal(Poll(1),physical);
 CHECK(SetPcBindings(defaults));Equal(Poll(0),physical);
 // A reader sees one complete map while the UI repeatedly replaces it.
 PcBindings alternate=unique;for(unsigned i=0;i<20;++i)alternate[i].keys[0]=0xC0+i;
 CHECK(SetPcBindings(unique));std::atomic<bool> start=false;
 std::thread writer([&]{while(!start.load()){} for(unsigned i=0;i<2000;++i)CHECK(SetPcBindings(i&1?unique:alternate));});
 start=true;for(unsigned i=0;i<2000;++i){auto got=GetPcBindings();CHECK(Same(got,unique)||Same(got,alternate));Key(0x90,true);Frame();Poll(0);}writer.join();
 CHECK(SetPcBindings(defaults));Equal(Poll(0),physical);
 std::puts("actual editable bindings, aliases, bounded bidirectional wheel pulses/hold threshold/resets, movement, native mouse bridge and controller preservation passed");
}
'''


class PcBindingsTests(unittest.TestCase):
    def test_native_message_capture_precedes_input(self):
        window = (SDK / "app/main.cpp").read_text(encoding="utf-8")
        body = window[window.index("LRESULT CALLBACK WndProc("):]
        stages = ["ImGui_ImplWin32_WndProcHandler", "input::SetActive(false)", "else SyncInput(",
                  "kGame.message && kGame.message(", "wp == VK_F1", "input::Key(", "if (handled_ui)"]
        positions = [body.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(body.count("kGame.message && kGame.message("), 1)
        self.assertIn("kGame.message(hwnd, msg, wp, lp, &result)) return result;", body)
        self.assertLess(body.index("kGame.message && kGame.message("), body.index("input::Wheel("))

    def test_actual_mapping_and_native_mouse_bridge(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        window = (SDK / "app/main.cpp").read_text(encoding="utf-8")
        bridge = re.search(r"    if \(msg == WM_LBUTTONDOWN[^\n]*\) input::Key.*?(?=    if \(msg == WM_INPUT\))", window, re.S)
        self.assertIsNotNone(bridge)
        self.assertIn("VK_MBUTTON", bridge.group())
        self.assertIn("VK_XBUTTON1", bridge.group())
        self.assertIn("VK_XBUTTON2", bridge.group())
        self.assertIn("input::Wheel(int16_t(HIWORD(wp)))", bridge.group())
        with tempfile.TemporaryDirectory(prefix="xbexbe-pc-bindings-", dir=ROOT / "build") as tmp:
            folder = Path(tmp)
            (folder / "SDL3").mkdir()
            (folder / "SDL3/SDL.h").write_text(SDL, encoding="utf-8")
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(FIXTURE.replace("NATIVE_MOUSE_BRIDGE", bridge.group()), encoding="utf-8")
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(folder),
                                     "-I", str(SDK), str(source), "-o", str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("actual editable bindings", result.stdout)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
