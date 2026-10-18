"""Actual input source: native menu pointer lifetime and last-device arbitration."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_xbexbe_native_input import SDL

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"

FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include "core/input.cpp"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
const app::GameInfo app::kGame={};
void logx::Write(Level,const char*,...){}
using namespace input;
static uint64_t time_us=100000;
static void Frame(){time_us+=16667;AdvanceFrame(time_us);}
static void Tap(uint32_t key){Key(key,true);Key(key,false);}
int main(){
 fake_init=true;fake_count=1;Init();SetActive(true);Frame();
 auto bindings=DefaultPcBindings();bindings[4]={{0x1B,'P'}};bindings[9]={{'B',0}};bindings[1].keys[1]=kMouseWheel;CHECK(SetPcBindings(bindings));
 SetWheelPulseDuration(150000);
 CHECK(!GetLastDevice().controller);
 fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_SOUTH]=true;Poll(0);CHECK(GetLastDevice().controller);
 auto revision=GetLastDevice().revision;NotePcActivity();CHECK(!GetLastDevice().controller&&GetLastDevice().revision==revision+1);
 for(int i=0;i<20;i++)Poll(0);CHECK(!GetLastDevice().controller); // held pad cannot steal the prompt back
 fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_SOUTH]=false;Poll(0);CHECK(!GetLastDevice().controller);
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTX]=500;Poll(0);CHECK(!GetLastDevice().controller);
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTX]=9000;Poll(0);CHECK(GetLastDevice().controller);
 Tap('E');CHECK(!GetLastDevice().controller);Poll(0);CHECK(!GetLastDevice().controller);
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTX]=16000;Poll(0);CHECK(GetLastDevice().controller);
 fake_pads[0].axes[SDL_GAMEPAD_AXIS_RIGHTX]=0;Poll(0);
 Frame();Mouse(2,-3);Frame();CHECK(!GetLastDevice().controller&&GetMouseSnapshot().dx==2);
 Tap(0x1B);Frame();CHECK(Poll(0).buttons&0x10);Frame();CHECK(!(Poll(0).buttons&0x10));
 auto epoch=GetMouseSnapshot().active_epoch;SetMenuMode(true);
 CHECK(!GetMouseSnapshot().active&&GetMouseSnapshot().active_epoch!=epoch);
 auto p=GetPointerSnapshot();CHECK(p.active);auto pointer_epoch=p.epoch;
 PointerPosition(-12,245,2560,1440);p=GetPointerSnapshot();CHECK(p.x==-12&&p.y==245&&p.width==2560&&p.height==1440);
 CHECK(p.epoch!=pointer_epoch);pointer_epoch=p.epoch;
 auto seq=p.sequence;PointerPosition(-12,245,2560,1440);CHECK(GetPointerSnapshot().sequence==seq);
 PointerPosition(800,400,2560,1440);PointerButton(1,true);PointerButton(1,true);PointerButton(1,false);
 PointerButton(2,true);PointerButton(2,false);PointerButton(0x1B,true);PointerButton(0x1B,false);
 p=GetPointerSnapshot();CHECK(p.left_presses==1&&p.right_presses==1&&p.back_presses==1);
 PointerPosition(810,450,2560,1440);CHECK(GetPointerSnapshot().left_x==800&&GetPointerSnapshot().left_y==400&&GetPointerSnapshot().left_width==2560&&GetPointerSnapshot().left_height==1440);
 p=GetPointerSnapshot();
 for(int i=0;i<20;i++)CHECK(GetPointerSnapshot().sequence==p.sequence);
 PointerWheel(120);Wheel(120);PointerWheel(-240);Wheel(-240);CHECK(GetPointerSnapshot().wheel==-120);
 Frame();CHECK(!Poll(0).buttons); // Native menu scrolling never activates the gameplay wheel binding.
 p=GetPointerSnapshot();PointerPosition(800,400,1280,720);CHECK(GetPointerSnapshot().epoch!=p.epoch&&GetPointerSnapshot().left_presses==p.left_presses);
 Tap(1);Tap(2);Tap(0x1B);Tap('E');Mouse(200,200);Frame();
 auto pad=Poll(0);CHECK(!pad.buttons&&pad.analog[0]==255&&pad.analog[6]==0&&pad.analog[7]==0);
 CHECK(!GetMouseSnapshot().active&&!GetMouseSnapshot().dx&&!GetMouseSnapshot().dy);
 fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_EAST]=true;pad=Poll(0);CHECK(pad.analog[1]==255&&GetLastDevice().controller);
 PointerPosition(801,400,2560,1440);CHECK(!GetLastDevice().controller);Poll(0);CHECK(!GetLastDevice().controller);
 fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_EAST]=false;Poll(0);
 SetActive(false);CHECK(!GetPointerSnapshot().active&&GetPointerSnapshot().epoch!=pointer_epoch);
 p=GetPointerSnapshot();PointerButton(1,true);PointerWheel(120);CHECK(GetPointerSnapshot().left_presses==p.left_presses&&GetPointerSnapshot().wheel==p.wheel);
 SetActive(true);CHECK(GetPointerSnapshot().active);PointerButton(1,true);PointerButton(1,false);CHECK(GetPointerSnapshot().left_presses==p.left_presses+1);
 SetMenuMode(false);CHECK(!GetPointerSnapshot().active&&GetMouseSnapshot().active);
 Frame();CHECK(!Poll(0).buttons&&!Poll(0).analog[0]&&!GetMouseSnapshot().dx);
 Tap(0x1B);Frame();CHECK(Poll(0).buttons==0x10);Frame();CHECK(!Poll(0).buttons);
 Tap(1);Frame();CHECK(Poll(0).analog[7]==255);Frame();CHECK(!Poll(0).analog[7]);
 const auto menu_wheel=GetPointerSnapshot().wheel;PointerWheel(120);CHECK(GetPointerSnapshot().wheel==menu_wheel);
 Wheel(120);Frame();CHECK(Poll(0).buttons==2);Wheel(120);SetMenuMode(true);Frame();CHECK(!Poll(0).buttons);
 PointerWheel(-120);Wheel(-120);SetMenuMode(false);Frame();CHECK(!Poll(0).buttons);
 Wheel(90);SetMenuMode(true);SetMenuMode(false);Wheel(30);Frame();CHECK(!Poll(0).buttons);
 std::puts("menu input: pointer edges/epochs, gameplay wheel/menu-scroll isolation, contextual consumption, raw-motion isolation, custom pause, controller preservation and last-device activity passed");
}
'''


class MenuInputTests(unittest.TestCase):
    def test_actual_input_pointer_and_device_lifetime(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="menu-input-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            (folder / "SDL3").mkdir()
            (folder / "SDL3/SDL.h").write_text(SDL, encoding="utf-8")
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(FIXTURE, encoding="utf-8")
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(folder),
                                     "-I", str(SDK), str(source), "-o", str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
