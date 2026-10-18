"""Exercise production input with real SDL virtual PS4/Switch pads; no game/window."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'third_party/XboxXBERecomp/runtime'
SDL = ROOT / 'build/xbexbe/_deps/sdl3-src'
SDL_LIB = ROOT / 'build/xbexbe/_deps/sdl3-build/SDL3-static.lib'
COMPILER = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/Llvm/x64/bin/clang++.exe')


class ControllerFamilyTests(unittest.TestCase):
    def test_real_sdl_mapping_hotplug_activity_and_rumble(self):
        if not COMPILER.is_file() or not SDL_LIB.is_file():
            self.skipTest('Pinned built SDL and Visual Studio Clang required')
        with tempfile.TemporaryDirectory(prefix='controller-family-', dir=ROOT / 'build') as td:
            folder = Path(td)
            source, exe = folder / 'test.cpp', folder / 'test.exe'
            source.write_text(FIXTURE)
            command = [str(COMPILER), '-std=c++20', '-O1', '-fms-runtime-lib=dll',
                       '-Wl,/NODEFAULTLIB:libcmt', '-DSDL_STATIC_LIB',
                       '-I', str(SDK), '-I', str(SDL / 'include'), str(source), str(SDL_LIB)]
            command += ['-l' + name for name in ('kernel32', 'user32', 'gdi32', 'winmm', 'imm32', 'ole32',
                        'oleaut32', 'version', 'uuid', 'advapi32', 'setupapi', 'shell32', 'dinput8')]
            result = subprocess.run(command + ['-o', str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "core/input.cpp"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s [%s]\n",__LINE__,#x,SDL_GetError());std::exit(90);}}while(0)
const app::GameInfo app::kGame={};
void logx::Write(Level,const char*,...){}
using namespace input;
struct VirtualPad {
 SDL_JoystickID id=0;SDL_Joystick* joystick=nullptr;int port;
 uint16_t low=0,high=0;unsigned rumbles=0;
};
static bool SDLCALL RumbleVirtual(void* data,Uint16 low,Uint16 high){
 auto& pad=*static_cast<VirtualPad*>(data);pad.low=low;pad.high=high;++pad.rumbles;return true;
}
static void Update(){SDL_UpdateJoysticks();SDL_Delay(2);for(int i=0;i<4;++i)Poll(i);}
static void Attach(VirtualPad& pad,Uint16 vendor,Uint16 product,const char* name,int port){
 SDL_VirtualJoystickDesc desc{};SDL_INIT_INTERFACE(&desc);
 desc.type=SDL_JOYSTICK_TYPE_GAMEPAD;desc.vendor_id=vendor;desc.product_id=product;
 desc.naxes=SDL_GAMEPAD_AXIS_COUNT;desc.nbuttons=SDL_GAMEPAD_BUTTON_DPAD_RIGHT+1;
 desc.axis_mask=(1u<<desc.naxes)-1;desc.button_mask=(1u<<desc.nbuttons)-1;
 desc.name=name;desc.userdata=&pad;desc.Rumble=RumbleVirtual;
 pad.id=SDL_AttachVirtualJoystick(&desc);CHECK(pad.id);pad.port=port;
 pad.joystick=SDL_OpenJoystick(pad.id);CHECK(pad.joystick);
 CHECK(SDL_SetJoystickVirtualAxis(pad.joystick,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,-32768));
 CHECK(SDL_SetJoystickVirtualAxis(pad.joystick,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,-32768));
 Update();CHECK(Poll(port).connected);
}
static void Detach(VirtualPad& pad){CHECK(SDL_DetachVirtualJoystick(pad.id));SDL_CloseJoystick(pad.joystick);pad.joystick=nullptr;Update();}
static void Button(VirtualPad& pad,SDL_GamepadButton button,bool down){CHECK(SDL_SetJoystickVirtualButton(pad.joystick,button,down));Update();}
static void Axis(VirtualPad& pad,SDL_GamepadAxis axis,Sint16 value){CHECK(SDL_SetJoystickVirtualAxis(pad.joystick,axis,value));Update();}
static void FamilyIs(ControllerFamily family){auto device=GetLastDevice();CHECK(device.controller&&device.family==family);}
static void Pc(){NotePcActivity();auto d=GetLastDevice();CHECK(!d.controller&&d.family==ControllerFamily::Xbox);}
static void Buttons(VirtualPad& pad,ControllerFamily family){
 constexpr SDL_GamepadButton digital[]{SDL_GAMEPAD_BUTTON_DPAD_UP,SDL_GAMEPAD_BUTTON_DPAD_DOWN,
  SDL_GAMEPAD_BUTTON_DPAD_LEFT,SDL_GAMEPAD_BUTTON_DPAD_RIGHT,SDL_GAMEPAD_BUTTON_START,SDL_GAMEPAD_BUTTON_BACK,
  SDL_GAMEPAD_BUTTON_LEFT_STICK,SDL_GAMEPAD_BUTTON_RIGHT_STICK};
 constexpr SDL_GamepadButton analog[]{SDL_GAMEPAD_BUTTON_SOUTH,SDL_GAMEPAD_BUTTON_EAST,
  SDL_GAMEPAD_BUTTON_WEST,SDL_GAMEPAD_BUTTON_NORTH,SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER};
 for(unsigned i=0;i<8;++i){Button(pad,digital[i],true);FamilyIs(family);CHECK(Poll(pad.port).buttons==(1u<<i));Button(pad,digital[i],false);CHECK(!Poll(pad.port).buttons);}
 for(unsigned i=0;i<6;++i){Button(pad,analog[i],true);FamilyIs(family);auto p=Poll(pad.port);CHECK(!p.buttons);
  for(unsigned j=0;j<8;++j)CHECK(p.analog[j]==(i==j?255:0));Button(pad,analog[i],false);}
 Axis(pad,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,32767);CHECK(Poll(pad.port).analog[6]==255&&Poll(pad.port).analog[7]==0);
 Axis(pad,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,-32768);Axis(pad,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,32767);
 CHECK(Poll(pad.port).analog[7]==255&&Poll(pad.port).analog[6]==0);Axis(pad,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,-32768);
 Axis(pad,SDL_GAMEPAD_AXIS_LEFTX,12345);Axis(pad,SDL_GAMEPAD_AXIS_LEFTY,-23456);
 Axis(pad,SDL_GAMEPAD_AXIS_RIGHTX,-30000);Axis(pad,SDL_GAMEPAD_AXIS_RIGHTY,32767);
 auto p=Poll(pad.port);CHECK(p.lx==12345&&p.ly==23455&&p.rx==-30000&&p.ry==-32768);
 for(unsigned i=0;i<4;++i)Axis(pad,static_cast<SDL_GamepadAxis>(i),0);
 Rumble(pad.port,12345,23456);CHECK(pad.rumbles&&pad.low==12345&&pad.high==23456);Rumble(pad.port,0,0);
 CHECK(!pad.low&&!pad.high);
}
int main(){
 // Isolate this process from physical controllers, including rumble. Production
 // hint defaults remain unchanged; SDL's virtual driver still exercises real mapping.
 for(const char* hint:{SDL_HINT_JOYSTICK_HIDAPI,SDL_HINT_JOYSTICK_WGI,SDL_HINT_XINPUT_ENABLED,
     SDL_HINT_JOYSTICK_DIRECTINPUT,SDL_HINT_JOYSTICK_RAWINPUT,SDL_HINT_JOYSTICK_THREAD})
  CHECK(SDL_SetHintWithPriority(hint,"0",SDL_HINT_OVERRIDE));
 Init();SetActive(true);CHECK(!Poll(1).connected);Pc();auto revision=GetLastDevice().revision;
 VirtualPad ps4{},sw{};Attach(ps4,0x054c,0x05c4,"Virtual DualShock 4",0);
 CHECK(SDL_GetGamepadTypeForID(ps4.id)==SDL_GAMEPAD_TYPE_PS4);
 Attach(sw,0x057e,0x2009,"Virtual Switch Pro",1);
 CHECK(SDL_GetGamepadTypeForID(sw.id)==SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_PRO);
 CHECK(GetControllerFamily(0)==ControllerFamily::PlayStation&&GetControllerFamily(1)==ControllerFamily::Switch);
 CHECK(GetControllerFamily(-1)==ControllerFamily::Xbox&&GetControllerFamily(4)==ControllerFamily::Xbox);
 CHECK(GetControllerFamily(2)==ControllerFamily::Xbox&&!GetLastDevice().controller);
 CHECK(GetLastDevice().revision==revision);Buttons(ps4,ControllerFamily::PlayStation);Buttons(sw,ControllerFamily::Switch);
 // Positional contracts: Cross/B = south = guest A, Circle/A = east = guest B.
 Button(ps4,SDL_GAMEPAD_BUTTON_SOUTH,true);FamilyIs(ControllerFamily::PlayStation);CHECK(Poll(0).analog[0]==255);
 Button(sw,SDL_GAMEPAD_BUTTON_SOUTH,true);FamilyIs(ControllerFamily::Switch);CHECK(Poll(1).analog[0]==255);
 revision=GetLastDevice().revision;for(int i=0;i<20;++i){Poll(0);Poll(1);}CHECK(GetLastDevice().revision==revision);
 Pc();revision=GetLastDevice().revision;Update();CHECK(GetLastDevice().revision==revision);
 Button(ps4,SDL_GAMEPAD_BUTTON_SOUTH,false);Button(sw,SDL_GAMEPAD_BUTTON_SOUTH,false);CHECK(GetLastDevice().revision==revision);
 // Drift, trigger noise, and held buttons cannot steal prompts from keyboard.
 Axis(sw,SDL_GAMEPAD_AXIS_RIGHTX,500);Axis(sw,SDL_GAMEPAD_AXIS_RIGHTX,-7000);
 Axis(sw,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,-30000);CHECK(GetLastDevice().revision==revision);
 Axis(sw,SDL_GAMEPAD_AXIS_RIGHTX,9000);FamilyIs(ControllerFamily::Switch);Pc();revision=GetLastDevice().revision;
 Axis(sw,SDL_GAMEPAD_AXIS_RIGHTX,9200);CHECK(GetLastDevice().revision==revision);
 Axis(sw,SDL_GAMEPAD_AXIS_RIGHTX,16000);FamilyIs(ControllerFamily::Switch);
 Axis(sw,SDL_GAMEPAD_AXIS_RIGHTX,0);Axis(sw,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,-32768);
 // Disconnecting another port leaves the active family; active removal clears it.
 Button(ps4,SDL_GAMEPAD_BUTTON_START,true);FamilyIs(ControllerFamily::PlayStation);revision=GetLastDevice().revision;
 Detach(sw);FamilyIs(ControllerFamily::PlayStation);CHECK(GetLastDevice().revision==revision);
 CHECK(GetControllerFamily(1)==ControllerFamily::Xbox);
 Detach(ps4);CHECK(!GetLastDevice().controller&&GetLastDevice().family==ControllerFamily::Xbox);
 CHECK(GetControllerFamily(0)==ControllerFamily::Xbox);
 CHECK(!Poll(1).connected&&Poll(0).connected); // PC retains the first port.
 // A reused port has no stale held-button history, even with the same action held.
 Attach(sw,0x057e,0x2009,"Replacement Switch Pro",0);Pc();Button(sw,SDL_GAMEPAD_BUTTON_START,true);
 FamilyIs(ControllerFamily::Switch);CHECK(Poll(0).buttons==0x10);Detach(sw);
 Attach(ps4,0x054c,0x05c4,"Replacement DualShock 4",0);Button(ps4,SDL_GAMEPAD_BUTTON_START,true);
 FamilyIs(ControllerFamily::PlayStation);CHECK(Poll(0).buttons==0x10);Button(ps4,SDL_GAMEPAD_BUTTON_START,false);
 // Both PC key and raw mouse activity restore keyboard prompts; idle polls do not revert them.
 Key('W',true);CHECK(!GetLastDevice().controller&&GetLastDevice().family==ControllerFamily::Xbox);Key('W',false);
 Button(ps4,SDL_GAMEPAD_BUTTON_EAST,true);FamilyIs(ControllerFamily::PlayStation);Mouse(1,0);CHECK(!GetLastDevice().controller);
 Button(ps4,SDL_GAMEPAD_BUTTON_EAST,false);Update();CHECK(!GetLastDevice().controller);Detach(ps4);
 // SDL presents paired Joy-Cons as one full pad. Exercise that type through the
 // real SDL mapping too; this does not claim complete controls on one Joy-Con.
 VirtualPad pair{},xbox{};Attach(pair,0x057e,0x2008,"Virtual Joy-Con (L+R)",0);
 CHECK(SDL_GetGamepadTypeForID(pair.id)==SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_PAIR);
 Buttons(pair,ControllerFamily::Switch);Attach(sw,0x057e,0x2009,"Second Switch Pro",1);
 Button(pair,SDL_GAMEPAD_BUTTON_START,true);FamilyIs(ControllerFamily::Switch);revision=GetLastDevice().revision;
 Button(sw,SDL_GAMEPAD_BUTTON_START,true);FamilyIs(ControllerFamily::Switch);CHECK(GetLastDevice().revision==revision+1);
 revision=GetLastDevice().revision;Update();CHECK(GetLastDevice().revision==revision);Detach(pair);Detach(sw);
 Attach(xbox,0x045e,0x028e,"Virtual Xbox 360",0);
 CHECK(SDL_GetGamepadTypeForID(xbox.id)==SDL_GAMEPAD_TYPE_XBOX360);Buttons(xbox,ControllerFamily::Xbox);Detach(xbox);
 std::puts("PASS real SDL: PS4/Switch Pro/paired Joy-Con/Xbox auto type, all mapped buttons/axes, rumble, per-port edges, hotplug, replacement and noise/PC arbitration");
}
'''


if __name__ == '__main__':
    unittest.main()
