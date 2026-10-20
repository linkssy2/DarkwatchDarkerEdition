"""Actual shared raw input and title hooks; original tails have a separate oracle."""
from pathlib import Path
import os
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
#include <cstdarg>
#include <set>
#include <vector>
#include <string>
#include "core/input.cpp"
#include "game_info.cpp"
static darkwatch::ControlsSettings controls;
darkwatch::ControlsSettings darkwatch::ControlsSnapshot(){return controls;}
static const void* controls_load_table=nullptr;
static void* controls_save_table=nullptr;
static const void* view_load_table=nullptr;
static void* view_save_table=nullptr;
void darkwatch::ControlsLoad(const void* t){controls_load_table=t;}
void darkwatch::ControlsSave(void* t){controls_save_table=t;}
void darkwatch::view::Load(const void* t){view_load_table=t;}
void darkwatch::view::Save(void* t){view_save_table=t;}
static const void* coop_load_table=nullptr;
static void* coop_save_table=nullptr;
void darkwatch::coop::Load(const void* t){coop_load_table=t;}
void darkwatch::coop::Save(void* t){coop_save_table=t;}
void darkwatch::coop::Start(){}
void darkwatch::coop::Pad(int,input::Pad&){}
void darkwatch::coop::Rumble(int,uint16_t&,uint16_t&){}
bool darkwatch::ControlsMessage(void*,uint32_t,uintptr_t,intptr_t,intptr_t*){return false;}
// The graphics page has its own actual ImGui/input fixture; isolate direct aiming here.
void DarkwatchGraphicsInit() {}
void DarkwatchGraphicsWindow(void*) {}
void DarkwatchGraphicsUi(double) {}
void DarkwatchMenuUi(double) {}
bool darkwatch::InitializeMenuCursor() { return true; }
void darkwatch::InitializeHdUi() {}
int darkwatch::PrepareShaders() { return 0; }
void DarkwatchGraphicsPad(int, input::Pad&) {}
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}} while(0)
static uint8_t memory[0x500000],before[0x500000];
static std::set<uint32_t> blocked;
static std::vector<std::string> messages;
static X86Context c;
static uint64_t now=1000000;
static uint32_t state=0x1000,owner=0x2000,route=0x421FE0;
static unsigned cases=0;
static float dt_seconds=.02f;
bool mem::IsCommitted(uint32_t page){CHECK(!(page&0xFFF));return page<sizeof(memory)&&!blocked.contains(page);}
void* app::Window(){return nullptr;}
void logx::Write(Level,const char* fmt,...){char text[2048];va_list args;va_start(args,fmt);std::vsnprintf(text,sizeof(text),fmt,args);va_end(args);messages.emplace_back(text);}
static void W(uint32_t p,uint32_t v){std::memcpy(memory+p,&v,4);}
static void F(uint32_t p,float v){std::memcpy(memory+p,&v,4);}
static float RF(uint32_t p){float v;std::memcpy(&v,memory+p,4);return v;}
static bool Near(double a,double b){return std::abs(a-b)<0.0002*std::max(1.0,std::abs(b));}
static void Frame(int32_t dx=0,int32_t dy=0,uint64_t elapsed=20000){input::Mouse(dx,dy);now+=elapsed;input::AdvanceFrame(now);}
static void Prepare(unsigned axis,unsigned top=0,double angle=10,double rate=3){
 std::memset(&c,0xA5,sizeof(c));c.ebp=axis?0x5100:0x5000;c.ebx=c.esi=state;c.top=top;
 for(unsigned i=0;i<8;i++)c.st[i]=100+i;
 c.st[top]=angle;c.st[(top+1)&7]=rate;
 W(c.ebp,0x6000);W(c.ebp+4,route==0x421FE0?(axis?0xA84B0:0xA84A1):(axis?0xA1B37:0xA1B28));
 F(c.ebp+8,axis?80:dt_seconds);F(c.ebp+0xC,float(rate));F(0x6008,dt_seconds);
}
static void Target(){
 W(state,route);W(state+0x40,owner);W(state+0x7C,owner);memory[state+0x74]=1;
 W(owner+0x30,0x700C);W(owner+0xF4,0x4000);W(owner+0x20,0x4100);
 F(owner+0x5C,-80);F(owner+0x60,80);memory[owner+0x139]=0;
 W(0x4000,0x4200);W(0x42A4,1);memory[0x410C]=0;W(0x4AC174,0x3000);W(0x30D4,0x7000);
 memory[0x3120]=1;memory[0x3121]=0;W(0x7008,0x7000);W(0x7010,0x700C);
}
static void Reset(uint32_t r=0x421FE0){
 std::memset(memory,0,sizeof(memory));blocked.clear();messages.clear();g_mouse_pair={};g_mouse_logs=0;g_mouse_log_us=0;
 state=0x1000;owner=0x2000;route=r;dt_seconds=.02f;Target();controls={};
 input::SetActive(false);input::SetMouseToStick(true);app::kGame.init();input::SetActive(true);Frame();
 Prepare(0);ApplyMouseAim(c,memory,0);CHECK(c.st[c.top]==10); // First local identity discards the old snapshot.
}
static void NoChange(unsigned axis){
 auto saved=c;std::memcpy(before,memory,sizeof(memory));
 if(axis)DarkwatchObservePitch(c,memory);else DarkwatchObserveYaw(c,memory);
 CHECK(!std::memcmp(&saved,&c,sizeof(c))&&!std::memcmp(before,memory,sizeof(memory)));++cases;
}
static bool Center(){auto saved=c;std::memcpy(before,memory,sizeof(memory));bool r=DarkwatchMousePitchActive(c,memory);
 CHECK(!std::memcmp(&saved,&c,sizeof(c))&&!std::memcmp(before,memory,sizeof(memory)));return r;}
static void Yaw(double degrees,unsigned top=0,double angle=10,double rate=3){
 Prepare(0,top,angle,rate);auto saved=c;std::memcpy(before,memory,sizeof(memory));DarkwatchObserveYaw(c,memory);
 double result=std::fmod(angle+degrees,360.0);if(result>180)result-=360;if(result<-180)result+=360;
 CHECK(Near(c.st[top],result)&&Near(c.st[(top+1)&7],rate+degrees/double(dt_seconds)));
 saved.st[top]=c.st[top];saved.st[(top+1)&7]=c.st[(top+1)&7];CHECK(!std::memcmp(&saved,&c,sizeof(c)));
 CHECK(!std::memcmp(before,memory,sizeof(memory)));++cases;
}
static void Pitch(double degrees,unsigned top=0,double angle=10,double rate=3){
 Prepare(1,top,angle,rate);CHECK(Center()==(degrees!=0));auto saved=c;std::memcpy(before,memory,sizeof(memory));
 DarkwatchObservePitch(c,memory);CHECK(Near(c.st[top],angle+degrees));CHECK(Near(RF(c.ebp+0xC),rate+degrees/double(dt_seconds)));
 saved.st[top]=c.st[top];CHECK(!std::memcmp(&saved,&c,sizeof(c)));std::memcpy(before+c.ebp+0xC,memory+c.ebp+0xC,4);
 CHECK(!std::memcmp(before,memory,sizeof(memory)));++cases;
}
int main(){
 // Walk, jump and derived vampire jump share verified original look callers.
 for(uint32_t r:{0x421FE0u,0x420E50u,0x4223A8u})for(unsigned top=0;top<8;top++){
  Reset(r);Frame(20,-30);Yaw(-1,top);Pitch(-1.5,top);
  Prepare(0,top);NoChange(0);Prepare(1,top);CHECK(!Center());NoChange(1);
 }
 Reset();Frame(-100,100);Yaw(5,7,179,4);Pitch(5,6,79,4); // Original tail, separately tested, clamps this pitch to80.
 Frame(INT32_MAX,INT32_MIN);Yaw(-double(INT32_MAX)*.05,3);Pitch(double(INT32_MIN)*.05,2);
 Reset();memory[owner+0x139]=1;Frame(4,20);Yaw(-.2);Pitch(-1);
 // Y must come from the yaw-latched generation even if Swap publishes between the pair.
 Reset();Frame(20,40);Yaw(-1);auto generation=input::GetMouseSnapshot().generation;Frame(60,80);
 Pitch(2);CHECK(g_mouse_pair.sample.generation==generation);Yaw(-3);Pitch(4);
 // Nonlocal calls do not consume or invalidate pending local input.
 Reset();Frame(20,40);uint32_t local=owner;owner=0x2200;Target();W(owner+0x30,0x800C);
 Prepare(0);NoChange(0);owner=local;Target();Yaw(-1);Pitch(2);
 // A second local identity cannot reuse the old counts, even in the same generation.
 Reset();Frame(20,40);Yaw(-1);owner=0x2200;Target();Prepare(0);NoChange(0);Prepare(1);CHECK(!Center());NoChange(1);
 Frame(20,40);Yaw(-1);Pitch(2);
 // State/route transitions discard their current generation, then support the next observed route.
 route=0x420E50;state=0x1200;Target();Prepare(0);NoChange(0);Frame(20,40);Yaw(-1);Pitch(2);
 // Focus between axes drops Y; reacquisition cannot replay queued counts.
 Reset();Frame(20,40);Yaw(-1);input::SetActive(false);Prepare(1);CHECK(!Center());NoChange(1);
 input::Mouse(100,100);input::SetActive(true);Frame(100,100);Prepare(0);NoChange(0);Frame(20,40);Yaw(-1);Pitch(2);
 // A long idle gap drops current counts. A two-generation simulation interval is allowed.
 Reset();Frame(20,40,300000);Prepare(0);NoChange(0);Frame(1,2);Frame(20,40);Yaw(-1.05);Pitch(2.1);
 Frame(3,4);Frame(5,6);Frame(7,8);Yaw(-.75);Pitch(.9);
 Frame(500,-600);Frame(-500,600);Yaw(0);Pitch(0);
 Frame(INT32_MAX,INT32_MIN);Frame(INT32_MAX,INT32_MIN);Frame(INT32_MAX,INT32_MIN);
 Yaw(-3*double(INT32_MAX)*.05);Pitch(3*double(INT32_MIN)*.05);
 for(float dt:{.008f,.016f,.033f,.1f}){Reset();dt_seconds=dt;Frame(20,40);Yaw(-1);Pitch(2);}
 // Rejected local updates advance both cumulative baselines; re-enabling has no burst.
 Reset();memory[0x3121]=1;
 for(unsigned i=0;i<5;i++){Frame(1000,2000);Prepare(0);NoChange(0);}
 memory[0x3121]=0;Frame(20,40);Yaw(-1);Pitch(2);
 // Controller-disabled, unobserved route, original gate, and dt errors have no context/guest writes.
 for(unsigned bad=0;bad<10;bad++){
  Reset(bad==8||bad==9?0x420E50:0x421FE0);Frame(20,40);Prepare(0);
  if(bad==0)memory[0x3120]=0;if(bad==1)memory[0x3121]=1;if(bad==2)W(state,0x420BE8);
  if(bad==3)W(0x42A4,0);if(bad==4)F(c.ebp+8,0);if(bad==5)F(c.ebp+8,-1);
  if(bad==6)F(c.ebp+8,std::numeric_limits<float>::quiet_NaN());if(bad==7)F(c.ebp+8,1);
  if(bad==8)W(state+0x7C,0x2200);if(bad==9)memory[0x410C]=1;NoChange(0);
 }
 // Invalid/uncommitted/wrapping addresses and invalid arithmetic never cause unchecked writes.
 Reset();Frame(20,40);Prepare(0);c.ebx=0xFFFFFFC4;NoChange(0);
 Reset();Frame(20,40);Prepare(0);blocked.insert(0x2000);NoChange(0);
 Reset();Frame(20,40);Prepare(0);c.top=8;NoChange(0);
 Reset();Frame(20,40);Prepare(0);c.st[c.top]=std::numeric_limits<double>::quiet_NaN();NoChange(0);
 Reset();Frame(20,40);Yaw(-1);Prepare(1);CHECK(Center());c.ebp=0xFFFFFFF8;NoChange(1);
 Reset();Frame(20,40);Yaw(-1);Prepare(1);CHECK(Center());blocked.insert(0x5000);NoChange(1);
 Reset();dt_seconds=1e-40f;Frame(20,40);Prepare(0);NoChange(0);Prepare(1);CHECK(!Center());NoChange(1);
 // A missing pre-centering call must not inject Y after the original center path already ran.
 Reset();Frame(20,40);Yaw(-1);Prepare(1);NoChange(1);
 // Missing or reversed pair cannot consume Y; unsupported hooks do not change context.
 Reset();Frame(20,40);Prepare(1);CHECK(!Center());NoChange(1);Yaw(-1);Pitch(2);
 Reset();Frame(20,40);Yaw(-1);Prepare(1);W(c.ebp,0x6100);F(0x6108,.02f);CHECK(!Center());NoChange(1);
 // Settings use synchronized snapshots and callbacks, not mutable GameInfo pointers.
 Reset();controls.direct_mouse=false;app::kGame.init();Frame();Frame(8,-4);CHECK(input::Poll(0).rx>6800&&input::Poll(0).ry>3400);
 Prepare(0);NoChange(0);Prepare(1);CHECK(!Center());NoChange(1);
 CHECK(app::kGame.options.empty()&&app::kGame.load&&app::kGame.save);
 app::kGame.load(memory);app::kGame.save(memory);
 CHECK(controls_load_table==memory&&view_load_table==memory&&controls_save_table==memory&&view_save_table==memory);CHECK(coop_load_table==memory&&coop_save_table==memory);
 CHECK(app::kGame.message==darkwatch::ControlsMessage);
 // Each latched pair retains one sensitivity even if the UI changes settings between axes.
 Reset();Frame(20,40);Yaw(-1);controls.mouse_millidegrees=100;Pitch(2);
 Frame(20,40);Yaw(-2);Pitch(4);
 // Aim options are independent from direct mouse, target contents, and pending raw motion.
 for(uint32_t r:{0x421FE0u,0x420E50u,0x4223A8u})for(bool direct:{false,true})for(unsigned top=0;top<8;top++){
  Reset(r);controls.direct_mouse=direct;controls.aim_assistance=false;controls.aim_centering=false;
  for(unsigned axis=0;axis<2;axis++){
   Prepare(axis,top);auto saved=c;std::memcpy(before,memory,sizeof(memory));
   CHECK(axis?DarkwatchSkipPitchAssistance(c,memory):DarkwatchSkipYawAssistance(c,memory));
   CHECK(!std::memcmp(&saved,&c,sizeof(c))&&!std::memcmp(before,memory,sizeof(memory)));
   ++cases;
  }
  Prepare(1,top);CHECK(Center());
  controls.aim_assistance=true;CHECK(!DarkwatchSkipPitchAssistance(c,memory));CHECK(Center());
  controls.aim_assistance=false;controls.aim_centering=true;CHECK(!Center());CHECK(DarkwatchSkipPitchAssistance(c,memory));
 }
 // F1/native input inactivity does not silently re-enable assistance for a physical controller.
 Reset();controls.aim_assistance=controls.aim_centering=false;input::SetActive(false);
 Prepare(0);CHECK(DarkwatchSkipYawAssistance(c,memory));NoChange(0);
 Prepare(1);CHECK(DarkwatchSkipPitchAssistance(c,memory));CHECK(Center());NoChange(1);
 // No assistance or centering override for unknown/nonlocal/unreadable original updates.
 for(unsigned bad=0;bad<11;bad++){
  Reset(bad==8||bad==9?0x420E50:0x421FE0);controls.direct_mouse=false;
  controls.aim_assistance=controls.aim_centering=false;
  Prepare(1);
  if(bad==0)memory[0x3120]=0;if(bad==1)memory[0x3121]=1;if(bad==2)W(state,0x420BE8);
  if(bad==3)W(0x42A4,0);if(bad==4)F(0x6008,0);if(bad==5)W(owner+0x30,0x800C);
  if(bad==6)F(0x6008,std::numeric_limits<float>::quiet_NaN());if(bad==7)blocked.insert(0x2000);
  if(bad==8)W(state+0x7C,0x2200);if(bad==9)memory[0x410C]=1;
  if(bad==10)c.esi=0xFFFFFFC4;
  auto saved=c;std::memcpy(before,memory,sizeof(memory));CHECK(!DarkwatchSkipPitchAssistance(c,memory));CHECK(!Center());
  CHECK(!std::memcmp(&saved,&c,sizeof(c))&&!std::memcmp(before,memory,sizeof(memory)));++cases;
 }
 // The original gate belongs to the referenced object, not nearby wrapper data.
 for(uint32_t r:{0x421FE0u,0x420E50u,0x4223A8u})for(float unrelated:{0.f,.05f,.1f}){
  Reset(r);F(0x40A4,unrelated);Frame(20,40);Yaw(-1);Pitch(2);
  controls.aim_assistance=controls.aim_centering=false;
  Prepare(0);CHECK(DarkwatchSkipYawAssistance(c,memory));
  Prepare(1);CHECK(DarkwatchSkipPitchAssistance(c,memory));CHECK(Center());
 }
 // The derived vampire jump retains the same owner/mode/caller gates as base jump.
 for(unsigned bad=0;bad<4;bad++){
  Reset(0x4223A8);Frame(20,40);Prepare(0);
  if(bad==0)W(state+0x7C,0x2200);if(bad==1)memory[0x410C]=1;
  if(bad==2)W(c.ebp+4,0xA84A1);if(bad==3)W(0x42A4,0);NoChange(0);
  Prepare(1);if(bad==2)W(c.ebp+4,0xA84B0);CHECK(!Center());NoChange(1);
  controls.aim_assistance=controls.aim_centering=false;
  CHECK(!DarkwatchSkipPitchAssistance(c,memory));CHECK(!Center());
 }
 // Nonzero wrapper data cannot enable a closed or unreadable original gate.
 for(unsigned bad=0;bad<5;bad++){
  Reset();F(0x40A4,.1f);
  if(bad==0)W(0x42A4,0);if(bad==1)W(owner+0xF4,0);if(bad==2)W(0x4000,0);
  if(bad==3)W(0x4000,0xFFFFFF80);if(bad==4){W(0x4000,0x9000);blocked.insert(0x9000);}
  Frame(20,40);Prepare(0);NoChange(0);Prepare(1);CHECK(!Center());NoChange(1);
  controls.aim_assistance=controls.aim_centering=false;
  CHECK(!DarkwatchSkipPitchAssistance(c,memory));CHECK(!Center());
 }
 // Bounded real generation/cause logs remain available after startup.
 Reset();for(unsigned i=0;i<400;i++){Frame(1,1,20000);Yaw(-.05);Pitch(.05);}
 CHECK(g_mouse_logs<=256);if(diag::Perf()){
  bool witnessed=false;for(const auto& s:messages)if(s.find("direct mouse:")!=std::string::npos&&s.find("reason=applied")!=std::string::npos&&s.find("generation=")!=std::string::npos)witnessed=true;
  CHECK(witnessed&&g_mouse_logs>32);
 }
 std::printf("actual raw input and direct mouse hooks: %u cases passed\n",cases);
}
'''


def frontend_fixture(folder):
    # Aiming does not initialize the settings artwork; test that UI separately.
    (folder / "common").mkdir(exist_ok=True)
    (folder / "common/settings_skin.h").write_text(
        "#pragma once\nnamespace darkwatch::skin { inline void Finalize() {} }\n")


class DirectMouseTests(unittest.TestCase):
    def test_actual_input_and_hooks(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        with tempfile.TemporaryDirectory(prefix="xbexbe-direct-mouse-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            frontend_fixture(folder)
            (folder / "SDL3").mkdir()
            (folder / "SDL3/SDL.h").write_text(SDL)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(FIXTURE)
            built = subprocess.run([compiler, "-std=c++20", "-march=x86-64-v2", "-O1", "-fuse-ld=lld",
                                    "-I", str(folder), "-I", str(ROOT / "xbexbe/src/common"), "-I", str(ROOT / "xbexbe/src"), "-I", str(SDK),
                                    str(source), "-o", str(exe), "-luser32"], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            for perf in (False, True):
                env = os.environ.copy()
                env.pop("XBE_PERF", None)
                if perf:
                    env["XBE_PERF"] = "1"
                ran = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
                self.assertIn("actual raw input and direct mouse hooks:", ran.stdout)


if __name__ == "__main__":
    unittest.main()
