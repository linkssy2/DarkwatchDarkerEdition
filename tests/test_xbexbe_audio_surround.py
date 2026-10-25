"""Exercise real speaker-bin routing, PCM/ADPCM and packet interpolation; no live device."""
from pathlib import Path
import shutil
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"


class SurroundTests(unittest.TestCase):
    def test_actual_mixer_and_guest_routes(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        source = r'''
#include <cstdio>
#include <cstdlib>
#include "xdk/dsound.cpp"
#define CHECK(x) do { if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);} }while(0)
static uint8_t memory[4 << 20];
uint8_t* kernel::g_base=memory;
const xbe::Image* kernel::g_image=nullptr;
static uint32_t allocated=0x10000;
namespace logx { void Flush() {} void Write(Level,const char*,...) {} }
uint32_t mem::AllocSystem(uint32_t n,uint32_t) { uint32_t p=allocated;allocated+=(n+15)&~15u;CHECK(allocated<sizeof(memory));return p; }
void mem::FreeSystem(uint32_t) {}
uint32_t mem::AllocContiguous(uint32_t n,uint32_t,uint32_t,uint32_t) {return mem::AllocSystem(n);}
void mem::FreeContiguous(uint32_t) {}
bool mem::IsCommitted(uint32_t p) {return p<sizeof(memory);}
namespace kernel {
void StartHostThread(const char*,std::function<void(X86Context&)>) {}
ObjectRef FromHandle(uint32_t) {CHECK(false);return nullptr;}
int32_t SetEvent(Object&) {CHECK(false);return 0;}
uint32_t CallGuest(X86Context&,uint32_t,const uint32_t*,size_t) {CHECK(false);return 0;}
std::string ReadCString(uint32_t va,size_t n) {std::string s;while(n--&&memory[va])s+=char(memory[va++]);return s;}
bool ReadGameFile(const std::string&,std::vector<uint8_t>&) {CHECK(false);return false;}
}
namespace dispatch { X86Func* Find(uint32_t){return nullptr;} uint32_t KernelThunkAddress(uint32_t o){return 0xFE000000+o*4;} }
namespace audio {void StartOutput(std::function<void(float*,uint32_t)> fn){CHECK(bool(fn));}}
static uint32_t Call(X86Func* fn,std::initializer_list<uint32_t> a){
 X86Context c{};c.esp=0x8000;W32(c.esp,0x12345678);uint32_t i=0;
 for(auto x:a)W32(c.esp+4+4*i++,x);fn(c,memory);CHECK(c.esp==0x8004+4*a.size());return c.eax;
}
static void Near(float got,float want){CHECK(std::abs(got-want)<0.000003f);}
static uint32_t Buffer(unsigned channels=1,unsigned flags=0x10){
 W16(0x300,1);W16(0x302,channels);W32(0x304,48000);W32(0x308,96000*channels);W16(0x30C,2*channels);W16(0x30E,16);
 for(unsigned f=0;f<64;++f)for(unsigned c=0;c<channels;++c)W16(0x400+2*(f*channels+c),channels==1?8192:1024*(c+1));
 W32(0x200,20);W32(0x204,flags);W32(0x208,0);W32(0x20C,0x300);W32(0x210,0);
 CHECK(Call(GUEST(DirectSoundCreateBuffer),{0x200,0x100})==0);auto obj=R32(0x100);
 CHECK(Call(GUEST(IDirectSoundBuffer_SetBufferData),{obj,0x400,128*channels})==0);
 CHECK(Call(GUEST(IDirectSoundBuffer_Play),{obj,0,0,1})==0);
 Find(obj)->applied_voice_data=true;return obj;
}
static void Bins(uint32_t obj,std::initializer_list<unsigned> bins){
 W32(0x600,bins.size());W32(0x604,0x620);unsigned i=0;
 for(auto b:bins){W32(0x620+8*i,b);W32(0x624+8*i,0);++i;}
 CHECK(Call(GUEST(IDirectSoundBuffer_SetMixBins),{obj,0x600})==0);Find(obj)->applied_voice_data=true;
}
static void Drop(uint32_t obj){CHECK(Call(GUEST(IDirectSoundBuffer_Release),{obj})==0);CHECK(g_voices.empty());}
static std::array<float,6> Frame(){
 std::array<float,8> guard;guard.fill(9);Render(guard.data()+1,1);CHECK(guard.front()==9&&guard.back()==9);
 std::array<float,6> out;std::copy_n(guard.begin()+1,6,out.begin());return out;
}
int main(){
 CHECK(!audio::SurroundEnabled()&&!audio::SurroundAvailable()&&audio::OutputChannels()==2);
 auto obj=Buffer();float old[2];Render(old,1);Near(old[0],.25f);Near(old[1],.25f);
 audio::SetSurroundEnabled(true);Render(old,1);Near(old[0],.25f);Near(old[1],.25f); // Stereo-device fallback.
 audio::SetOutputChannels(6);CHECK(audio::SurroundAvailable());
 constexpr unsigned expected[]{0,1,2,3,4,5,0,1,4,5};
 for(unsigned bin=0;bin<10;++bin){
  Bins(obj,{bin});auto out=Frame();for(unsigned c=0;c<6;++c)Near(out[c],c==expected[bin] ?.25f:0.f);
 }
 // Captured dialogue voices can target only DSP bin 10 plus a muted LFE send.
 Bins(obj,{10,3});Find(obj)->applied_gain[3]=0;
 auto dry=Frame();Near(dry[0],.25f);Near(dry[1],.25f);for(unsigned c=2;c<6;++c)Near(dry[c],0);
 Bins(obj,{6,7,8,9,2,10});
 // Native precomputed gains retain independent front/rear levels and ignore the DSP send.
 Find(obj)->applied_gain[6]=.2f;Find(obj)->applied_gain[7]=.3f;Find(obj)->applied_gain[8]=.4f;
 Find(obj)->applied_gain[9]=.5f;Find(obj)->applied_gain[2]=.6f;
 auto out=Frame();Near(out[0],.05f);Near(out[1],.075f);Near(out[2],.15f);Near(out[3],0);Near(out[4],.1f);Near(out[5],.125f);
 auto position=Find(obj)->pos;audio::SetSurroundEnabled(false);out=Frame();CHECK(Find(obj)->pos==position+1);
 for(unsigned c=2;c<6;++c)Near(out[c],0); // A live mode change does not recreate or rewind voices.
 audio::SetSurroundEnabled(true);Drop(obj);

 obj=Buffer(6);Bins(obj,{0,1,2,3,4,5});out=Frame();
 for(unsigned c=0;c<6;++c)Near(out[c],float(c+1)/32.f);Drop(obj); // Six independent PCM channels.

 obj=Buffer();Bins(obj,{0,1});auto* v=Find(obj);v->applied_voice_data=false;v->mode=1;v->p[2]=-1;
 out=Frame();Near(out[0],0);Near(out[1],0);Near(out[4],.25f);Near(out[5],.25f);
 v->p[2]=1;out=Frame();Near(out[0],.25f);Near(out[1],.25f);Near(out[4],0);Near(out[5],0);
 v->p[2]=std::nanf("");out=Frame();for(auto f:out)CHECK(std::isfinite(f));
 Drop(obj);

 obj=Buffer();Bins(obj,{8});v=Find(obj);v->tag=0x69;v->align=36;v->bits=4;v->bytes=v->play_len=v->loop_len=36;v->block=-1;
 std::memset(HostPtr(0x400),0,36);W16(0x400,8192);out=Frame();
 for(unsigned c=0;c<6;++c)Near(out[c],c==4?.25f:0);Drop(obj); // Real Xbox ADPCM decode remains active.

 // Six-channel stream crosses a packet boundary while interpolating every source channel.
 W16(0x300,1);W16(0x302,6);W32(0x304,48000);W16(0x30C,12);W16(0x30E,16);
 W32(0x200,0x10);W32(0x204,4);W32(0x208,0x300);W32(0x20C,0);W32(0x210,0);W32(0x214,0);
 CHECK(Call(GUEST(DirectSoundCreateStream),{0x200,0x100})==0);obj=R32(0x100);v=Find(obj);
 for(unsigned p=0;p<2;++p){
  for(unsigned c=0;c<6;++c)W16(0x400+p*12+c*2,1024*(c+1)*(p+1));
  W32(0x700,0x400+p*12);W32(0x704,12);W32(0x708,0x740+p*8);W32(0x70C,0x744+p*8);W32(0x710,0);
  CHECK(Call(GUEST(CDirectSoundStream_Process),{obj,0x700,0})==0);
 }
 v->nbins=6;for(unsigned c=0;c<6;++c)v->bin[c]=c;
 v->applied_voice_data=true;v->pos=.5;v->applied_step=.5;
 out=Frame();for(unsigned c=0;c<6;++c)Near(out[c],1.5f*(c+1)/32.f);
 out=Frame();for(unsigned c=0;c<6;++c)Near(out[c],2.f*(c+1)/32.f);
 CHECK(R32(0x740)==12&&R32(0x744)==0&&v->packets.size()==1);
 CHECK(Call(GUEST(CDirectSoundStream_Release),{obj})==0);CHECK(g_voices.empty());
 audio::SetOutputChannels(8);CHECK(audio::OutputChannels()==2&&!audio::SurroundAvailable());
 std::puts("discrete bins, stereo fallback, live switching, 3D direction, PCM, ADPCM and stream boundary passed");
}
'''
        with tempfile.TemporaryDirectory(prefix="xbexbe-surround-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            path, exe = folder / "test.cpp", folder / "test.exe"
            # Synthetic export addresses exercise SDK routing without translated game code.
            sdk_text = (SDK / "xdk/dsound.cpp").read_text()
            names = set(re.findall(r"SYM\((\w+)\)|HLE_(?:STDCALL|FASTCALL|CDECL)\((\w+)", sdk_text))
            names = sorted({name for row in names for name in row if name})
            (folder / "image_symbols.h").write_text("#pragma once\n"
                "#define XDK_CDirectSoundStream_Vtable 0\n#define XDK_CDirectSoundStream_Vtable2 4\n" + "".join(
                f"#define SYM_{name} {0x200000+i*16:08X}\n#define HAS_{name} 1\n" for i, name in enumerate(names)))
            path.write_text(source)
            command = [compiler, "-std=c++20", "-march=x86-64-v2", "-O1", "-fuse-ld=lld",
                       "-I", str(folder), "-I", str(SDK), str(path), "-o", str(exe)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # The former stereo-only routing must fail the independent speaker-isolation cases.
            mixer = (SDK / "xdk/dsound.cpp").read_text()
            gate = "const bool surround = output_channels == 6 && audio::SurroundEnabled();"
            self.assertEqual(mixer.count(gate), 1)
            (folder / "stereo-only.cpp").write_text(mixer.replace(gate, "const bool surround = false;"))
            path.write_text(source.replace('#include "xdk/dsound.cpp"', '#include "stereo-only.cpp"'))
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 90, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
