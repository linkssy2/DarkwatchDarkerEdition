"""Original XACT output-buffer shape through actual HLE setters and PCM mixing.

No cached host gains, coordinates, or routing state are injected. The original
XACT construction contract is separately pinned by its original-body tests.
Host allocation, clock/output startup and kernel callbacks are controlled here.
"""
from pathlib import Path
import shutil
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'third_party/XboxXBERecomp/runtime'

SOURCE = r'''
#include <cstdio>
#include <cstdlib>
#include <set>
#include "xdk/dsound.cpp"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"case %u line %d: %s\n",case_id,__LINE__,#x); std::exit(90); } } while (0)
static unsigned case_id;
static uint8_t memory[4 << 20];
uint8_t* kernel::g_base=memory;
const xbe::Image* kernel::g_image=nullptr;
static uint32_t next_alloc=0x10000, recycled;
static uint32_t next_pcm=0x200000;
static std::set<uint32_t> allocations;
namespace logx { void Flush() {} void Write(Level,const char*,...) {} }
uint32_t mem::AllocSystem(uint32_t n,uint32_t) {
    uint32_t result=recycled ? recycled : next_alloc;
    if (recycled) recycled=0; else next_alloc+=(n+15)&~15u;
    CHECK(result+n<sizeof(memory) && allocations.insert(result).second);
    std::memset(memory+result,0xA5,n); return result;
}
void mem::FreeSystem(uint32_t p) { CHECK(allocations.erase(p)==1); recycled=p; }
uint32_t mem::AllocContiguous(uint32_t n,uint32_t,uint32_t,uint32_t) { return mem::AllocSystem(n); }
void mem::FreeContiguous(uint32_t p) { mem::FreeSystem(p); }
bool mem::IsCommitted(uint32_t p) { return p<sizeof(memory); }
namespace kernel {
void StartHostThread(const char*,std::function<void(X86Context&)>) {}
ObjectRef FromHandle(uint32_t) { CHECK(false); return nullptr; }
int32_t SetEvent(Object&) { CHECK(false); return 0; }
uint32_t CallGuest(X86Context&,uint32_t,const uint32_t*,size_t) { CHECK(false); return 0; }
std::string ReadCString(uint32_t p,size_t n) { std::string s; while (n-- && memory[p]) s+=char(memory[p++]); return s; }
bool ReadGameFile(const std::string&,std::vector<uint8_t>&) { CHECK(false); return false; }
}
namespace dispatch { X86Func* Find(uint32_t) { return nullptr; } uint32_t KernelThunkAddress(uint32_t n) { return 0xFE000000+n*4; } }
namespace audio { void StartOutput(std::function<void(float*,uint32_t)> fn) { CHECK(bool(fn)); } }
static uint32_t Call(X86Func* fn,std::initializer_list<uint32_t> args) {
    X86Context ctx{}; ctx.esp=0x8000; ctx.ebx=11; ctx.esi=12; ctx.edi=13; ctx.ebp=14;
    W32(ctx.esp,0x12345678); unsigned i=0;
    for (auto value:args) W32(ctx.esp+4+4*i++,value);
    W32(ctx.esp+4+4*i,0xCAFE1234); fn(ctx,memory);
    CHECK(ctx.esp==0x8004+4*args.size() && R32(ctx.esp)==0xCAFE1234);
    CHECK(ctx.ebx==11 && ctx.esi==12 && ctx.edi==13 && ctx.ebp==14);
    return ctx.eax;
}
static uint32_t Bins(std::initializer_list<std::pair<unsigned,int>> bins) {
    W32(0x600,bins.size()); W32(0x604,0x620); unsigned i=0;
    for (auto [bin,volume]:bins) { W32(0x620+i*8,bin); W32(0x624+i*8,uint32_t(volume)); ++i; }
    return 0x600;
}
static void Format(unsigned channels=1) {
    W16(0x300,1); W16(0x302,channels); W32(0x304,48000);
    W32(0x308,96000*channels); W16(0x30C,2*channels); W16(0x30E,16);
    for (unsigned f=0;f<256;++f) for (unsigned c=0;c<channels;++c)
        W16(0x1000+2*(f*channels+c),c ? 4096 : 8192);
}
static uint32_t Parent() {
    Bins({{6,0},{8,0},{7,0},{9,0},{2,0}});
    W32(0x200,20); W32(0x204,0x602000); W32(0x208,0); W32(0x20C,0); W32(0x210,0x600);
    CHECK(Call(GUEST(DirectSoundCreateBuffer),{0x200,0x100})==0);
    return R32(0x100);
}
static uint32_t Child(bool stream,unsigned channels=1) {
    Format(channels);
    const uint32_t pcm=next_pcm; next_pcm+=0x1000;
    CHECK(next_pcm<sizeof(memory)); std::memcpy(memory+pcm,memory+0x1000,512*channels);
    if (stream) {
        W32(0x200,0x400000); W32(0x204,4); W32(0x208,0x300);
        W32(0x20C,0); W32(0x210,0); W32(0x214,0);
        CHECK(Call(GUEST(DirectSoundCreateStream),{0x200,0x100})==0);
    } else {
        W32(0x200,20); W32(0x204,0x400000); W32(0x208,0); W32(0x20C,0x300); W32(0x210,0);
        CHECK(Call(GUEST(DirectSoundCreateBuffer),{0x200,0x100})==0);
    }
    auto obj=R32(0x100);
    if (stream) {
        W32(0x700,pcm); W32(0x704,512*channels); W32(0x708,0x780); W32(0x70C,0x784); W32(0x710,0);
        CHECK(Call(GUEST(CDirectSoundStream_Process),{obj,0x700,0})==0);
    } else {
        CHECK(Call(GUEST(IDirectSoundBuffer_SetBufferData),{obj,pcm,512*channels})==0);
        CHECK(Call(GUEST(IDirectSoundBuffer_Play),{obj,0,0,1})==0);
    }
    return obj;
}
static X86Func* Route(bool stream) { return stream ? GUEST(IDirectSoundStream_SetOutputBuffer) : GUEST(IDirectSoundBuffer_SetOutputBuffer); }
static X86Func* Data(bool stream) { return stream ? GUEST(IDirectSoundStream_Set3DVoiceData) : GUEST(IDirectSoundBuffer_Set3DVoiceData); }
static X86Func* Volume(bool stream) { return stream ? GUEST(CDirectSoundStream_SetVolume) : GUEST(IDirectSoundBuffer_SetVolume); }
static X86Func* Headroom(bool stream) { return stream ? GUEST(CDirectSoundStream_SetHeadroom) : GUEST(IDirectSoundBuffer_SetHeadroom); }
static X86Func* Release(bool stream) { return stream ? GUEST(CDirectSoundStream_Release) : GUEST(IDirectSoundBuffer_Release); }
static void QuerySends(uint32_t obj,bool stream,std::initializer_list<unsigned> bins) {
    std::memset(memory+0x9FC,0xA5,0x64);
    CHECK(Call(stream ? GUEST(IDirectSoundStream_GetVoiceProperties) : GUEST(IDirectSoundBuffer_GetVoiceProperties),
               {obj,0xA00})==0);
    CHECK(R32(0x9FC)==0xA5A5A5A5 && R32(0xA5C)==0xA5A5A5A5);
    CHECK(R32(0xA00)==bins.size()); unsigned i=0;
    for (unsigned bin:bins) CHECK(R32(0xA04+8*i++)==bin);
    for (;i<8;++i) CHECK(R32(0xA04+8*i)==0xFFFFFFFFu);
}
static void Attach(uint32_t child,bool stream,uint32_t parent) {
    CHECK(Call(Route(stream),{child,parent})==0);
    CHECK(Call(stream ? GUEST(IDirectSoundStream_Use3DVoiceData) : GUEST(IDirectSoundBuffer_Use3DVoiceData),{child,1})==0);
    CHECK(Call(stream ? GUEST(CDirectSoundStream_SetMixBins) : GUEST(IDirectSoundBuffer_SetMixBins),
               {child,Bins({{10,0},{3,-10000}})})==0);
    QuerySends(child,stream,{10,3});
}
static void Spatial(uint32_t obj,bool stream,unsigned mask,int distance,int cone,int front,int rear,int center) {
    for (unsigned i=0;i<14;++i) W32(0x800+i*4,0);
    W32(0x800,mask); W32(0x804,uint32_t(distance)); W32(0x808,uint32_t(cone));
    W32(0x810,uint32_t(rear)); W32(0x814,uint32_t(front)); W32(0x818,uint32_t(center));
    CHECK(Call(Data(stream),{obj,0x800})==0);
}
static double Gain(unsigned attenuation) {
    unsigned packed=std::min(attenuation*64/100,4095u);
    return packed==4095 ? 0 : std::pow(10.,-double(packed)/1280.);
}
static void Near(float got,double want) {
    if (!std::isfinite(got) || std::abs(got-want)>=.000003)
        std::fprintf(stderr,"PCM got %.9g expected %.9g\n",got,want);
    CHECK(std::isfinite(got) && std::abs(got-want)<.000003);
}
static std::array<float,6> Frame() {
    std::array<float,8> out; out.fill(19); Render(out.data()+1,1);
    CHECK(out.front()==19 && out.back()==19);
    std::array<float,6> result; std::copy_n(out.begin()+1,6,result.begin()); return result;
}
static void Expected(const std::array<float,6>& got,double front,double rear,double center=0) {
    Near(got[0],front); Near(got[1],front); Near(got[2],center); Near(got[3],0); Near(got[4],rear); Near(got[5],rear);
}
static void BufferPosition(uint32_t obj,unsigned bytes) {
    CHECK(Call(GUEST(IDirectSoundBuffer_GetCurrentPosition),{obj,0x900,0x904})==0);
    CHECK(R32(0x900)==bytes);
}
static void Routing(bool stream) {
    ++case_id; auto parent=Parent(); auto child=Child(stream);
    // The parent has no PCM and is never Play'ed. Its directional state must still be used.
    Attach(child,stream,parent);
    Spatial(child,stream,0x33,0,0,0,0,0);
    Spatial(parent,false,0xDC,0,0,-6000,0,-10000);
    double source=.25*Gain(600); // Original child default headroom, exactly once.
    Expected(Frame(),source*Gain(6000),source);
    if (!stream) BufferPosition(child,2);
    Spatial(parent,false,0xDC,0,0,0,-6000,-10000);
    if (!stream) BufferPosition(child,2);
    Expected(Frame(),source,source*Gain(6000));
    if (!stream) BufferPosition(child,4); // Parent movement does not rewind the source.
    CHECK(Call(Volume(stream),{child,uint32_t(-600)})==0);
    CHECK(Call(GUEST(IDirectSoundBuffer_SetVolume),{parent,uint32_t(-300)})==0);
    Spatial(child,stream,0x33,-200,-100,0,0,0);
    source=.25*Gain(1500);
    Expected(Frame(),source*Gain(300),source*Gain(6300));
    CHECK(Call(Headroom(stream),{child,0})==0);
    CHECK(Call(GUEST(IDirectSoundBuffer_SetHeadroom),{parent,100})==0);
    source=.25*Gain(900);
    Expected(Frame(),source*Gain(400),source*Gain(6400));
    // Stereo folds original speaker destinations; it must not double distance/volume.
    audio::SetSurroundEnabled(false); Expected(Frame(),source*Gain(400),0);
    audio::SetSurroundEnabled(true);
    // Replacing the output parent uses the replacement's current gains immediately.
    auto replacement=Parent(); Spatial(replacement,false,0xDC,0,0,-10000,0,-10000);
    Attach(child,stream,replacement); Expected(Frame(),0,source);
    CHECK(Call(GUEST(IDirectSoundBuffer_Release),{parent})==0);
    // Null detaches and restores the same dry source gain, without stale parent state.
    CHECK(Call(Route(stream),{child,0})==0); Expected(Frame(),source,0);
    CHECK(Call(GUEST(IDirectSoundBuffer_Release),{replacement})==0);
    CHECK(Call(Release(stream),{child})==0); CHECK(allocations.empty());
}
static void LifetimeAndSends(bool stream) {
    ++case_id; auto parent=Parent(); auto child=Child(stream);
    Attach(child,stream,parent);
    Spatial(parent,false,0xDC,0,0,-10000,0,-10000);
    Spatial(child,stream,0x33,0,0,0,0,0);
    const double source=.25*Gain(600);
    Expected(Frame(),0,source);
    // Room attenuation belongs to the wet send, not the independent virtual dry input.
    W32(0x800,0x10); W32(0x820,uint32_t(-1800));
    CHECK(Call(Data(stream),{child,0x800})==0); Expected(Frame(),0,source);
    // Actual XACT defaults keep an independent LFE send at 0 mB. It is not routed twice.
    CHECK(Call(stream ? GUEST(CDirectSoundStream_SetMixBins) : GUEST(IDirectSoundBuffer_SetMixBins),
               {child,Bins({{10,0},{3,0}})})==0);
    auto out=Frame(); Near(out[0],0); Near(out[1],0); Near(out[2],0);
    Near(out[3],source); Near(out[4],source); Near(out[5],source);
    CHECK(Call(stream ? GUEST(CDirectSoundStream_SetMixBins) : GUEST(IDirectSoundBuffer_SetMixBins),
               {child,Bins({{10,0},{3,-10000}})})==0);
    CHECK(Call(Route(stream),{child,parent})==0); // Reattaching the same parent must not accumulate references.
    if (stream) CHECK(Call(GUEST(CDirectSoundStream_Pause),{child,1})==0);
    else CHECK(Call(GUEST(IDirectSoundBuffer_Stop),{child})==0);
    Expected(Frame(),0,0);
    if (stream) CHECK(Call(GUEST(CDirectSoundStream_Pause),{child,0})==0);
    else CHECK(Call(GUEST(IDirectSoundBuffer_Play),{child,0,0,1})==0);
    Expected(Frame(),0,source); // Stop/pause does not detach the spatial parent.
    // A routed source owns a parent reference. Releasing the caller's reference is safe.
    CHECK(Call(GUEST(IDirectSoundBuffer_Release),{parent})==1);
    Expected(Frame(),0,source);
    CHECK(Call(Route(stream),{child,0})==0);
    // The detached source reverts to its wet-only dry fallback with its own headroom.
    Expected(Frame(),.25*Gain(2400),0);
    auto reused=Parent(); CHECK(reused==parent);
    Spatial(reused,false,0xDC,0,0,0,-10000,-10000);
    Expected(Frame(),.25*Gain(2400),0); // No stale raw ID may reconnect it.
    CHECK(Call(GUEST(IDirectSoundBuffer_Release),{reused})==0);
    CHECK(Call(Release(stream),{child})==0); CHECK(allocations.empty());
}
static void InvalidRoutes() {
    ++case_id; auto first=Parent(); auto second=Parent(); auto child=Child(false);
    Attach(child,false,first); Spatial(first,false,0xDC,0,0,-10000,0,-10000);
    const double source=.25*Gain(600);
    CHECK(Call(Route(false),{child,0xBAADF00D})!=0); Expected(Frame(),0,source);
    CHECK(Call(Route(false),{first,first})!=0); Expected(Frame(),0,source);
    CHECK(Call(Route(false),{first,second})!=0); // Nested mix-ins are outside the supported title path.
    CHECK(Call(Route(false),{second,first})!=0); // Rejecting nested routes also prevents cycles.
    Expected(Frame(),0,source);
    auto wrong_type=Child(true);
    CHECK(Call(Route(false),{child,wrong_type})!=0);
    CHECK(Call(Release(true),{wrong_type})==0);
    Format(2); CHECK(Call(GUEST(IDirectSoundBuffer_SetFormat),{second,0x300})==0);
    CHECK(Call(Route(false),{child,second})!=0); Expected(Frame(),0,source);
    CHECK(Call(Release(false),{child})==0);
    CHECK(Call(Release(false),{first})==0); CHECK(Call(Release(false),{second})==0);
    CHECK(allocations.empty());
}
static void UnroutedStereo() {
    ++case_id; auto child=Child(false,2);
    const double gain=Gain(600);
    auto out=Frame(); Near(out[0],.25*gain); Near(out[1],.125*gain);
    for (unsigned c=2;c<6;++c) Near(out[c],0);
    CHECK(Call(Route(false),{child,0})==0);
    CHECK(Frame()==out); audio::SetSurroundEnabled(false); CHECK(Frame()==out);
    audio::SetSurroundEnabled(true); CHECK(Call(Release(false),{child})==0);
    CHECK(allocations.empty());
}
static void RoutedStereo(bool stream) {
    ++case_id; auto parent=Parent(); auto child=Child(stream,2);
    Attach(child,stream,parent);
    Spatial(parent,false,0xDC,0,0,-10000,0,-10000);
    Spatial(child,stream,0x33,0,0,0,0,0);
    // Original virtual input volume = trunc(2000 log10(1 / channels)) = -602 mB.
    // It is combined with the source headroom before the native packed-gain quantization.
    const double source=(.25+.125)*Gain(1202);
    Expected(Frame(),0,source);
    audio::SetSurroundEnabled(false); Expected(Frame(),source,0); audio::SetSurroundEnabled(true);
    CHECK(Call(Release(stream),{child})==0);
    CHECK(Call(Release(false),{parent})==0); CHECK(allocations.empty());
}
static void ExplicitSends(bool stream) {
    ++case_id; auto first=Parent(); auto second=Parent(); auto child=Child(stream);
    Spatial(first,false,0xDC,0,0,-10000,0,-10000);
    Spatial(second,false,0xDC,0,0,0,-10000,-10000);
    Spatial(child,stream,0x33,0,0,0,0,0);
    const double source=.25*Gain(600);
    CHECK(Call(Route(stream),{child,first})==0);
    QuerySends(child,stream,{});
    Expected(Frame(),0,source); // Attachment replaces the implicit front defaults.
    auto set_bins=stream ? GUEST(CDirectSoundStream_SetMixBins) : GUEST(IDirectSoundBuffer_SetMixBins);
    CHECK(Call(set_bins,{child,Bins({{0,0},{1,0},{3,0}})})==0);
    QuerySends(child,stream,{0,1,3});
    auto out=Frame(); Near(out[0],source); Near(out[1],source); Near(out[2],0);
    Near(out[3],source); Near(out[4],source); Near(out[5],source);
    CHECK(Call(Route(stream),{child,first})==0); CHECK(Frame()==out);
    CHECK(Call(Route(stream),{child,second})==0);
    QuerySends(child,stream,{});
    Expected(Frame(),source,0); // Changing parents clears the previous explicit sends.
    CHECK(Call(Route(stream),{child,0})==0); Expected(Frame(),0,0);
    CHECK(Call(set_bins,{child,0})==0); Expected(Frame(),source,0);
    CHECK(Call(Release(stream),{child})==0);
    CHECK(Call(Release(false),{first})==0); CHECK(Call(Release(false),{second})==0);
    CHECK(allocations.empty());
}
int main() {
    audio::SetOutputChannels(6); audio::SetSurroundEnabled(true);
    UnroutedStereo(); Routing(false); Routing(true);
    LifetimeAndSends(false); LifetimeAndSends(true); InvalidRoutes();
    RoutedStereo(false); RoutedStereo(true);
    ExplicitSends(false); ExplicitSends(true);
    std::puts("XACT buffer/stream routing, motion, two-stage gain, stereo, sends, ownership, reuse and cycle rejection passed");
}
'''


def compile_and_run(folder, source, mixer=None, release=False):
    compiler = shutil.which('clang++')
    if not compiler:
        raise unittest.SkipTest('clang++ required')
    if mixer is not None:
        (folder / 'mixer.cpp').write_text(mixer)
        source = source.replace('#include "xdk/dsound.cpp"', '#include "mixer.cpp"')
    path, exe = folder / 'test.cpp', folder / 'test.exe'
    sdk_text = (SDK / 'xdk/dsound.cpp').read_text()
    symbols = re.findall(r'SYM\((\w+)\)|HLE_(?:STDCALL|FASTCALL|CDECL)\((\w+)', sdk_text)
    names = sorted({name for row in symbols for name in row if name})
    (folder / 'image_symbols.h').write_text('#pragma once\n'
        '#define XDK_CDirectSoundStream_Vtable 0\n#define XDK_CDirectSoundStream_Vtable2 4\n' + ''.join(
        f'#define SYM_{name} {0x200000 + i * 16:08X}\n#define HAS_{name} 1\n'
        for i, name in enumerate(names)))
    path.write_text(source)
    command = [compiler, '-std=c++20', '-march=x86-64-v2', '-O1', '-fuse-ld=lld',
               '-I', str(folder), '-I', str(SDK), str(path), '-o', str(exe)]
    if release:
        command.insert(1, '-DXBE_RELEASE')
    build = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if build.returncode:
        raise AssertionError(build.stdout + build.stderr)
    return subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)


class OutputBufferTests(unittest.TestCase):
    def test_real_xact_parent_routing(self):
        with tempfile.TemporaryDirectory(prefix='xbexbe-output-', dir=ROOT / 'build') as temp:
            result = compile_and_run(Path(temp), SOURCE)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_xact_parent_routing(self):
        with tempfile.TemporaryDirectory(prefix='xbexbe-output-release-', dir=ROOT / 'build') as temp:
            result = compile_and_run(Path(temp), SOURCE, release=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_noop_output_buffer_negative_control(self):
        mixer = (SDK / 'xdk/dsound.cpp').read_text()
        signature = 'static uint32_t SetOutputBuffer(Voice& v, uint32_t output) {'
        self.assertEqual(mixer.count(signature), 1)
        start = mixer.index(signature) + len(signature)
        cursor, depth = start, 1
        while depth:
            depth += (mixer[cursor] == '{') - (mixer[cursor] == '}')
            cursor += 1
        # Preserve every other current mixer path; restore only the former accepted no-op.
        old_route = mixer[:start] + '\n    (void)v; (void)output; return 0;\n}' + mixer[cursor:]
        with tempfile.TemporaryDirectory(prefix='xbexbe-output-negative-', dir=ROOT / 'build') as temp:
            result = compile_and_run(Path(temp), SOURCE, old_route)
            self.assertEqual(result.returncode, 90, result.stdout + result.stderr)
            self.assertIn('PCM got ', result.stderr)


if __name__ == '__main__':
    unittest.main()
