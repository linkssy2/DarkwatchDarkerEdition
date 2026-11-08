"""Actual SDL/production routing with a built-in pad and a second controller."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_xbexbe_controller_families import COMPILER, FIXTURE, ROOT, SDK, SDL, SDL_LIB


MAIN = r'''
static void BothTriggers(VirtualPad& pad,Sint16 value){
 CHECK(SDL_SetJoystickVirtualAxis(pad.joystick,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,value));
 CHECK(SDL_SetJoystickVirtualAxis(pad.joystick,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,value));Update();
}
static void Owner(VirtualPad& pad){
 const auto n=pad.rumbles;Rumble(0,123,456);CHECK(pad.rumbles==n+1&&pad.low==123&&pad.high==456);Rumble(0,0,0);
}
int main(){
 for(const char* hint:{SDL_HINT_JOYSTICK_HIDAPI,SDL_HINT_JOYSTICK_WGI,SDL_HINT_XINPUT_ENABLED,
     SDL_HINT_JOYSTICK_DIRECTINPUT,SDL_HINT_JOYSTICK_RAWINPUT,SDL_HINT_JOYSTICK_THREAD})
  CHECK(SDL_SetHintWithPriority(hint,"0",SDL_HINT_OVERRIDE));
 SetSinglePlayerController(true);Init();SetForeground(true);SetActive(true);SetMenuMode(true);SetTitleScreen(true);
 VirtualPad deck{},external{},ps{};
 Attach(deck,0x045e,0x028e,"Built-in Xbox",0);Attach(external,0x045e,0x028e,"External Xbox",1);
 Button(external,SDL_GAMEPAD_BUTTON_START,true);Owner(external);CHECK(Poll(0).buttons&0x10);
 Button(external,SDL_GAMEPAD_BUTTON_START,false);Button(deck,SDL_GAMEPAD_BUTTON_START,true);Owner(deck);
 Button(deck,SDL_GAMEPAD_BUTTON_START,false);SetTitleScreen(false);
 PointerPosition(1,1,640,480);PointerPosition(2,1,640,480);CHECK(GetPointerSnapshot().enabled);
 // Startup C000 on the later device must not take over guest0 or its pointer.
 BothTriggers(external,32767);CHECK(!Poll(0).analog[6]&&!Poll(0).analog[7]);
 CHECK(Poll(1).analog[6]==255&&Poll(1).analog[7]==255&&GetPointerSnapshot().enabled);Owner(deck);
 BothTriggers(external,-32768);
 Button(external,SDL_GAMEPAD_BUTTON_SOUTH,true);Owner(external);
 CHECK(Poll(0).analog[0]==255&&!Poll(1).analog[0]&&!GetPointerSnapshot().enabled);
 // Mouse movement works again; holding the controller action is not another claim.
 PointerPosition(3,1,640,480);CHECK(GetPointerSnapshot().enabled&&!GetLastDevice().controller);
 Update();CHECK(GetPointerSnapshot().enabled&&!GetLastDevice().controller);
 Button(external,SDL_GAMEPAD_BUTTON_SOUTH,false);
 // Gameplay sticks and independent triggers use the newly selected guest0.
 SetMenuMode(false);Axis(external,SDL_GAMEPAD_AXIS_LEFTY,-23000);CHECK(Poll(0).ly==22999&&Poll(1).ly==-1);
 Axis(external,SDL_GAMEPAD_AXIS_LEFTY,0);Axis(deck,SDL_GAMEPAD_AXIS_RIGHTX,12000);Owner(deck);
 CHECK(Poll(0).rx==12000&&Poll(1).rx==0);Axis(deck,SDL_GAMEPAD_AXIS_RIGHTX,0);
 Axis(external,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,32767);Owner(external);
 CHECK(Poll(0).analog[6]==255&&!Poll(0).analog[7]);Axis(external,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,-32768);
 // Settings belong to the player, not the previous physical controller.
 auto remap=DefaultPadBindings();std::swap(remap[8],remap[10]);CHECK(SetPadBindings(0,remap));
 Button(external,SDL_GAMEPAD_BUTTON_WEST,true);CHECK(Poll(0).analog[0]==255&&!Poll(0).analog[2]);
 CHECK(GetControllerPromptSnapshot().bindings==remap);Button(external,SDL_GAMEPAD_BUTTON_WEST,false);
 // Another pad cannot steal the player during binding capture.
 CHECK(BeginPadCapture(0));Update();Button(deck,SDL_GAMEPAD_BUTTON_START,true);Owner(external);CHECK(PadCapturing());
 Button(external,SDL_GAMEPAD_BUTTON_EAST,true);CHECK(TakePadCapture()==10&&!PadCapturing());Owner(external);
 Button(external,SDL_GAMEPAD_BUTTON_EAST,false);Button(deck,SDL_GAMEPAD_BUTTON_START,false);
 CHECK(BeginPadCapture(0));Update();
 CHECK(SDL_SetJoystickVirtualButton(deck.joystick,SDL_GAMEPAD_BUTTON_START,true));
 CancelPadCapture();Update();CHECK(TakePadCapture()==kPadCaptureCancelled);Owner(external);
 Button(deck,SDL_GAMEPAD_BUTTON_START,false);
 // Focus loss consumes background edges, so refocusing with a held button does not switch.
 SetForeground(false);SetActive(false);Button(deck,SDL_GAMEPAD_BUTTON_SOUTH,true);Owner(external);
 SetForeground(true);SetActive(true);Update();Owner(external);Button(deck,SDL_GAMEPAD_BUTTON_SOUTH,false);
 // The paused guest may not poll at all while unfocused.
 SetForeground(false);SetActive(false);CHECK(SDL_SetJoystickVirtualButton(deck.joystick,SDL_GAMEPAD_BUTTON_SOUTH,true));
 SetForeground(true);SetActive(true);Update();Owner(external);Button(deck,SDL_GAMEPAD_BUTTON_SOUTH,false);
 Button(deck,SDL_GAMEPAD_BUTTON_SOUTH,true);Owner(deck);CHECK(Poll(0).analog[2]==255);
 Button(deck,SDL_GAMEPAD_BUTTON_SOUTH,false);CHECK(SetPadBindings(0,DefaultPadBindings()));
 // A foreground hosted panel captures PC input without disabling controller handoff.
 SetMenuMode(true);SetActive(false);Button(external,SDL_GAMEPAD_BUTTON_DPAD_DOWN,true);Owner(external);
 CHECK(Poll(0).buttons==2);Button(external,SDL_GAMEPAD_BUTTON_DPAD_DOWN,false);
 Button(deck,SDL_GAMEPAD_BUTTON_DPAD_UP,true);Owner(deck);CHECK(Poll(0).buttons==1);
 Button(deck,SDL_GAMEPAD_BUTTON_DPAD_UP,false);SetMenuMode(false);SetActive(true);
 // Freeze controller co-op in the current order, including remapping and rumble.
 SetSinglePlayerController(false);SetCoopKeyboard(false);
 Button(external,SDL_GAMEPAD_BUTTON_NORTH,true);Owner(deck);CHECK(Poll(1).analog[3]==255&&!Poll(0).analog[3]);
 Rumble(1,765,876);CHECK(external.low==765&&external.high==876);Rumble(1,0,0);
 Button(external,SDL_GAMEPAD_BUTTON_NORTH,false);
 // Keyboard co-op keeps guest0 for PC; pad activity never promotes either device.
 SetCoopKeyboard(true);SetMenuMode(true);PointerPosition(4,1,640,480);CHECK(GetPointerSnapshot().enabled);
 Button(deck,SDL_GAMEPAD_BUTTON_SOUTH,true);Button(external,SDL_GAMEPAD_BUTTON_EAST,true);
 CHECK(!Poll(0).analog[0]&&!Poll(0).analog[1]&&Poll(1).analog[0]==255&&Poll(2).analog[1]==255);
 CHECK(GetPointerSnapshot().enabled);const auto d=deck.rumbles,e=external.rumbles;Rumble(0,500,500);
 CHECK(deck.rumbles==d&&external.rumbles==e);Rumble(1,333,444);CHECK(deck.low==333);Rumble(2,555,666);CHECK(external.low==555);
 // Returning to solo baselines actions already held across the mode change.
 SetCoopKeyboard(false);SetSinglePlayerController(true);Update();Owner(deck);
 Button(deck,SDL_GAMEPAD_BUTTON_SOUTH,false);Button(external,SDL_GAMEPAD_BUTTON_EAST,false);
 Button(external,SDL_GAMEPAD_BUTTON_EAST,true);Owner(external);Button(external,SDL_GAMEPAD_BUTTON_EAST,false);
 Detach(external);CHECK(Poll(0).connected); // PC is still available.
 Button(deck,SDL_GAMEPAD_BUTTON_START,true);Owner(deck);CHECK(Poll(0).buttons&0x10);Button(deck,SDL_GAMEPAD_BUTTON_START,false);
 Attach(external,0x045e,0x028e,"Reconnected Xbox",1);Owner(deck);
 Button(external,SDL_GAMEPAD_BUTTON_SOUTH,true);Owner(external);Button(external,SDL_GAMEPAD_BUTTON_SOUTH,false);
 // Family and explicit-player prompt resolution follow the same physical handle.
 Attach(ps,0x054c,0x05c4,"Third DualShock",2);Button(ps,SDL_GAMEPAD_BUTTON_SOUTH,true);Owner(ps);
 CHECK(GetControllerFamily(0)==ControllerFamily::PlayStation);SetMenuMode(false);
 CHECK(GetControllerPromptSnapshot(0).device.family==ControllerFamily::PlayStation);
 Button(ps,SDL_GAMEPAD_BUTTON_SOUTH,false);Axis(external,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,32767);Owner(external);
 CHECK(GetControllerFamily(0)==ControllerFamily::Xbox&&Poll(0).analog[7]==255&&!Poll(0).analog[6]);
 Axis(external,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,-32768);
 // Invalid guests remain inert and cannot mutate selection.
 for(int p:{-1,4,99}){CHECK(!Poll(p).connected);Rumble(p,1,2);}Owner(external);
 Detach(ps);Detach(external);Detach(deck);
 std::puts("PASS real SDL: solo active-pad promotion, C000 rejection, menu/gameplay, focus/capture, remapping/family/rumble, reconnect and both frozen co-op layouts");
}
'''


class SinglePlayerControllerTests(unittest.TestCase):
    def test_real_sdl_player_ownership(self):
        if not COMPILER.is_file() or not SDL_LIB.is_file():
            self.skipTest("Pinned built SDL and Visual Studio Clang required")
        with tempfile.TemporaryDirectory(prefix="solo-controller-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(FIXTURE.split("int main(){")[0] + MAIN)
            command = [str(COMPILER), "-std=c++20", "-O1", "-fms-runtime-lib=dll",
                       "-Wl,/NODEFAULTLIB:libcmt", "-DSDL_STATIC_LIB", "-I", str(SDK),
                       "-I", str(SDL / "include"), str(source), str(SDL_LIB)]
            command += ["-l" + name for name in ("kernel32", "user32", "gdi32", "winmm", "imm32", "ole32",
                        "oleaut32", "version", "uuid", "advapi32", "setupapi", "shell32", "dinput8")]
            built = subprocess.run(command + ["-o", str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            env = {key: value for key, value in os.environ.items() if not key.upper().startswith("SDL_")}
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            print(ran.stdout.strip())


if __name__ == "__main__":
    unittest.main()
