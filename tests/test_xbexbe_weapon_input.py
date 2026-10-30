"""Real input/control binding edges drive the original held Swap action only once."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_xbexbe_native_input import SDL

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'third_party/XboxXBERecomp/runtime'
FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <utility>
#include "SDL3/SDL.h"
#include "app/app.h"
#include "core/log.h"
#include "common/controls.h"
#include "common/weapon_input.h"
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
const app::GameInfo app::kGame={.pad=DarkwatchWeaponInput};
void logx::Write(Level,const char*,...){}
std::vector<std::pair<unsigned,int>> requests;
int action[2]={1,11};
int DarkwatchWeaponCycleAction(unsigned player){return action[player];}
void DarkwatchQueueWeaponCycle(unsigned player,int direction){requests.emplace_back(player,direction);}
uint64_t now=100000;
void Frame(uint64_t delta=16667){input::AdvanceFrame(now+=delta);}
void Neutral(){for(auto& p:fake_pads)for(auto& b:p.buttons)b=false;Frame(200000);input::Poll(0);input::Poll(1);Frame();input::Poll(0);input::Poll(1);requests.clear();}
int main(){
 using namespace input;fake_init=true;fake_count=2;Init();SetActive(true);
 auto controls=darkwatch::ControlsDefaults();controls.weapon_buttons[1]={2,3};
 CHECK(darkwatch::ControlsApply(controls));Frame();Poll(0);Poll(1);requests.clear();
 Key(0xDD,true);Key(0xDD,false);Frame();auto p=Poll(0);CHECK(p.buttons==2&&requests.size()==1&&requests.back().second==1);
 for(int i=0;i<12;++i)CHECK(Poll(0).buttons==2);CHECK(requests.size()==1&&!Poll(1).analog[3]);
 Frame(100001);CHECK(Poll(0).buttons==2);Frame(49999);CHECK(!Poll(0).buttons);
 Frame();CHECK(!Poll(0).buttons);requests.clear();
 Key(0xDB,true);Frame();CHECK(Poll(0).buttons==2&&requests.size()==1&&requests.back().second==-1);
 Frame(200000);CHECK(!Poll(0).buttons);Frame();CHECK(!Poll(0).buttons&&requests.size()==1);Key(0xDB,false);Neutral();
 // Simultaneous Next/Previous cancels; no delayed action is queued.
 Key(0xDB,true);Key(0xDD,true);Frame();CHECK(!Poll(0).buttons&&requests.empty());
 Key(0xDB,false);Key(0xDD,false);Neutral();
 // Co-op controller owner and Chieftain's original Y swap remain independent.
 SetCoopKeyboard(true);Frame();Poll(0);Poll(1);requests.clear();
 fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_DPAD_LEFT]=true;Frame();p=Poll(1);
 CHECK(p.analog[3]==255&&!(p.buttons&4)&&requests.size()==1&&requests.back().first==1&&requests.back().second==1);
 CHECK(!Poll(0).buttons);Neutral();
 // Optional override follows physical position after an ordinary remap.
 auto map=DefaultPadBindings();std::swap(map[2],map[15]);CHECK(SetPadBindings(1,map));Neutral();
 fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_DPAD_LEFT]=true;Frame();p=Poll(1);
 CHECK(p.analog[3]==255&&!p.analog[7]&&requests.size()==1);Neutral();
 // Rejected native contexts never emit a synthetic swap.
 action[1]=-1;fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_DPAD_RIGHT]=true;Frame();p=Poll(1);
 CHECK(!p.analog[3]&&requests.empty());Neutral();action[1]=11;
 // Pause/focus clear the pending selection and held input cannot fire on return.
 Key(0xDD,true);Frame();CHECK(Poll(0).buttons==2);SetMenuMode(true);Poll(0);
 CHECK(requests.back().second==0);SetMenuMode(false);Frame();CHECK(!Poll(0).buttons);Key(0xDD,false);Neutral();
 fake_pads[0].buttons[SDL_GAMEPAD_BUTTON_DPAD_LEFT]=true;SetActive(false);Poll(1);
 CHECK(requests.back().second==0);SetActive(true);Frame();CHECK(!Poll(1).analog[3]);Frame();CHECK(!Poll(1).analog[3]);Neutral();
 // Connection scans do not queue title actions.
 Key(0xDD,true);Key(0xDD,false);Frame();Poll(0,false);CHECK(requests.empty());Poll(0);CHECK(requests.size()==1);
 Neutral();
 // User-defined directional wheel bindings reach the same immutable swap pulse.
 controls.bindings[size_t(PcAction::NextWeapon)]={{kMouseWheelUp,0}};
 controls.bindings[size_t(PcAction::PreviousWeapon)]={{kMouseWheelDown,0}};
 CHECK(darkwatch::ControlsApply(controls));Neutral();
 for(int delta:{120,-120}){
   Wheel(delta);Frame();p=Poll(0);CHECK(p.buttons==2&&requests.size()==1&&requests.back().second==(delta>0?1:-1));
   for(int i=0;i<20;++i)CHECK(Poll(0).buttons==2);CHECK(requests.size()==1);
   Frame(100001);CHECK(Poll(0).buttons==2);Frame(49999);CHECK(!Poll(0).buttons);Frame();CHECK(!Poll(0).buttons);Neutral();
 }
 std::puts("PASS cycle input: original 150ms Swap pulse, both directions, co-op ownership, physical remap, repeats, context and focus gates");
}
'''


class WeaponInputTests(unittest.TestCase):
    def test_production_input_and_control_bridge(self):
        compiler = shutil.which('clang++')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix='weapon-input-', dir=ROOT / 'build') as tmp:
            folder = Path(tmp)
            (folder / 'SDL3').mkdir()
            (folder / 'SDL3/SDL.h').write_text(SDL)
            source, exe = folder / 'test.cpp', folder / 'test.exe'
            source.write_text(FIXTURE)
            result = subprocess.run([compiler, '-std=c++20', '-O1', '-fuse-ld=lld', '-I', str(folder),
                '-I', str(SDK), '-I', str(ROOT / 'xbexbe/src'),
                '-I', str(ROOT / 'build/xbexbe/_deps/tomlplusplus-src/include'), str(source),
                str(SDK / 'core/input.cpp'), str(ROOT / 'xbexbe/src/common/controls.cpp'),
                str(ROOT / 'xbexbe/src/common/weapon_input.cpp'), '-luser32', '-o', str(exe)],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())
