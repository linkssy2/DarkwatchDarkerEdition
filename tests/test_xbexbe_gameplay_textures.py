"""Exercise the real optional-pack loader with synthetic v1/v2 fixtures."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GameplayTexturesTests(unittest.TestCase):

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
