"""Authored border-toggle guards; no game assets or original functions required."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"
COMMON = ROOT / "xbexbe/src/common"

PREFIX = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <limits>
#include <set>
#include <utility>
#include "graphics_cinematic.cpp"
#define CHECK(x) do {if (!(x)) {std::fprintf(stderr,"case %u line %d: %s\n",cases,__LINE__,#x);std::exit(90);}} while(0)
static unsigned cases, reads;
static uint8_t memory[0x500000], saved[sizeof(memory)];
static std::set<uint32_t> blocked;
static darkwatch::view::Settings settings;
static bool wide;
namespace darkwatch::view { Settings Snapshot(uint32_t) { return settings; } }
namespace app { bool Widescreen() { return wide; } }
namespace mem { bool IsCommitted(uint32_t p) { ++reads; return p < sizeof(memory) && !blocked.contains(p); } }
static void W(uint32_t p, uint32_t v) { std::memcpy(memory+p,&v,4); }
static constexpr uint32_t effect=0x10FF0;
static X86Context Setup() {
    settings={};settings.cutscene_borders=false;wide=false;reads=0;blocked.clear();
    std::memset(memory,0,sizeof(memory));
    W(0x4B7A4C,2);W(0x4B7A68,effect);W(effect,0x478244);
    X86Context ctx;std::memset(&ctx,0x5A,sizeof(ctx));ctx.esi=effect+0x29;return ctx;
}
static void Check(X86Context ctx, uint8_t* base, bool expected) {
    const auto before=ctx;std::memcpy(saved,memory,sizeof(memory));
    CHECK(DarkwatchHideCinematicBorder(ctx,base)==expected);
    CHECK(!std::memcmp(&before,&ctx,sizeof(ctx)));
    CHECK(!std::memcmp(saved,memory,sizeof(memory)));++cases;
}
'''

PROJECTION_DRIVER = r'''
static void WF(uint32_t p,float v) { std::memcpy(memory+p,&v,4); }
static float RF(uint32_t p) { float v;std::memcpy(&v,memory+p,4);return v; }
static X86Context ProjectionSetup(float target=.775f,float amount=1.f) {
    auto ctx=Setup();wide=true;settings.cutscene_borders=true;
    ctx.esi=effect;ctx.ebp=0x30100;ctx.esp=ctx.ebp-0x68;
    WF(effect+0x30,target);WF(effect+0x24,amount);WF(ctx.ebp+8,(1-target)*amount);
    return ctx;
}
static void ProjectionCheck(X86Context ctx,uint8_t* base,bool change,float expected=0) {
    const auto prior=ctx;std::memcpy(saved,memory,sizeof(memory));
    DarkwatchCinematicBorderProjection(ctx,base);
    CHECK(!std::memcmp(&prior,&ctx,sizeof(ctx)));
    if(change) {
        CHECK(std::abs(RF(ctx.ebp+8)-expected)<0.000001f);
        std::memcpy(saved+ctx.ebp+8,memory+ctx.ebp+8,4);
    }
    CHECK(!std::memcmp(saved,memory,sizeof(memory)));
    // A repeated callback cannot compound the crop or mutate the effect.
    DarkwatchCinematicBorderProjection(ctx,base);
    CHECK(!std::memcmp(&prior,&ctx,sizeof(ctx)));
    CHECK(!std::memcmp(saved,memory,sizeof(memory)));++cases;
}
int main() {
    // Original .225 margins leave .55 of the authored height. At 16:9,
    // .133333 margins retain that same composition at correct proportions.
    for(unsigned phase=1;phase<=3;++phase)for(float amount:{0.f,.4f,1.f}) {
        auto ctx=ProjectionSetup();WF(effect+0x24,amount);WF(ctx.ebp+8,.225f*amount);
        W(0x4B7A4C,phase);ProjectionCheck(ctx,memory,true,(2.f/15.f)*amount);
    }
    // Other valid masks retain their target framing; thin masks reach zero,
    // and the original entering/leaving interpolation amount remains linear.
    for(auto target_expected:{std::pair{.5f,.5f},std::pair{.75f,1.f/6.f},
                              std::pair{.875f,0.f},std::pair{1.f,0.f}})
    for(float amount:{0.f,.25f,1.f}) {
        auto ctx=ProjectionSetup(target_expected.first,amount);
        ProjectionCheck(ctx,memory,true,target_expected.second*amount);
    }
    for(unsigned bad=0;bad<28;++bad) {
        auto ctx=ProjectionSetup();uint8_t* base=memory;
        switch(bad) {
        case 0:wide=false;break;
        case 1:settings.cutscene_borders=false;break;
        case 2:base=nullptr;break;
        case 3:W(0x4B7A4C,0);break;
        case 4:W(0x4B7A4C,4);break;
        case 5:W(0x4B7A4C,0xFFFFFFFF);break;
        case 6:memory[0x4B7A41]=1;break;
        case 7:memory[0x4B7A41]=0xFF;break;
        case 8:W(0x4B7A68,effect+4);break;
        case 9:W(effect,0x478248);break;
        case 10:blocked.insert(0x4B7000);break;
        case 11:blocked.insert(effect&~(mem::kPage-1));break;
        case 12:blocked.insert((effect+0x3B)&~(mem::kPage-1));break;
        case 13:ctx.esi=0xFFFFFFF0;W(0x4B7A68,ctx.esi);break;
        case 14:ctx.esi=0;W(0x4B7A68,0);break;
        case 15:blocked.insert(ctx.ebp&~(mem::kPage-1));break;
        case 16:ctx.ebp=0xFFFFFFFC;ctx.esp=ctx.ebp-0x68;break;
        case 17:ctx.ebp=0;ctx.esp=0;break;
        case 18:ctx.esp+=4;break;
        case 19:WF(effect+0x30,std::numeric_limits<float>::quiet_NaN());break;
        case 20:WF(effect+0x30,std::numeric_limits<float>::infinity());break;
        case 21:WF(effect+0x30,-.1f);break;
        case 22:WF(effect+0x30,1.1f);break;
        case 23:WF(effect+0x24,std::numeric_limits<float>::quiet_NaN());break;
        case 24:WF(effect+0x24,std::numeric_limits<float>::infinity());break;
        case 25:WF(effect+0x24,-.1f);break;
        case 26:WF(effect+0x24,1.1f);break;
        case 27:ctx.esi=0x600000;W(0x4B7A68,ctx.esi);break;
        }
        ProjectionCheck(ctx,base,false);
    }
    CHECK(cases==49);
    std::puts("49 cinematic border framing, interpolation, movie and memory guards passed");
}
'''

DRIVER = r'''
int main() {
    for(unsigned phase=1;phase<=3;++phase) {
        auto ctx=Setup();W(0x4B7A4C,phase);Check(ctx,memory,true);
        settings.cutscene_borders=true;reads=0;Check(ctx,memory,false);CHECK(reads==0);
    }
    for(unsigned bad=0;bad<16;++bad) {
        auto ctx=Setup();uint8_t* base=memory;
        switch(bad) {
        case 0:base=nullptr;break;
        case 1:ctx.esi=0;break;
        case 2:ctx.esi=0x28;break;
        case 3:ctx.esi=0x29;W(0x4B7A68,0);break;
        case 4:W(0x4B7A4C,0);break;
        case 5:W(0x4B7A4C,4);break;
        case 6:W(0x4B7A4C,0xFFFFFFFF);break;
        case 7:memory[0x4B7A41]=1;break;
        case 8:memory[0x4B7A41]=0xFF;break;
        case 9:W(0x4B7A68,effect+4);break;
        case 10:W(effect,0x478248);break;
        case 11:blocked.insert(0x4B7000);break;
        case 12:blocked.insert(effect&~(mem::kPage-1));break;
        case 13:blocked.insert((effect+0x3B)&~(mem::kPage-1));break;
        case 14:ctx.esi=0xFFFFFFF9;W(0x4B7A68,0xFFFFFFD0);break;
        case 15:ctx.esi=0x600029;W(0x4B7A68,0x600000);break;
        }
        Check(ctx,base,false);
    }
    std::printf("%u cinematic preference/phase/movie/owner/identity/memory guards passed\n",cases);
}
'''


def compile_and_run(test, source, label):
    compiler = shutil.which("clang++")
    if not compiler:
        test.skipTest("Clang PATH required")
    with tempfile.TemporaryDirectory(prefix="cinematic-", dir=ROOT/"build") as tmp:
        folder = Path(tmp)
        cpp, exe = folder/"fixture.cpp", folder/"fixture.exe"
        cpp.write_text(source, encoding="utf-8")
        result = subprocess.run([compiler, "-std=c++20", "-march=x86-64-v2", "-O1",
                                 "-fuse-ld=lld", "-I", str(SDK), "-I", str(COMMON),
                                 str(cpp), "-o", str(exe)], capture_output=True, text=True, timeout=60)
        test.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
        test.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        test.assertIn(label, result.stdout)
        print(result.stdout.strip())


class CinematicTests(unittest.TestCase):
    def test_actual_authored_guards_without_guest_or_register_writes(self):
        compile_and_run(self, PREFIX+DRIVER, "cinematic preference/phase/movie/owner/identity/memory guards passed")

    def test_only_two_original_bar_draw_calls_are_configured(self):
        config = tomllib.loads((ROOT/"xbexbe/config/game.toml").read_text())
        hooks = [h for h in config["hook"] if h["call"] == "DarkwatchHideCinematicBorder"]
        self.assertEqual(hooks, [
            {"at":0x326D22,"call":"DarkwatchHideCinematicBorder","on_true":0x326D27},
            {"at":0x326D3C,"call":"DarkwatchHideCinematicBorder","on_true":0x326D41},
        ])

    def test_widescreen_bar_projection_changes_only_local_thickness(self):
        compile_and_run(self, PREFIX+PROJECTION_DRIVER,
                        "49 cinematic border framing, interpolation, movie and memory guards passed")
        config = tomllib.loads((ROOT/"xbexbe/config/game.toml").read_text())
        self.assertEqual([h for h in config["hook"] if h["call"] == "DarkwatchCinematicBorderProjection"],
                         [{"at": 0x326CF3, "call": "DarkwatchCinematicBorderProjection"}])


if __name__ == "__main__":
    unittest.main()
