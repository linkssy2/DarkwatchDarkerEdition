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
#include <set>
#include "graphics_cinematic.cpp"
#define CHECK(x) do {if (!(x)) {std::fprintf(stderr,"case %u line %d: %s\n",cases,__LINE__,#x);std::exit(90);}} while(0)
static unsigned cases, reads;
static uint8_t memory[0x500000], saved[sizeof(memory)];
static std::set<uint32_t> blocked;
static darkwatch::view::Settings settings;
namespace darkwatch::view { Settings Snapshot(uint32_t) { return settings; } }
namespace mem { bool IsCommitted(uint32_t p) { ++reads; return p < sizeof(memory) && !blocked.contains(p); } }
static void W(uint32_t p, uint32_t v) { std::memcpy(memory+p,&v,4); }
static constexpr uint32_t effect=0x10FF0;
static X86Context Setup() {
    settings={};settings.cutscene_borders=false;reads=0;blocked.clear();
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


if __name__ == "__main__":
    unittest.main()
