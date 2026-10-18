"""Exercise the actual SDK I/O APC queue, export wrapper, status mapper and guest call."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"


def function(source, start):
    begin = source.index(start)
    return source[begin:source.index("\n}\n", begin) + 3]


class IoApcTests(unittest.TestCase):
    def test_completion_arguments_status_stack_queue_and_reentrancy(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required for native SDK check")
        kernel = (SDK / "kernel/xboxkrnl.cpp").read_text()
        status_and_exports = kernel[kernel.index("static uint32_t StatusToDosError("):kernel.index("// exceptions, debug, shutdown")]
        dispatch = (SDK / "cpu/dispatch.cpp").read_text()
        thread = (SDK / "kernel/threads.cpp").read_text()
        files = (SDK / "kernel/files.cpp").read_text()
        fixture = r'''
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include "kernel/exports.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x); std::exit(90); } } while(0)
alignas(64) static uint8_t memory[0x5000];
uint8_t* kernel::g_base = memory;
static kernel::KernelFn exports[400];
static kernel::Thread* active;
static int signalled, notified, calls;
static uint32_t got[3], callback_sp;
static bool requeue;
namespace kernel {
std::mutex& DispatchLock() { static std::mutex lock;return lock; }
void RegisterExport(uint32_t ordinal, const char*, KernelFn fn) { CHECK(ordinal<400); exports[ordinal]=fn; }
Thread* Current() { return active; }
ObjectRef FromHandle(uint32_t handle) {
    static auto event=std::make_shared<Object>(ObjType::Event);
    CHECK(handle==7); return event;
}
int32_t SetEvent(Object&) { signalled++; return 0; }
void SignalChanged() { notified++; }
''' + function(dispatch, "uint32_t CallGuest(X86Context& ctx, uint32_t fn, const uint32_t* args, size_t count)") + r'''
''' + function(thread, "void QueueApc(") + function(thread, "bool RunApcs(") + function(files, "void IoStatus(") + function(files, "void Complete(") + status_and_exports + r'''
}
void x86_icall(X86Context& ctx, uint8_t*, uint32_t target) {
    using namespace kernel;
    if (target==0xFE000000+232*4) { CHECK(exports[232]); exports[232](ctx,g_base); return; }
    if (target!=0x1234) throw std::runtime_error("unknown completion target");
    CHECK(R32(ctx.esp)==0xFFFFFFF0); callback_sp=ctx.esp; calls++;
    for(uint32_t i=0;i<3;i++) got[i]=R32(ctx.esp+4+i*4);
    if (requeue) { requeue=false; QueueApc(*active,0xFE000000+232*4,0x1234,got[2],0); }
    W32(got[2]+0x10,0xFEEDBEEF);
    ctx.eax=1;ctx.ecx=2;ctx.edx=3;ctx.ebx=4;ctx.esi=5;ctx.edi=6;ctx.ebp=7;
    Return(ctx,0xBADBAD,3);
}
static void Registers(X86Context& ctx) {
    ctx.eax=11;ctx.ecx=12;ctx.edx=13;ctx.ebx=14;ctx.esi=15;ctx.edi=16;ctx.ebp=17;ctx.esp=0x3000;
}
static void CheckRegisters(const X86Context& ctx) {
    CHECK(ctx.eax==11&&ctx.ecx==12&&ctx.edx==13&&ctx.ebx==14&&ctx.esi==15&&ctx.edi==16&&ctx.ebp==17&&ctx.esp==0x3000);
}
int main() {
    using namespace kernel;
    CHECK(exports[232] && exports[301]);
    Thread current, other; X86Context ctx{}, other_ctx{}; current.ctx=&ctx; other.ctx=&other_ctx; active=&current;
    const uint32_t cases[][4]={
        {0,0x123,0,0x123}, {0x40000001,0x45,0,0x45}, {0xC0000011,123,38,0},
        {0xC0000022,123,5,0}, {0xC000007F,123,112,0}, {0xC0000023,123,122,0}, {0x80001234,123,317,0}
    };
    for(const auto& c:cases) {
        Registers(ctx); IoStatus(0x200,c[0],c[1]); W32(0x210,0);
        int before=calls, events=signalled, signals=notified;
        Complete(7,0xFE000000+232*4,0x1234,0x200);
        CHECK(calls==before && signalled==events+1 && notified==signals+1);
        CHECK(current.apcs.size()==1 && other.apcs.empty());
        CHECK(RunApcs(current) && !RunApcs(current));
        CHECK(calls==before+1 && got[0]==c[2] && got[1]==c[3] && got[2]==0x200);
        CHECK(R32(0x200)==c[0] && R32(0x204)==c[1] && R32(0x210)==0xFEEDBEEF);
        CHECK(callback_sp==0x3000-32); CheckRegisters(ctx);
    }
    // Exercise the export directly too: the three-argument stdcall wrapper consumes 16 bytes.
    Registers(ctx); IoStatus(0x200,0,9); W32(ctx.esp,0xABCD);
    W32(ctx.esp+4,0x1234); W32(ctx.esp+8,0x200); W32(ctx.esp+12,0xDEADBEEF); W32(ctx.esp+16,0xA5A5A5A5);
    exports[232](ctx,g_base); CHECK(ctx.esp==0x3010 && ctx.eax==0 && R32(ctx.esp)==0xA5A5A5A5);
    CHECK(got[0]==0&&got[1]==9&&got[2]==0x200);
    Registers(ctx); IoStatus(0x200,0,17); requeue=true; int before=calls;
    Complete(0,0xFE000000+232*4,0x1234,0x200); CHECK(RunApcs(current));
    CHECK(calls==before+2&&current.apcs.empty()); CheckRegisters(ctx);
    before=calls; Complete(0,0,0x1234,0x200); CHECK(!RunApcs(current)&&calls==before);
    active=nullptr; Complete(0,0xFE000000+232*4,0x1234,0x200); CHECK(current.apcs.empty()); active=&current;
    // The original public status export shares the same conversion and stack contract.
    Registers(ctx); W32(ctx.esp+4,kEndOfFile); exports[301](ctx,g_base); CHECK(ctx.eax==38&&ctx.esp==0x3008);
    Registers(ctx); IoStatus(0x200,0,1); bool trapped=false;
    try { CallGuest(ctx,0xFE000000+232*4,{0x4321,0x200,0}); } catch(const std::runtime_error&) { trapped=true; }
    CHECK(trapped);
    std::puts("I/O APC success/informational/error/EOF/warning/stack/queue/reentrant cases passed");
}
'''
        with tempfile.TemporaryDirectory(prefix="xbexbe-io-apc-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            path, exe = folder / "test.cpp", folder / "test.exe"
            path.write_text(fixture)
            result = subprocess.run([compiler, "-std=c++20", "-march=x86-64-v2", "-O1", "-fuse-ld=lld",
                                     "-I", str(SDK), str(path), "-o", str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
