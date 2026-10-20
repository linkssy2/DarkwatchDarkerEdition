"""Network co-op video: colour conversion and a real Media Foundation H.264 round trip."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "common/coop_video.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line%d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
using namespace darkwatch::coop::video;
constexpr uint32_t W=320,H=240;
static std::vector<uint8_t> Frame(int n){std::vector<uint8_t> f(W*H*4);
 for(uint32_t y=0;y<H;++y)for(uint32_t x=0;x<W;++x){uint8_t* p=&f[(y*W+x)*4];
  p[0]=uint8_t((x+n*4)&255);p[1]=uint8_t(y);p[2]=uint8_t(x<W/2?40:200);p[3]=255;}
 for(uint32_t y=60;y<120;++y)for(uint32_t x=40+n*3;x<100+n*3&&x<W;++x){uint8_t* p=&f[(y*W+x)*4];p[0]=p[1]=p[2]=250;}
 return f;}
static double Error(const uint8_t* a,const uint8_t* b,size_t pixels){double e=0;for(size_t i=0;i<pixels;++i)for(int c=0;c<3;++c)e+=std::abs(int(a[i*4+c])-int(b[i*4+c]));return e/(pixels*3);}
int main(){
 auto src=Frame(0);std::vector<uint8_t> nv12,back;
 BgraToNv12(src.data(),W*4,W,H,nv12);CHECK(nv12.size()==W*H*3/2);
 Nv12ToBgra(nv12.data(),W,H,W,H,back);CHECK(back.size()==src.size());
 const double convert=Error(src.data(),back.data(),W*H);CHECK(convert<4);
 std::vector<uint8_t> grey(W*H*4,0);for(size_t i=0;i<W*H;++i){grey[i*4]=grey[i*4+1]=grey[i*4+2]=128;grey[i*4+3]=255;}
 BgraToNv12(grey.data(),W*4,W,H,nv12);CHECK(std::abs(int(nv12[0])-126)<=2&&std::abs(int(nv12[W*H])-128)<=1&&std::abs(int(nv12[W*H+1])-128)<=1);
 CHECK(Startup());
 CHECK(!Encoder::Create(W+1,H,60,2000000));
 auto enc=Encoder::Create(W,H,60,4000000);CHECK(enc);
 auto dec=Decoder::Create();CHECK(dec);
 int units=0,keys=0,decoded=0;bool first_key=false;size_t bytes=0;double worst=0;int forced_key=-1;
 std::vector<std::vector<uint8_t>> sources;
 for(int n=0;n<40;++n){auto f=Frame(n);sources.push_back(f);BgraToNv12(f.data(),W*4,W,H,nv12);
  const bool force=n==25;
  CHECK(enc->Encode(nv12,force,[&](const uint8_t* d,size_t s,bool key){
   if(!units)first_key=key;++units;bytes+=s;if(key){++keys;if(n>=25&&forced_key<0)forced_key=n;}
   CHECK(dec->Decode(d,s,[&](const uint8_t* bgra,uint32_t w,uint32_t h){CHECK(w==W&&h==H);
    const double e=Error(sources[decoded].data(),bgra,W*H);if(decoded>2&&e>worst)worst=e;++decoded;}));}));}
 std::printf("video: %d units, %zu bytes, %d keys (forced at %d), %d decoded, worst error %.2f, convert %.2f\n",units,bytes,keys,forced_key,decoded,worst,convert);
 CHECK(first_key);CHECK(units>=38);CHECK(forced_key==25);CHECK(decoded>=36);CHECK(worst<12);
 enc.reset();dec.reset();Shutdown();
 std::puts("coop video: conversion, forced keyframe and H.264 round trip passed");
}
'''


class CoopVideoTests(unittest.TestCase):
    def test_conversion_and_h264_round_trip(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler)
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="coop-video-", dir=ROOT / "build") as name:
            folder = Path(name)
            cpp, exe = folder / "test.cpp", folder / "test.exe"
            cpp.write_text(FIXTURE)
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(ROOT / "xbexbe/src"),
                str(cpp), str(ROOT / "xbexbe/src/common/coop_video.cpp"),
                "-lmfplat", "-lmfuuid", "-lwmcodecdspuuid", "-lstrmiids", "-lole32", "-loleaut32", "-o", str(exe)],
                capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
