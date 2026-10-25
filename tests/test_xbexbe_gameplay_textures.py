"""Exercise the real optional-pack loader with synthetic v1/v2 fixtures."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GameplayTexturesTests(unittest.TestCase):
    def test_paired_low_dictionary_identity_and_pack_validation(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('Requires compiler')
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            folder = Path(folder)
            shutil.copy2(ROOT/'xbexbe/src/common/gameplay_textures.h', folder/'gameplay_textures.h')
            (folder/'gameplay_texture_assets.h').write_text(r'''
inline const std::array<uint8_t,1040> high=[](){std::array<uint8_t,1040> a{};a[3]=255;a[1024]=3;return a;}();
inline const std::array<uint8_t,1025> low=[](){std::array<uint8_t,1025> a{};a[7]=255;a[1024]=1;return a;}();
inline const GameplayAsset kGameplayAssets[]{
 {"base.dwt",4,4,1,11,16,1024,8,8,1,hd::Hash(high)}
};
''')
            (folder/'gameplay_texture_aliases.h').write_text(r'''
inline const GameplayAlias kGameplayAliases[]{
 {hd::Hash(high),1,1,1,11,1,hd::Hash(low)},
 {123,2,2,1,6,16,456}
};
''')
            (folder/'test.cpp').write_text(r'''
#include "gameplay_textures.h"
#include <cassert>
using namespace darkwatch;
static void Write(bool v2,bool corrupt=false){
 std::vector<uint8_t> d(v2?32:24);std::memcpy(d.data(),v2?"DWGAME02":"DWGAME01",8);
 uint32_t h[]{8,8,1,16};std::memcpy(d.data()+8,h,16);
 if(v2){auto hash=hd::Hash(high);std::memcpy(d.data()+24,&hash,8);}
 else d.insert(d.end(),high.begin(),high.end());
 d.insert(d.end(),8*8*4,77);auto hash=hd::Hash(d);auto p=reinterpret_cast<uint8_t*>(&hash);d.insert(d.end(),p,p+8);
 if(corrupt)d[32]^=1;
 std::ofstream f("base.dwt",std::ios::binary);f.write((char*)d.data(),d.size());assert(f);
}
int main(){
 GameplayTextures t;gpu::TextureReplacement out;gpu::TextureDesc d{};d.format=11;
 std::array<uint32_t,256> palette{};std::memcpy(palette.data(),low.data(),1024);
 for(bool v2:{false,true}){
  Write(v2);t.Open(".");assert(t.Available());
  assert(t.Replace(d,low.data()+1024,1,palette.data(),out));
  assert(out.width==8&&out.height==8&&out.bgra==std::vector<uint8_t>(256,77));
  auto saved=out;auto changed=low;changed.back()^=1;
  assert(!t.Replace(d,changed.data()+1024,1,palette.data(),out));
  palette[0]^=1;assert(!t.Replace(d,low.data()+1024,1,palette.data(),out));palette[0]^=1;
  assert(!t.Replace(d,low.data()+1024,0,palette.data(),out));
  assert(!t.Replace(d,low.data()+1024,1,nullptr,out));
  for(unsigned kind=0;kind<6;++kind){auto wrong=d;
   if(kind==0)wrong.width=2;if(kind==1)wrong.levels=2;if(kind==2)wrong.format=12;
   if(kind==3)wrong.cube=true;if(kind==4)wrong.linear=true;if(kind==5)wrong.depth=2;
   assert(!t.Replace(wrong,low.data()+1024,1,palette.data(),out));
  }
  assert(out.id==saved.id&&out.bgra==saved.bgra);
  // The exact full dictionary still takes the original comparison path.
  auto full=d;full.width=full.height=4;std::array<uint32_t,256> fullpalette{};
  std::memcpy(fullpalette.data(),high.data(),1024);
  assert(t.Replace(full,high.data()+1024,16,fullpalette.data(),out));
  Write(v2,true);assert(!t.Replace(d,low.data()+1024,1,palette.data(),out));
 }
 Write(true);t.Open(".");assert(t.Replace(d,low.data()+1024,1,palette.data(),out));
 std::filesystem::remove("base.dwt");t.Open(".");
 assert(!t.Available()&&!t.Replace(d,low.data()+1024,1,palette.data(),out));
}
''')
            exe = folder/'test.exe'
            build = subprocess.run([compiler,'-std=c++20','-O2','-I',str(ROOT/'xbexbe/src/common'),
                '-I',str(ROOT/'third_party/XboxXBERecomp/runtime'),str(folder/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run = subprocess.run([str(exe)],cwd=folder,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)

    def test_two_published_packs_or_complete_current_generation_only(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('Requires compiler')
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            folder = Path(folder)
            shutil.copy2(ROOT/'xbexbe/src/common/gameplay_textures.h', folder/'gameplay_textures.h')
            (folder/'gameplay_texture_assets.h').write_text(r'''
inline constexpr GameplayAsset kGameplayAssets[]{
 {"base.dwt",1,1,1,6,4,0,1,1,1,11},
 {"new-a.dwt",1,1,1,6,4,0,1,1,1,12,2},
 {"new-b.dwt",1,1,1,6,4,0,1,1,1,13,2},
 {"current-a.dwt",1,1,1,6,4,0,1,1,1,14,3},
 {"current-b.dwt",1,1,1,6,4,0,1,1,1,15,3}
};
''')
            (folder/'test.cpp').write_text(r'''
#include "gameplay_textures.h"
#include <cassert>
using namespace darkwatch;
static void Write(size_t i){
 const auto& a=kGameplayAssets[i];std::vector<uint8_t> d(36);
 std::memcpy(d.data(),"DWGAME02",8);uint32_t h[]{1,1,1,4};std::memcpy(d.data()+8,h,16);
 std::memcpy(d.data()+24,&a.native_hash,8);d[32]=uint8_t(i+1);d[35]=255;
 uint64_t hash=hd::Hash(d);auto p=reinterpret_cast<uint8_t*>(&hash);d.insert(d.end(),p,p+8);
 std::ofstream f(a.file,std::ios::binary);f.write((char*)d.data(),d.size());assert(f);
}
int main(int argc,char**){
 GameplayTextures t;gpu::TextureReplacement out;
 if(argc==2){
  Write(0);std::error_code error;std::filesystem::exists(kGameplayAssets[1].file,error);assert(error);
  t.Open(".");assert(!t.Available());return 0;
 }
 // Exhaust every possible partial install: only the three complete released
 // generations qualify, never a later group without its earlier additions.
 for(unsigned mask=0;mask<32;++mask){
  for(unsigned i=0;i<5;++i){
   std::filesystem::remove(kGameplayAssets[i].file);if(mask&(1u<<i))Write(i);
  }
  t.Open(".");bool valid=mask==1||mask==7||mask==31;assert(t.Available()==valid);
  for(unsigned i=0;i<5;++i)assert(t.LoadByNativeHash(11+i,out)==(valid&&bool(mask&(1u<<i))));
 }
 // A changed current payload cannot pass its lazy integrity check; a damaged
 // current header invalidates the install rather than downgrading it silently.
 {std::fstream f("current-a.dwt",std::ios::binary|std::ios::in|std::ios::out);f.seekp(32);f.put('x');}
 t.Open(".");assert(t.Available()&&!t.LoadByNativeHash(14,out)&&t.LoadByNativeHash(11,out));
 Write(3);{std::fstream f("current-a.dwt",std::ios::binary|std::ios::in|std::ios::out);f.seekp(8);f.put('x');}
 t.Open(".");assert(!t.Available());
 for(const auto& a:kGameplayAssets)std::filesystem::remove(a.file);
 t.Open(".");assert(!t.Available());
 Write(0);t.Open(".");assert(t.Available()&&t.LoadByNativeHash(11,out));
 assert(!t.LoadByNativeHash(12,out)&&!t.LoadByNativeHash(13,out));
 Write(1);t.Open(".");assert(!t.Available()&&!t.LoadByNativeHash(11,out));
 Write(2);t.Open(".");assert(t.Available()&&t.LoadByNativeHash(12,out)&&t.LoadByNativeHash(13,out));
 {std::ofstream f("new-a.dwt",std::ios::binary);f<<"broken";}
 t.Open(".");assert(!t.Available());Write(1);
 std::filesystem::remove("base.dwt");t.Open(".");assert(!t.Available());Write(0);
 std::filesystem::remove("new-a.dwt");t.Open(".");assert(!t.Available());
 std::filesystem::remove("new-b.dwt");t.Open(".");assert(t.Available()&&t.LoadByNativeHash(11,out));
}
''')
            exe = folder/'test.exe'
            build = subprocess.run([compiler,'-std=c++20','-O2','-I',str(ROOT/'xbexbe/src/common'),
                '-I',str(ROOT/'third_party/XboxXBERecomp/runtime'),str(folder/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run = subprocess.run([str(exe)],cwd=folder,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            # A filesystem status error is not evidence that an extension is absent.
            catalog = folder/'gameplay_texture_assets.h'
            # Windows reports invalid status for the reserved device; POSIX reports
            # ELOOP for a self-referencing link. Neither needs permission changes.
            error_name = 'NUL' if os.name == 'nt' else 'loop.dwt'
            if os.name != 'nt':
                (folder/error_name).symlink_to(error_name)
            catalog.write_text(catalog.read_text().replace('new-a.dwt', error_name))
            build = subprocess.run([compiler,'-std=c++20','-O2','-I',str(ROOT/'xbexbe/src/common'),
                '-I',str(ROOT/'third_party/XboxXBERecomp/runtime'),str(folder/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run = subprocess.run([str(exe),'status-error'],cwd=folder,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)


    def test_identity_mips_opacity_and_corrupt_fallback(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("Requires compiler")
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            tmp = Path(tmp)
            # A complete tiny catalog exercises the shipping parser without game assets.
            shutil.copy2(ROOT / "xbexbe/src/common/gameplay_textures.h", tmp / "gameplay_textures.h")
            (tmp / "gameplay_texture_assets.h").write_text(r'''
inline const std::array<uint8_t,8> plain_native{1,2,3,4,5,6,7,8};
inline const std::array<uint8_t,1028> palette_native=[](){std::array<uint8_t,1028> a{};a[0]=1;a[1024]=2;return a;}();
inline const GameplayAsset kGameplayAssets[]{
 {"plain.dwt",2,2,1,12,8,0,4,2,3,hd::Hash(plain_native)},
 {"palette.dwt",2,2,1,11,4,1024,2,4,3,hd::Hash(palette_native)}
};
''', encoding="utf-8")
            source = tmp / "test.cpp"
            source.write_text(r'''
#include "gameplay_textures.h"
#include <cassert>
using namespace darkwatch;
static std::span<const uint8_t> Native(size_t i){return i?std::span<const uint8_t>(palette_native):std::span<const uint8_t>(plain_native);}
static std::vector<uint8_t> Pack(size_t i,bool v2){
 const auto& a=kGameplayAssets[i];std::vector<uint8_t> data(v2?32:24);
 std::memcpy(data.data(),v2?"DWGAME02":"DWGAME01",8);
 uint32_t header[]{a.hd_width,a.hd_height,a.hd_levels,a.bytes};std::memcpy(data.data()+8,header,16);
 if(v2)std::memcpy(data.data()+24,&a.native_hash,8);
 else{auto n=Native(i);data.insert(data.end(),n.begin(),n.end());}
 for(unsigned l=0;l<a.hd_levels;++l){
  size_t bytes=size_t(std::max(a.hd_width>>l,1u))*std::max(a.hd_height>>l,1u)*4;
  for(size_t p=0;p<bytes/4;++p)data.insert(data.end(),{uint8_t(i+1),uint8_t(l),3,255});
 }
 uint64_t hash=hd::Hash(data);const auto* h=reinterpret_cast<uint8_t*>(&hash);data.insert(data.end(),h,h+8);return data;
}
static void Write(size_t i,const std::vector<uint8_t>& data){
 std::ofstream f(kGameplayAssets[i].file,std::ios::binary);f.write((const char*)data.data(),data.size());assert(f);
}
static bool Replace(GameplayTextures& textures,size_t i){
 const auto& a=kGameplayAssets[i];auto n=Native(i);gpu::TextureDesc d{};
 d.format=a.format;d.width=a.width;d.height=a.height;d.levels=a.levels;
 gpu::TextureReplacement out{777,1,1,{0}};
 bool result=textures.Replace(d,n.data()+a.palette,a.bytes,a.palette?(const uint32_t*)n.data():nullptr,out);
 gpu::TextureReplacement alias{777,1,1,{0}};
 assert(textures.LoadByNativeHash(a.native_hash,alias)==result);
 assert(alias.id==out.id&&alias.width==out.width&&alias.height==out.height&&alias.bgra==out.bgra&&alias.mips==out.mips);
 assert(!textures.LoadByNativeHash(0,alias));
 if(!result){assert(out.id==777&&out.width==1);return false;}
 assert(out.width==a.hd_width&&out.height==a.hd_height&&out.mips.size()+1==a.hd_levels);
 for(unsigned l=0;l<a.hd_levels;++l){
  auto& pixels=l?out.mips[l-1]:out.bgra;
  assert(pixels.size()==size_t(std::max(a.hd_width>>l,1u))*std::max(a.hd_height>>l,1u)*4);
  for(size_t p=0;p<pixels.size();p+=4)assert(pixels[p]==i+1&&pixels[p+1]==l&&pixels[p+3]==255);
 }
 std::vector<uint8_t> wrong(n.begin(),n.end());wrong.back()^=1;
 assert(!textures.Replace(d,wrong.data()+a.palette,a.bytes,a.palette?(const uint32_t*)wrong.data():nullptr,out));
 if(a.palette){wrong.assign(n.begin(),n.end());wrong[0]^=1;
  assert(!textures.Replace(d,wrong.data()+a.palette,a.bytes,(const uint32_t*)wrong.data(),out));}
 assert(!textures.Replace(d,n.data()+a.palette,a.bytes-1,a.palette?(const uint32_t*)n.data():nullptr,out));
 ++d.levels;assert(!textures.Replace(d,n.data()+a.palette,a.bytes,a.palette?(const uint32_t*)n.data():nullptr,out));
 return true;
}
int main(int argc,char**argv){
 assert(argc==2);const std::filesystem::path path=argv[1];std::filesystem::current_path(path);
 GameplayTextures textures;textures.Open(path);assert(!textures.Available()&&!Replace(textures,0));
 for(bool v2:{false,true}){
  Write(0,Pack(0,v2));textures.Open(path);assert(!textures.Available()&&!Replace(textures,0));
  Write(1,Pack(1,v2));textures.Open(path);assert(textures.Available()&&Replace(textures,0)&&Replace(textures,1));
  Write(1,Pack(1,!v2));textures.Open(path);assert(textures.Available()&&Replace(textures,1));
  std::ofstream("pack.json")<<"receipt ignored by runtime";textures.Open(path);assert(textures.Available());
  const auto valid=Pack(0,v2);
  for(size_t byte:{size_t(0),size_t(8),size_t(12),size_t(16),size_t(20)}){
   auto bad=valid;bad[byte]^=1;Write(0,bad);textures.Open(path);assert(!textures.Available()&&!Replace(textures,1));
  }
  if(v2){auto bad=valid;bad[24]^=1;Write(0,bad);textures.Open(path);assert(!textures.Available());}
  auto bad=valid;bad.pop_back();Write(0,bad);textures.Open(path);assert(!textures.Available());
  bad=valid;bad.push_back(0);Write(0,bad);textures.Open(path);assert(!textures.Available());
  Write(0,{'D','W','G','A','M','E','0','2'});textures.Open(path);assert(!textures.Available());
  // Header checks are cheap; the full-file integrity check is deliberately lazy.
  for(size_t byte:{valid.size()-9,valid.size()-1}){
   bad=valid;bad[byte]^=1;Write(0,bad);textures.Open(path);assert(textures.Available()&&!Replace(textures,0)&&Replace(textures,1));
  }
  if(!v2){bad=valid;bad[24]^=1;uint64_t h=hd::Hash({bad.data(),bad.size()-8});
   std::memcpy(bad.data()+bad.size()-8,&h,8);Write(0,bad);textures.Open(path);assert(textures.Available()&&!Replace(textures,0));}
  Write(0,valid);textures.Open(path);assert(textures.Available());
  bad=valid;bad[8]^=1;Write(0,bad);assert(textures.Available()&&!Replace(textures,0));Write(0,valid);
  std::filesystem::remove(kGameplayAssets[0].file);std::filesystem::remove(kGameplayAssets[1].file);
  // Availability is a startup snapshot; deleted files fail safely on upload.
  assert(textures.Available()&&!Replace(textures,0));textures.Open(path);assert(!textures.Available());
 }
}
''', encoding="utf-8")
            exe = tmp / "test.exe"
            command = [compiler, "-std=c++20", "-O2",
                       "-I", str(ROOT / "xbexbe/src/common"),
                       "-I", str(ROOT / "third_party/XboxXBERecomp/runtime"),
                       str(source), "-o", str(exe)]
            build = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe), str(tmp)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
