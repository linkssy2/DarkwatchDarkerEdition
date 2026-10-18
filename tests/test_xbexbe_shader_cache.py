"""Actual D3DCompile/cache code, real compiler DLL and filesystem; no GPU needed."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from test_xbexbe_io_apc import function

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'third_party/XboxXBERecomp/runtime'

PREAMBLE = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3dcompiler.h>
#include <bcrypt.h>
#include <wrl/client.h>
#pragma comment(lib,"d3dcompiler.lib")
#pragma comment(lib,"bcrypt.lib")
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <cwctype>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>
using Microsoft::WRL::ComPtr;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
#define LOGE(...) ((void)0)
#define LOG_FIRST(...) ((void)0)
namespace diag {bool Perf(){return true;}}
static std::filesystem::path cache_root;
namespace app {std::filesystem::path ExeDir(){return cache_root;}}
static unsigned compile_calls=0;
uint64_t Hash(const void*,size_t,uint64_t=1469598103934665603ull);
class D3D12Backend {
public:
 std::unordered_map<uint64_t,ComPtr<ID3DBlob>> blobs_;
 ID3DBlob* Compile(const std::string&,const char*,const char*,uint64_t&);
};
'''

DRIVER = r'''
static const std::string source=R"(float4 main(float4 p:POSITION):SV_Position{return p;}
float4 alternate(float4 p:POSITION):SV_Position{return p*2;})";
static std::vector<uint8_t> Read(const std::filesystem::path& p){std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
static void Write(const std::filesystem::path& p,const std::vector<uint8_t>& v){std::ofstream f(p,std::ios::binary|std::ios::trunc);f.write(reinterpret_cast<const char*>(v.data()),v.size());CHECK(bool(f));}
static std::vector<uint8_t> Bytes(ID3DBlob* b){auto* p=static_cast<uint8_t*>(b->GetBufferPointer());return {p,p+b->GetBufferSize()};}
static ID3DBlob* Compile(D3D12Backend& b,const std::string& s=source,const char* e="main",const char* p="vs_5_0") {uint64_t hash;return b.Compile(s,e,p,hash);}
static ShaderDigest Key(const std::string& s=source,const char* e="main",const char* p="vs_5_0",uint32_t f1=D3DCOMPILE_OPTIMIZATION_LEVEL1,uint32_t f2=0){
 auto compiler=ShaderCompilerIdentity();CHECK(compiler);auto key=ShaderCacheKey(s,e,p,f1,f2,*compiler);CHECK(key);return *key;
}
int main(int argc,char** argv){
 CHECK(argc==3);cache_root=std::filesystem::path(argv[2]);std::string mode=argv[1];
 auto compiler=ShaderCompilerIdentity();CHECK(compiler);
 HMODULE module=GetModuleHandleW(D3DCOMPILER_DLL_W);CHECK(module);auto actual=GetProcAddress(module,"D3DCompile");CHECK(actual);CHECK(GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,reinterpret_cast<LPCWSTR>(actual),&module));
 wchar_t module_path[32768];CHECK(GetModuleFileNameW(module,module_path,32768));auto compiler_bytes=Read(module_path);ShaderDigest compiler_digest{};
 CHECK(ShaderDigestOf(compiler_bytes.data(),compiler_bytes.size(),compiler_digest)&&compiler_digest==*compiler);
 auto module_name=std::filesystem::path(module_path).filename().wstring();for(auto& c:module_name)c=std::towlower(c);CHECK(module_name.find(L"compiler")!=std::wstring::npos);
 D3D12Backend b;auto* code=Compile(b);CHECK(code&&ShaderBytecode(code->GetBufferPointer(),code->GetBufferSize()));
 auto expected=Bytes(code);CHECK(Compile(b)==code);unsigned first_calls=compile_calls;
 if(mode=="cold"){CHECK(first_calls==1&&g_perf.shader_cache_misses==1&&g_perf.shader_cache_writes==1);}
 else if(mode=="warm"){CHECK(first_calls==0&&g_perf.shader_cache_hits==1&&g_perf.shaders==0);}
 else if(mode=="race"){CHECK(first_calls<=1);}
 else CHECK(mode=="cases");
 if(mode!="cases"){std::printf("PASS %s calls=%u bytes=%zu\n",mode.c_str(),compile_calls,expected.size());return 0;}
 auto key=Key();auto path=ShaderCachePath(key);auto valid=Read(path);CHECK(valid.size()==sizeof(ShaderCacheHeader)+expected.size());
 // Every compilation input and the loaded compiler's bytes participate in identity.
 CHECK(Key(source+"\n")!=key);CHECK(Key(source,"alternate")!=key);CHECK(Key(source,"main","vs_4_0")!=key);
 CHECK(Key(source,"main","vs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3)!=key);CHECK(Key(source,"main","vs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL1,1)!=key);
 auto changed=*compiler;changed[0]^=1;CHECK(ShaderCacheKey(source,"main","vs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL1,0,changed)!=key);
 CHECK(!ShaderCacheKey(std::string((4u<<20)+1,' '),"main","vs_5_0",0,0,*compiler));
 for(auto input:{std::pair{"alternate","vs_5_0"},std::pair{"main","vs_4_0"}}){unsigned n=compile_calls;D3D12Backend x;CHECK(Compile(x,source,input.first,input.second)&&compile_calls==n+1);}
 {unsigned n=compile_calls;D3D12Backend x;CHECK(Compile(x,source+"\n")&&compile_calls==n+1);}
 // Corrupt or wrong records must take the real compiler fallback and repair the cache.
 for(unsigned kind=0;kind<9;++kind){
  auto bad=valid;
  if(kind==0)bad.resize(17); // truncated header
  if(kind==1)bad[0]^=1; // magic
  if(kind==2)bad[8]^=1; // version
  if(kind==3)bad[16]^=1; // key identity
  if(kind==4)bad[48]^=1; // checksum
  if(kind==5)bad.back()^=1; // payload
  if(kind==6)bad.push_back(0); // trailing data
  if(kind==7){uint32_t huge=UINT32_MAX;std::memcpy(bad.data()+12,&huge,4);} // declared extent
  if(kind==8){ // Integrity-correct invalid DXBC: reject unsafe chunk extent.
   uint32_t huge=UINT32_MAX;std::memcpy(bad.data()+sizeof(ShaderCacheHeader)+32,&huge,4);
   ShaderDigest digest;CHECK(ShaderDigestOf(bad.data()+sizeof(ShaderCacheHeader),bad.size()-sizeof(ShaderCacheHeader),digest));std::memcpy(bad.data()+48,digest.data(),digest.size());
  }
  Write(path,bad);unsigned n=compile_calls;D3D12Backend x;CHECK(Bytes(Compile(x))==expected&&compile_calls==n+1);CHECK(Read(path)==valid);
 }
 // Oversized on-disk length is rejected before a blob allocation/read.
 {std::ofstream f(path,std::ios::binary|std::ios::trunc);f.seekp(sizeof(ShaderCacheHeader)+kShaderBlobLimit);f.put(0);}
 {unsigned n=compile_calls;D3D12Backend x;CHECK(Bytes(Compile(x))==expected&&compile_calls==n+1);CHECK(Read(path)==valid);}
 // Failed atomic replacement preserves the prior complete record and removes only our temp.
 HANDLE reader=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);CHECK(reader!=INVALID_HANDLE_VALUE);
 CHECK(!WriteShaderCache(key,code));CHECK(CloseHandle(reader));CHECK(Read(path)==valid);
 for(const auto& e:std::filesystem::directory_iterator(path.parent_path()))CHECK(e.path().filename().wstring().find(L".tmp.")==std::wstring::npos);
 // A non-directory cache root cannot be written; actual compilation must still succeed.
 auto owned_root=cache_root;auto blocked=owned_root/"not-a-directory";Write(blocked,{1,2,3,4});cache_root=blocked;
 {unsigned n=compile_calls;D3D12Backend x;CHECK(Bytes(Compile(x))==expected&&compile_calls==n+1);CHECK(Read(blocked)==std::vector<uint8_t>({1,2,3,4}));}
 cache_root=owned_root;
 // Cache admission limits do not reject otherwise valid HLSL compilation.
 {unsigned n=compile_calls;auto writes=g_perf.shader_cache_writes;D3D12Backend x;
  CHECK(Compile(x,std::string((4u<<20)+1,' ')+source)&&compile_calls==n+1);CHECK(g_perf.shader_cache_writes==writes);}
 // Invalid HLSL is not cached as a disk success; memory failure behavior stays unchanged.
 {unsigned n=compile_calls;auto writes=g_perf.shader_cache_writes;D3D12Backend x;CHECK(!Compile(x,"invalid hlsl")&&compile_calls==n+1);CHECK(!Compile(x,"invalid hlsl")&&compile_calls==n+1);CHECK(g_perf.shader_cache_writes==writes);CHECK(!std::filesystem::exists(ShaderCachePath(Key("invalid hlsl"))));}
 std::puts("PASS input identity, 10 corrupt/size fallbacks, write failures, atomic preservation, original compile failure");
}
'''


class ShaderCacheTests(unittest.TestCase):
    def test_actual_compile_cache_cross_process_and_failure_contracts(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ required')
        path = Path(os.environ.get('XBE_SHADER_CACHE_SOURCE', str(SDK / 'gpu/d3d12.cpp')))
        source = path.read_text(encoding='utf-8')
        perf = source[source.index('using PerfClock ='):source.index('// F3 captures only')]
        helpers = source[source.index('// Compiled host shaders only.'):source.index('ID3DBlob* D3D12Backend::Compile(')]
        compile_code = function(source, 'ID3DBlob* D3D12Backend::Compile(')
        hash_code = function((SDK / 'gpu/shaders.cpp').read_text(), 'uint64_t Hash(')
        fixture = PREAMBLE + perf + hash_code + helpers + '\n#define D3DCompile(...) (++compile_calls, D3DCompile(__VA_ARGS__))\n' + compile_code + '\n#undef D3DCompile\n' + DRIVER
        with tempfile.TemporaryDirectory(prefix='shader-cache-', dir=ROOT / 'build') as temp:
            folder = Path(temp)
            cpp, exe = folder / 'cache.cpp', folder / 'cache.exe'
            cpp.write_text(fixture, encoding='utf-8')
            result = subprocess.run([compiler, '-std=c++20', '-O1', '-fuse-ld=lld', str(cpp), '-ld3dcompiler', '-lbcrypt', '-o', str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for mode in ['cold', 'warm', 'cases', 'warm']:
                result = subprocess.run([str(exe), mode, str(folder / 'owned')], capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS', result.stdout)
                print(result.stdout.strip())
            # Two independent processes publish the same key without partial records or clobbered temporaries.
            racers = [subprocess.Popen([str(exe), 'race', str(folder / 'shared')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
            for process in racers:
                stdout, stderr = process.communicate(timeout=45)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            result = subprocess.run([str(exe), 'warm', str(folder / 'shared')], capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(list((folder / 'shared').rglob('*.tmp.*')))
            print('PASS concurrent process publication and subsequent real disk hit')


if __name__ == '__main__':
    unittest.main()
