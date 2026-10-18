"""Exercise the actual sampler builder/cache and conservative user AF policy."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_xbexbe_io_apc import function

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"


class AnisotropicTests(unittest.TestCase):
    def test_authored_filter_exclusions_and_live_descriptor_cache(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        source = (SDK / "gpu/d3d12.cpp").read_text()
        shader = (SDK / "gpu/shaders.cpp").read_text()
        sampler = function(source, "D3D12_SAMPLER_DESC StageSampler(")
        self.assertIn("AnisotropyOverride(", sampler)
        self.assertIn("D3D12_SRV_DIMENSION_TEXTURE2D", sampler)
        start = source.index("// D3DTEXF: 1 point")
        actual = source[start:source.index("uint32_t SimpleState(", start)]
        start = source.index("struct DrawTextures {")
        textures = source[start:source.index("\n};", start) + 4]
        helpers = "\n".join(function(source, name) for name in (
            "float Bits(", "void Color(", "D3D12_COMPARISON_FUNC Cmp(", "D3D12_TEXTURE_ADDRESS_MODE Address("))
        harness = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <unordered_map>
#include "app/app.h"
#include "gpu/ext.h"
#include "gpu/sampler_policy.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
using namespace gpu;
static app::Settings settings;
app::Settings app::Snapshot(){return settings;}
''' + function(shader, "uint64_t Hash(").replace("uint64_t Hash(", "uint64_t gpu::Hash(") + helpers + textures + r'''
constexpr uint32_t kSamplerCount=2048;
struct Device {
    std::vector<D3D12_SAMPLER_DESC> made;
    void CreateSampler(const D3D12_SAMPLER_DESC* d,D3D12_CPU_DESCRIPTOR_HANDLE){made.push_back(*d);}
};
struct Heap{void* Get(){return nullptr;}};
struct D3D12Backend {
    Device device;Device* dev_=&device;Heap smp_heap_;uint32_t smp_inc_=1,smp_used_=0;
    std::unordered_map<uint64_t,uint32_t> samplers_;FILE* cap_=nullptr;
    D3D12_CPU_DESCRIPTOR_HANDLE Cpu(void*,uint32_t,uint32_t){return {};}
    uint32_t EnsureStageSamplers(const State&,const DrawTextures&,bool);
};
''' + actual + r'''
static void Same(const D3D12_SAMPLER_DESC& a,const D3D12_SAMPLER_DESC& b){CHECK(!std::memcmp(&a,&b,sizeof(a)));}
static void SameExceptFiltering(D3D12_SAMPLER_DESC a,D3D12_SAMPLER_DESC b){
    a.Filter=b.Filter;a.MaxAnisotropy=b.MaxAnisotropy;Same(a,b);
}
int main(){
    State s;auto& t=s.tss[0];
    t[kTssMinFilter]=t[kTssMagFilter]=t[kTssMipFilter]=2;
    t[kTssAddressU]=1;t[kTssAddressV]=2;t[kTssAddressW]=4;
    t[kTssBorderColor]=0xA1223355;t[kTssMaxMipLevel]=2;t[kTssMaxAnisotropy]=8;
    float bias=-1.25f;std::memcpy(&t[kTssMipLodBias],&bias,4);
    DrawTextures textures{};textures.info[0].kind=kTex2D;
    textures.res[0]=reinterpret_cast<ID3D12Resource*>(uintptr_t(1));
    textures.sv[0].ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
    textures.sv[0].Texture2D.MipLevels=8;
    auto original=s.tss;auto initial=textures;
    auto base=StageSampler(s,0,textures,false,0);
    CHECK(base.Filter==D3D12_FILTER_MIN_MAG_MIP_LINEAR&&base.MaxAnisotropy==0);
    unsigned cases=0;
    for(uint32_t request:{1u,2u,4u,8u,16u}){
        for(uint32_t min:{2u,3u})for(uint32_t mag:{2u,3u})for(uint32_t mip:{1u,2u}){
            t[kTssMinFilter]=min;t[kTssMagFilter]=mag;t[kTssMipFilter]=mip;
            auto authored=StageSampler(s,0,textures,false,0), forced=StageSampler(s,0,textures,false,request);
            if(request==1){CHECK(forced.Filter==D3D12_FILTER(mip==2?0x15:0x14));CHECK(forced.MaxAnisotropy==0);}
            else{CHECK(forced.Filter==D3D12_FILTER_ANISOTROPIC&&forced.MaxAnisotropy==request);}
            SameExceptFiltering(authored,forced);++cases;
        }
    }
    t=original[0];
    // Excluded texture paths retain every authored descriptor byte, even when
    // the title already selected anisotropy. Cube/3D view-union values are traps.
    for(unsigned exclusion=0;exclusion<10;++exclusion){
        DrawTextures excluded=initial;
        switch(exclusion){
        case 0:excluded.rt[0]=true;break;
        case 1:excluded.info[0].rect=1;break;
        case 2:excluded.info[0].shadow=1;break;
        case 3:excluded.info[0].kind=kTexCube;excluded.sv[0].ViewDimension=D3D12_SRV_DIMENSION_TEXTURECUBE;excluded.sv[0].TextureCube.MipLevels=8;break;
        case 4:excluded.info[0].kind=kTex3D;excluded.sv[0].ViewDimension=D3D12_SRV_DIMENSION_TEXTURE3D;excluded.sv[0].Texture3D.MipLevels=8;break;
        case 5:excluded.info[0].kind=kTexNone;break;
        case 6:excluded.res[0]=nullptr;break;
        case 7:excluded.sv[0].Texture2D.MipLevels=1;break;
        case 8:excluded.sv[0].Texture2D.MipLevels=0;break;
        case 9:excluded.sv[0].ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2DARRAY;excluded.sv[0].Texture2DArray.MipLevels=8;break;
        }
        for(uint32_t min:{2u,3u})for(uint32_t request:{0u,1u,2u,4u,8u,16u}){
            t[kTssMinFilter]=min;auto authored=StageSampler(s,0,excluded,true,0);
            Same(authored,StageSampler(s,0,excluded,true,request));++cases;
        }
    }
    // Point MIN or MAG, absent mip filtering, and unrecognized filter enums are
    // intentionally preserved. This catches the previous broad MIN>=2 rule.
    t=original[0];
    for(unsigned field:{kTssMinFilter,kTssMagFilter,kTssMipFilter})for(uint32_t value:{0u,1u,4u,5u}){
        if(field==kTssMipFilter&&value==1)continue;
        auto keep=t[field];t[field]=value;
        for(uint32_t request:{1u,2u,4u,8u,16u}){Same(StageSampler(s,0,initial,false,0),StageSampler(s,0,initial,false,request));++cases;}
        t[field]=keep;
    }
    for(uint32_t request:{0u,3u,6u,32u,0xFFFFFFFFu}){Same(base,StageSampler(s,0,initial,false,request));++cases;}
    // World UVs fitting 0..1 are not a UI identity: address-clamp inference
    // remains independent from the filtering option.
    auto clamped=StageSampler(s,0,initial,true,4);
    CHECK(clamped.Filter==D3D12_FILTER_ANISOTROPIC&&clamped.MaxAnisotropy==4);
    CHECK(clamped.AddressU==D3D12_TEXTURE_ADDRESS_MODE_CLAMP&&clamped.AddressV==D3D12_TEXTURE_ADDRESS_MODE_MIRROR);
    // Changing settings picks descriptors by their actual effective bytes;
    // returning to Original reuses its existing sampler. No explicit cache flush.
    D3D12Backend backend;settings.aniso=0;
    auto index0=backend.EnsureStageSamplers(s,initial,false);CHECK(index0==0&&backend.device.made.size()==4);
    settings.aniso=16;auto index16=backend.EnsureStageSamplers(s,initial,false);
    CHECK(index16==4&&backend.device.made.size()==8&&backend.device.made[4].MaxAnisotropy==16);
    settings.aniso=4;CHECK(backend.EnsureStageSamplers(s,initial,false)==8&&backend.device.made.size()==12);
    settings.aniso=0;CHECK(backend.EnsureStageSamplers(s,initial,false)==index0&&backend.device.made.size()==12);
    CHECK(s.tss==original&&!std::memcmp(&textures,&initial,sizeof(textures)));
    std::printf("anisotropic policy %u descriptor cases; original/cache/guards unchanged\n",cases);
}
'''
        with tempfile.TemporaryDirectory(prefix="xbexbe-af-", dir=ROOT / "build") as temporary:
            folder = Path(temporary)
            src, exe = folder / "test.cpp", folder / "test.exe"
            src.write_text(harness)
            result = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK),
                                     str(src), "-o", str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("anisotropic policy 220 descriptor cases", result.stdout)


if __name__ == "__main__":
    unittest.main()
