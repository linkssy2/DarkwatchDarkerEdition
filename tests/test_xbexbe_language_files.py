"""Actual kernel opens, reads and metadata select optional media only on D:."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_xbexbe_async_file_io import HARNESS, ROOT, SDK

DRIVER = r'''
static void Write(const std::filesystem::path& path,const char* text){
 std::filesystem::create_directories(path.parent_path());auto* f=std::fopen(path.string().c_str(),"wb");
 CHECK(f);std::fputs(text,f);std::fclose(f);
}
static void Read(const char* path,const char* expected){
 using namespace kernel;auto h=Open(path,0x20);auto n=uint32_t(std::strlen(expected));
 CHECK(Call(211,{h,0x220,0x240,24,5})==0);CHECK(R64(0x248)==n);
 W64(0x280,0);CHECK(Call(219,{h,0,0,0,0x1000,0x2000,n+1,0x280})==0);
 CHECK(R32(0x1004)==n&&!std::memcmp(memory+0x2000,expected,n));CHECK(CloseHandle(h));
}
static void Name(const char* path){
 using namespace kernel;const auto n=uint16_t(std::strlen(path));CHECK(n<400);
 std::memcpy(memory+0x500,path,n);W16(0x400,n);W16(0x402,n);W32(0x404,0x500);
 W32(0x300,0);W32(0x304,0x400);W32(0x308,0);
}
static uint32_t Rename(uint32_t handle,const char* target){
 using namespace kernel;Name(target);W32(0x600,1);W32(0x604,0);
 W16(0x608,R16(0x400));W16(0x60A,R16(0x402));W32(0x60C,0x500);
 return Call(226,{handle,0x220,0x600,16,10});
}
static void CheckReadOnly(){
 using namespace kernel;Name("D:\\audioDlg.pck");
 for(uint32_t disposition:{0u,2u,4u,5u})
  CHECK(Call(190,{0x200,0x80100080,0x300,0x220,0,0x80,1,disposition,0x20})==kAccessDenied);
 CHECK(Call(190,{0x200,0x80100080,0x300,0x220,0,0x80,1,1,0x1020})==kAccessDenied);
 CHECK(Call(202,{0x200,0x80100080,0x300,0x220,1,0x1020})==kAccessDenied);
 for(uint32_t access:{0x40000000u,0x10000000u,2u,4u,0x10u,0x100u,0x10000u,0x40000u,0x80000u}){
  CHECK(Call(190,{0x200,access,0x300,0x220,0,0x80,1,1,0x20})==kAccessDenied);
  CHECK(Call(202,{0x200,access,0x300,0x220,1,0x20})==kAccessDenied);
 }
 CHECK(Call(195,{0x300})==kAccessDenied);
 // Both open APIs and synchronous/asynchronous transfers enforce the same protection.
 for(bool open:{false,true})for(uint32_t options:{0x20u,0x48u}){
  auto h=Open("D:\\audioDlg.pck",options,open);CHECK(FileFromHandle(h)->read_only);
  W64(0x280,0);W32(0x3000,0x2000);memory[0x2000]='X';
  CHECK(Call(236,{h,0,0,0,0x1000,0x2000,1,0x280})==kAccessDenied);
  CHECK(Call(237,{h,0,0,0,0x1000,0x3000,1,0x280})==kAccessDenied);
  for(uint32_t cls:{19u,20u,13u}){W64(0x600,1);CHECK(Call(226,{h,0x220,0x600,8,cls})==kAccessDenied);}
  CHECK(Rename(h,"E:\\moved.pck")==kAccessDenied);
  W64(0x600,0);CHECK(Call(226,{h,0x220,0x600,8,14})==kSuccess);
  CHECK(CloseHandle(h));
 }
 Name("D:\\audioDlg.pck");
 CHECK(Call(190,{0x200,0x80100080,0x300,0x220,0,0x80,1,3,0x20})==kSuccess);
 CHECK(FileFromHandle(R32(0x200))->read_only);CHECK(CloseHandle(R32(0x200)));
 Read("D:\\audioDlg.pck","Spanish dialogue");
}
int main(int argc,char**argv){
 using namespace kernel;CHECK(argc==2);std::filesystem::path root=argv[1],disc=root/"disc",overlay=root/"es";
 Write(disc/"audioDlg.pck","English");Write(disc/"Movies1.pck","Original movie");
 Write(disc/"nested/audioDlg.pck","Original nested");Write(overlay/"audioDlg.pck","Spanish dialogue");
 MountDefaults(disc.string(),(root/"data").string());
 CreateSymbolicLink("\\??\\E:","\\Device\\Harddisk0\\Partition1");
 Read("D:\\audioDlg.pck","English");SetGameFileOverlay(overlay.string());
 Read("D:\\AUDIODLG.PCK","Spanish dialogue");Read("D:\\Movies1.pck","Original movie");
 Read("D:\\nested\\audioDlg.pck","Original nested");Read("D:\\nested\\..\\audioDlg.pck","English");
 auto save=Resolve("E:\\audioDlg.pck",0);CHECK(!save.host.empty()&&save.host!=(overlay/"audioDlg.pck").string());
 Write(save.host,"Saved game");Read("E:\\audioDlg.pck","Saved game");
 CheckReadOnly();
 // A writable save must not be allowed to overwrite an overlay through a rename.
 auto h=Open("E:\\audioDlg.pck",0x20);CHECK(!FileFromHandle(h)->read_only);
 CHECK(Rename(h,"D:\\audioDlg.pck")==kAccessDenied);
 W64(0x280,0);std::memcpy(memory+0x2000,"saved game",10);
 CHECK(Call(236,{h,0,0,0,0x1000,0x2000,10,0x280})==kSuccess);CHECK(CloseHandle(h));
 Read("E:\\audioDlg.pck","saved game");Read("D:\\audioDlg.pck","Spanish dialogue");
 const auto traversal=Resolve("D:\\..\\es\\audioDlg.pck",0).host;
 SetGameFileOverlay("");CHECK(Resolve("D:\\..\\es\\audioDlg.pck",0).host==traversal);
 Read("D:\\audioDlg.pck","English");
 std::puts("actual optional media reads, English/save fallbacks and write/delete/rename/truncate protection passed");
}
'''

class LanguageFilesTests(unittest.TestCase):
    def test_actual_file_service(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="language-files-") as tmp:
            folder = Path(tmp)
            cpp, exe = folder / "test.cpp", folder / "test.exe"
            cpp.write_text(HARNESS + DRIVER)
            result = subprocess.run([compiler, "-std=c++20", "-march=x86-64-v2", "-O1", "-fuse-ld=lld",
                                     "-I", str(SDK), str(cpp), str(SDK / "kernel/disc.cpp"), "-o", str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run = subprocess.run([str(exe), str(folder / "data")], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout.strip())

if __name__ == "__main__":
    unittest.main()
