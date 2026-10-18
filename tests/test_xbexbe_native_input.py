"""Exercise complete production input merging with controlled SDL devices and time."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"

SDL = r'''
#pragma once
#include <cstdint>
#include <cstdlib>
using SDL_JoystickID=uint32_t;
#define SDLCALL
enum SDL_LogPriority { SDL_LOG_PRIORITY_ERROR=5 };
enum SDL_HintPriority { SDL_HINT_OVERRIDE };
enum SDL_GamepadType { SDL_GAMEPAD_TYPE_UNKNOWN,SDL_GAMEPAD_TYPE_STANDARD,SDL_GAMEPAD_TYPE_XBOX360,
 SDL_GAMEPAD_TYPE_XBOXONE,SDL_GAMEPAD_TYPE_PS3,SDL_GAMEPAD_TYPE_PS4,SDL_GAMEPAD_TYPE_PS5,
 SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_PRO,SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT,
 SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT,SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_PAIR };
enum SDL_GamepadButton { SDL_GAMEPAD_BUTTON_DPAD_UP,SDL_GAMEPAD_BUTTON_DPAD_DOWN,SDL_GAMEPAD_BUTTON_DPAD_LEFT,
 SDL_GAMEPAD_BUTTON_DPAD_RIGHT,SDL_GAMEPAD_BUTTON_START,SDL_GAMEPAD_BUTTON_BACK,SDL_GAMEPAD_BUTTON_LEFT_STICK,
 SDL_GAMEPAD_BUTTON_RIGHT_STICK,SDL_GAMEPAD_BUTTON_SOUTH,SDL_GAMEPAD_BUTTON_EAST,SDL_GAMEPAD_BUTTON_WEST,
 SDL_GAMEPAD_BUTTON_NORTH,SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER };
enum SDL_GamepadAxis { SDL_GAMEPAD_AXIS_LEFT_TRIGGER,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,SDL_GAMEPAD_AXIS_LEFTX,
 SDL_GAMEPAD_AXIS_LEFTY,SDL_GAMEPAD_AXIS_RIGHTX,SDL_GAMEPAD_AXIS_RIGHTY };
struct SDL_Gamepad { SDL_JoystickID id; bool buttons[14]{}; int16_t axes[6]{}; SDL_GamepadType type=SDL_GAMEPAD_TYPE_UNKNOWN; };
struct SDL_Event { int type;struct{SDL_JoystickID which;}gdevice; };
inline SDL_Gamepad fake_pads[2]={{1},{2}};
inline int fake_count=0;
inline bool fake_init=false;
inline uint64_t fake_ticks=1;
enum { SDL_INIT_GAMEPAD,SDL_GETEVENT,SDL_EVENT_FIRST,SDL_EVENT_LAST,SDL_EVENT_GAMEPAD_ADDED,SDL_EVENT_GAMEPAD_REMOVED };
#define SDL_HINT_JOYSTICK_THREAD "thread"
#define SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS "background"
#define SDL_HINT_JOYSTICK_WGI "wgi"
#define SDL_HINT_JOYSTICK_RAWINPUT "raw"
#define SDL_HINT_XINPUT_ENABLED "xinput"
#define SDL_HINT_JOYSTICK_DIRECTINPUT "dinput"
#define SDL_HINT_LOGGING "logging"
#define SDL_VERSIONNUM_MAJOR(v) 3
#define SDL_VERSIONNUM_MINOR(v) 0
#define SDL_VERSIONNUM_MICRO(v) 0
inline void SDL_SetHint(const char*,const char*){}
inline bool SDL_SetHintWithPriority(const char*,const char*,SDL_HintPriority){return true;}
inline void SDL_SetLogOutputFunction(void(*)(void*,int,SDL_LogPriority,const char*),void*){}
inline bool SDL_Init(int){return fake_init;}
inline int SDL_GetVersion(){return 3;}
inline const char* SDL_GetError(){return "controlled SDL unavailable";}
inline SDL_JoystickID* SDL_GetGamepads(int* count){*count=fake_count;auto p=static_cast<SDL_JoystickID*>(std::malloc(8));p[0]=1;p[1]=2;return p;}
inline void SDL_free(void* p){std::free(p);}
inline SDL_Gamepad* SDL_OpenGamepad(SDL_JoystickID id){return &fake_pads[id-1];}
inline void SDL_CloseGamepad(SDL_Gamepad*){}
inline SDL_JoystickID SDL_GetGamepadID(SDL_Gamepad* p){return p->id;}
inline const char* SDL_GetGamepadName(SDL_Gamepad*){return "controlled pad";}
inline SDL_GamepadType SDL_GetGamepadType(SDL_Gamepad* p){return p->type;}
inline bool SDL_GamepadConnected(SDL_Gamepad* p){return p!=nullptr;}
inline bool SDL_GetGamepadButton(SDL_Gamepad* p,SDL_GamepadButton b){return p->buttons[b];}
inline int16_t SDL_GetGamepadAxis(SDL_Gamepad* p,SDL_GamepadAxis a){return p->axes[a];}
inline uint64_t SDL_GetTicks(){return fake_ticks;}
inline void SDL_PumpEvents(){}
inline int SDL_PeepEvents(SDL_Event*,int,int,int,int){return 0;}
inline void SDL_RumbleGamepad(SDL_Gamepad*,uint16_t,uint16_t,int){}
'''

FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include "core/input.cpp"
#define CHECK(x) do { if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);} } while(0)
const app::GameInfo app::kGame={};
void logx::Write(Level,const char*,...){}
using namespace input;
static uint64_t time_us=100000;
static void Frame(uint64_t elapsed=16667){time_us+=elapsed;AdvanceFrame(time_us);}
static void Equal(const Pad& a,const Pad& b){
 CHECK(a.connected==b.connected&&a.buttons==b.buttons&&a.lx==b.lx&&a.ly==b.ly&&a.rx==b.rx&&a.ry==b.ry);
 for(unsigned i=0;i<8;i++)CHECK(a.analog[i]==b.analog[i]);
}
static void Tap(uint32_t key){Key(key,true);Key(key,false);}
// Replaced by the unchanged production message-to-key clause before compilation.
NATIVE_KEY_BRIDGE
int main(){
 Init();SetActive(true); // A keyboard remains available when SDL cannot initialize.
 CHECK(Poll(0).connected&&!Poll(1).connected&&!Poll(-1).connected);
 Tap(0x0D);CHECK(!Poll(0).buttons);Frame();CHECK(Poll(0).buttons==0x10);
 Pad snapshot=Poll(0);for(int i=0;i<20;i++){Equal(Poll(0),snapshot);Poll(1);}
 AdvanceFrame(time_us);Equal(Poll(0),snapshot);Frame();CHECK(!Poll(0).buttons);
 // Every button uses the same frame latch, including pulses between arbitrary polls.
 const uint32_t keys[]={0x26,0x28,0x25,0x27,0x0D,0x09,'C','F',0x20,0x1B,'R','Q','G',0x10,0x02,0x01,'E'};
 for(unsigned i=0;i<std::size(keys);i++){
  Tap(keys[i]);Frame();Pad p=Poll(0);
  if(i<8)CHECK(p.buttons==(1u<<i));else CHECK(p.analog[i==16?0:i-8]==255);
  Frame();p=Poll(0);CHECK(!p.buttons);for(auto a:p.analog)CHECK(a==0);
 }
 Key('W',true);Frame();CHECK(Poll(0).ly==32767&&Poll(0).lx==0);
 Key('A',true);Frame();CHECK(Poll(0).ly==23170&&Poll(0).lx==-23170);
 Key('D',true);Frame();CHECK(Poll(0).ly==32767&&Poll(0).lx==0);
 Key('S',true);Frame();CHECK(Poll(0).ly==0&&Poll(0).lx==0);
 Key('W',false);Frame();CHECK(Poll(0).ly==-32767);
 Key('D',false);Frame();CHECK(Poll(0).lx==-23170&&Poll(0).ly==-23170);
 SetActive(false);CHECK(Poll(0).connected&&Poll(0).lx==0&&Poll(0).ly==0);
 Tap(0x0D);Mouse(99,99);SetActive(true);Frame();CHECK(!Poll(0).buttons&&!Poll(0).rx&&!Poll(0).ry);
 Key('W',true);Key('W',true);Frame();Frame();CHECK(Poll(0).ly==32767);
 Key('W',false);Frame();CHECK(Poll(0).ly==0);Key(UINT32_MAX,true);
 NativeKey(WM_KEYDOWN,'W');Frame();CHECK(Poll(0).ly==32767);
 NativeKey(WM_SYSKEYDOWN,0x12);NativeKey(WM_SYSKEYUP,'W');Frame();CHECK(Poll(0).ly==0);
 NativeKey(WM_SYSKEYDOWN,'W');Frame();CHECK(Poll(0).ly==32767);
 NativeKey(WM_KEYUP,'W');NativeKey(WM_SYSKEYUP,0x12);Frame();CHECK(Poll(0).ly==0);
 Mouse(2,3);Mouse(6,-7);Frame();snapshot=Poll(0);CHECK(snapshot.rx>8000&&snapshot.rx<8300&&snapshot.ry>4000&&snapshot.ry<4200);
 for(int i=0;i<20;i++)Equal(Poll(0),snapshot);
 Frame();CHECK(Poll(0).rx==0&&Poll(0).ry==0);
 Mouse(4,4);Frame(10000);snapshot=Poll(0);CHECK(snapshot.rx>0&&snapshot.ry<0);
 Mouse(8,8);Frame(20000);Equal(Poll(0),snapshot); // Velocity does not depend on the host frame period.
 for(int i=0;i<100;i++)Mouse(INT32_MAX,INT32_MIN);
 Frame();CHECK(Poll(0).rx==32767&&Poll(0).ry==32767);
 Frame();for(int i=0;i<100;i++)Mouse(INT32_MIN,INT32_MAX);
 Frame();CHECK(Poll(0).rx==-32768&&Poll(0).ry==-32768);
 Mouse(100,100);Frame(300000);CHECK(!Poll(0).rx&&!Poll(0).ry);
 Tap(0x20);Mouse(10,10);SetActive(false);SetActive(true);Frame();CHECK(!Poll(0).analog[0]&&!Poll(0).rx&&!Poll(0).ry);
 // Idle PC input must leave all physical button/axis values intact, on every port.
 fake_init=true;fake_count=2;fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_BACK]=true;
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_LEFTX]=1234;fake_pads[0].axes[SDL_GAMEPAD_AXIS_LEFTY]=-2345;
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTX]=-3456;fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTY]=4567;
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_LEFT_TRIGGER]=8000;
 fake_pads[1]=fake_pads[0];fake_pads[1].id=2;Init();Frame();snapshot=Poll(0);
 CHECK(snapshot.buttons==0x20&&snapshot.lx==1234&&snapshot.ly==2344&&snapshot.rx==-3456&&snapshot.ry==-4568&&snapshot.analog[6]==62);
 Equal(Poll(1),snapshot);Tap(0x20);Frame();Pad p=Poll(0);CHECK(p.analog[0]==255&&p.rx==snapshot.rx&&p.ly==snapshot.ly);
 Equal(Poll(1),snapshot);Frame();Equal(Poll(0),snapshot);
 Key('W',true);Mouse(8,-4);Frame();p=Poll(0);CHECK(p.ly==32767&&p.lx==0&&p.rx>8000&&p.ry>4000&&p.analog[6]==62);
 SetActive(false);Equal(Poll(0),snapshot);Equal(Poll(1),snapshot);
 // Raw counts are immutable once published. Direct mode changes only PC right-stick merging.
 SetMouseToStick(false);SetActive(true);Frame();
 auto raw=GetMouseSnapshot();CHECK(raw.active&&!raw.dx&&!raw.dy);
 uint64_t epoch=raw.active_epoch,generation=raw.generation;
 Mouse(12,-7);Mouse(-2,3);Tap('R');Frame();raw=GetMouseSnapshot();
 CHECK(raw.dx==10&&raw.dy==-4&&raw.generation==generation+1&&raw.active_epoch==epoch);
 CHECK(raw.accumulated_x==10&&raw.accumulated_y==uint64_t(int64_t(-4)));
 p=Poll(0);CHECK(p.rx==snapshot.rx&&p.ry==snapshot.ry&&p.analog[2]==255);
 for(int i=0;i<20;i++){Poll(0);Poll(1);CHECK(GetMouseSnapshot().generation==raw.generation&&GetMouseSnapshot().dx==10);}
 AdvanceFrame(time_us);AdvanceFrame(time_us-1);CHECK(GetMouseSnapshot().generation==raw.generation);
 Mouse(3,4);Frame();CHECK(GetMouseSnapshot().dx==3&&GetMouseSnapshot().dy==4);
 CHECK(GetMouseSnapshot().accumulated_x==13&&GetMouseSnapshot().accumulated_y==0);
 Frame();CHECK(!GetMouseSnapshot().dx&&!GetMouseSnapshot().dy);
 for(int i=0;i<3;i++)Mouse(INT32_MAX,INT32_MIN);Frame();
 CHECK(GetMouseSnapshot().dx==INT32_MAX&&GetMouseSnapshot().dy==INT32_MIN);
 raw=GetMouseSnapshot();Mouse(4,5);Frame(300000);
 CHECK(GetMouseSnapshot().active_epoch!=raw.active_epoch&&!GetMouseSnapshot().dx&&!GetMouseSnapshot().dy);
 CHECK(!GetMouseSnapshot().accumulated_x&&!GetMouseSnapshot().accumulated_y);
 raw=GetMouseSnapshot();Mouse(9,9);SetActive(false);
 CHECK(!GetMouseSnapshot().active&&!GetMouseSnapshot().dx&&GetMouseSnapshot().active_epoch!=raw.active_epoch);
 raw=GetMouseSnapshot();SetActive(false);CHECK(GetMouseSnapshot().active_epoch==raw.active_epoch);
 SetActive(true);Mouse(99,99);Frame();CHECK(!GetMouseSnapshot().dx&&!GetMouseSnapshot().dy);
 Mouse(2,-3);Frame();CHECK(GetMouseSnapshot().dx==2&&GetMouseSnapshot().dy==-3);
 raw=GetMouseSnapshot();SetMouseToStick(true);
 CHECK(GetMouseSnapshot().active_epoch!=raw.active_epoch&&!GetMouseSnapshot().dx);
 Frame();Mouse(8,-4);Frame();CHECK(Poll(0).rx>8000&&Poll(0).ry>4000);
 std::puts("actual native input frame snapshots, all buttons, focus, physical merge, timing and mouse bounds passed");
}
'''


class NativeInputTests(unittest.TestCase):
    def test_production_poll_and_event_transforms(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required for native input check")
        with tempfile.TemporaryDirectory(prefix="xbexbe-native-input-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            (folder / "SDL3").mkdir()
            (folder / "SDL3/SDL.h").write_text(SDL)
            path, exe = folder / "test.cpp", folder / "test.exe"
            window = (SDK / "app/main.cpp").read_text()
            clause = re.search(r"    if \(msg == WM_KEYDOWN[^\n]*\)\n        input::Key\([^;]+;", window)
            self.assertIsNotNone(clause)
            bridge = ("enum { WM_KEYDOWN=0x100, WM_KEYUP=0x101, WM_SYSKEYDOWN=0x104, WM_SYSKEYUP=0x105 };\n"
                      "static void NativeKey(uint32_t msg,uintptr_t wp) {\n" + clause.group() + "\n}")
            path.write_text(FIXTURE.replace("NATIVE_KEY_BRIDGE", bridge))
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(folder),
                                     "-I", str(SDK), str(path), "-o", str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("actual native input frame snapshots", result.stdout)


if __name__ == "__main__":
    unittest.main()
