"""Exercise the actual shared file service and its worker with controlled I/O stalls."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"

# Reusable by the original XACT staging oracle. No production scheduling hook:
# retaining File::io stalls the real worker before the real host transfer.
HARNESS = r'''
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <chrono>
#include <filesystem>
#include <future>
#include "kernel/kernel.h"
#include "kernel/exports.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x); std::exit(90); } } while(0)
alignas(64) static uint8_t memory[0x1000000];
uint8_t* kernel::g_base=memory;
static kernel::KernelFn exports[400];
static std::mutex handles_lock, dispatch_lock;
static std::condition_variable changed;
static std::unordered_map<uint32_t,kernel::ObjectRef> handles;
static uint32_t next_handle=0x1000;
static thread_local kernel::ThreadRef active;
void logx::Write(Level,const char*,...) {}
void logx::Flush() {}
namespace kernel {
void RegisterExport(uint32_t n,const char*,KernelFn f) { CHECK(n<400);exports[n]=f; }
Thread* Current() { return active.get(); }
ThreadRef CurrentRef() { return active; }
uint32_t NewHandle(ObjectRef p) { std::lock_guard l(handles_lock);auto h=next_handle;next_handle+=4;handles[h]=p;return h; }
ObjectRef FromHandle(uint32_t h) { std::lock_guard l(handles_lock);auto it=handles.find(h);return it==handles.end()?nullptr:it->second; }
bool CloseHandle(uint32_t h) { std::lock_guard l(handles_lock);return handles.erase(h)!=0; }
int32_t SetEvent(Object& o) { std::lock_guard l(dispatch_lock);int old=o.signal;o.signal=1;changed.notify_all();return old; }
int32_t ResetEvent(Object& o) { std::lock_guard l(dispatch_lock);int old=o.signal;o.signal=0;return old; }
void SignalChanged() { changed.notify_all(); }
void QueueApc(Thread& t,uint32_t fn,uint32_t a,uint32_t b,uint32_t c) {
    std::lock_guard l(t.apc_lock);t.apcs.push_back({fn,a,b,c});changed.notify_all();
}
}
#include "kernel/files.cpp"
static uint32_t Call(unsigned ordinal,std::initializer_list<uint32_t> args,uint32_t sp=0xF00000) {
    X86Context c{};c.esp=sp;kernel::W32(sp,0xABCDEF01);unsigned i=0;
    for(auto v:args)kernel::W32(sp+4+4*i++,v);
    CHECK(exports[ordinal]);exports[ordinal](c,memory);CHECK(c.esp==sp+4+4*i);return c.eax;
}
static void Await(const std::function<bool()>& ready) {
    auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    std::unique_lock l(dispatch_lock);
    while(!ready())CHECK(changed.wait_until(l,until)!=std::cv_status::timeout);
}
static uint32_t Status(uint32_t p) { return __atomic_load_n(reinterpret_cast<uint32_t*>(memory+p),__ATOMIC_ACQUIRE); }
static uint32_t Open(const std::string& path,uint32_t options,bool use_open=false) {
    using namespace kernel;CHECK(path.size()<400);std::memcpy(memory+0x500,path.c_str(),path.size());
    W16(0x400,uint16_t(path.size()));W16(0x402,uint16_t(path.size()));W32(0x404,0x500);
    W32(0x300,0);W32(0x304,0x400);W32(0x308,0);
    auto status=use_open?Call(202,{0x200,0x80100080,0x300,0x220,1,options})
                        :Call(190,{0x200,0x80100080,0x300,0x220,0,0x80,1,1,options});
    CHECK(status==kSuccess);return R32(0x200);
}
'''

DRIVER = r'''
int main(int argc,char** argv) {
    using namespace kernel;CHECK(argc==2);std::filesystem::path folder=argv[1];
    std::filesystem::create_directories(folder);std::vector<uint8_t> content(0x8000);
    for(size_t i=0;i<content.size();i++)content[i]=uint8_t(i*37+11);
    {auto* fp=std::fopen((folder/"source.bin").string().c_str(),"wb");CHECK(fp);CHECK(std::fwrite(content.data(),1,content.size(),fp)==content.size());std::fclose(fp);}
    MountDefaults(folder.string(),(folder/"data").string());active=std::make_shared<Thread>();auto issuer=active;
    auto other=std::make_shared<Thread>();
    for(uint32_t option:{0x10u,0x20u,0x48u}) {
        auto h=Open("D:\\source.bin",option);auto f=FileFromHandle(h);CHECK(f&&f->options==option);
        CHECK(Call(211,{h,0x220,0x240,4,16})==0&&R32(0x240)==(option&0x103E));CloseHandle(h);
        h=Open("D:\\source.bin",option,true);CHECK(FileFromHandle(h)->options==option);CloseHandle(h);
    }
    // Directory and disc-open construction retain options too (disc data reader is unchanged).
    std::filesystem::create_directories(folder/"subdir");
    auto directory=Open("D:\\subdir",0x21);CHECK(FileFromHandle(directory)->options==0x21);CloseHandle(directory);
    Disc::Entry entry;entry.name="source.bin";entry.size=0x8000;
    CHECK(OpenOnDisc(&entry,"D:\\source.bin",0x200,0x220,1,0x48)==0);
    CHECK(FileFromHandle(R32(0x200))->options==0x48);CloseHandle(R32(0x200));
    // Both synchronous modes still finish before returning, including current-position semantics.
    for(uint32_t option:{0x10u,0x20u}) {
        auto h=Open("D:\\source.bin",option);W64(0x280,13);
        CHECK(Call(219,{h,0,0,0,0x1000,0x2000,17,0x280})==0);
        CHECK(R32(0x1000)==0&&R32(0x1004)==17&&std::memcmp(memory+0x2000,content.data()+13,17)==0);
        CHECK(Call(219,{h,0,0,0,0x1000,0x2000,9,0})==0);
        CHECK(std::memcmp(memory+0x2000,content.data()+30,9)==0);CloseHandle(h);
    }
    auto h=Open("D:\\source.bin",0x48);auto f=FileFromHandle(h);
    auto event=std::make_shared<Object>(ObjType::Event);event->notification=true;event->signal=1;auto eh=NewHandle(event);
    std::unique_lock stall(f->io);W64(0x280,31);std::memset(memory+0x2000,0xCC,128);
    CHECK(Call(219,{h,eh,0x1234,0xCAFE,0x1000,0x2000,128,0x280})==kPending);
    CHECK(Status(0x1000)==kPending&&R32(0x1004)==0&&event->signal==0&&f->signal==0);
    CHECK(memory[0x2000]==0xCC&&issuer->apcs.empty());
    // Offset and issuing-thread context are captured, and closing handles does not invalidate retained objects.
    W64(0x280,9999);active=other;CHECK(CloseHandle(eh));CHECK(CloseHandle(h));stall.unlock();f.reset();
    Await([&]{return event->signal==1;});CHECK(Status(0x1000)==0&&R32(0x1004)==128);
    CHECK(std::memcmp(memory+0x2000,content.data()+31,128)==0);
    {std::unique_lock l(issuer->apc_lock);l.unlock();Await([&]{std::lock_guard a(issuer->apc_lock);return !issuer->apcs.empty();});}
    {std::lock_guard l(issuer->apc_lock);CHECK(issuer->apcs.size()==1);CHECK((issuer->apcs.front()==std::array<uint32_t,4>{0x1234,0xCAFE,0x1000,0}));issuer->apcs.clear();}
    CHECK(other->apcs.empty());active=issuer;
    h=Open("D:\\source.bin",0x48);f=FileFromHandle(h);stall=std::unique_lock(f->io);
    // Descriptor entries, not the descriptor's guest address, survive return.
    W64(0x280,100);W32(0x3000,0x4000);W32(0x3008,0x6000);
    CHECK(Call(220,{h,0,0,0,0x1100,0x3000,0x1100,0x280})==kPending);
    W32(0x3000,0x8000);W32(0x3008,0xA000);W64(0x280,200);stall.unlock();
    Await([&]{return f->signal==1;});CHECK(Status(0x1100)==0&&R32(0x1104)==0x1100);
    CHECK(std::memcmp(memory+0x4000,content.data()+100,0x1000)==0);
    CHECK(std::memcmp(memory+0x6000,content.data()+100+0x1000,0x100)==0&&memory[0x8000]==0);
    // Short read, EOF, zero length, invalid handles and asynchronous offset rejection.
    for(auto pair:{std::pair<uint32_t,uint32_t>{0x7FF0,16},{0x8000,0}}) {
        W64(0x280,pair.first);CHECK(Call(219,{h,0,0,0,0x1200,0x2000,32,0x280})==kPending);
        Await([&]{return f->signal==1;});CHECK(R32(0x1204)==pair.second);
        CHECK(Status(0x1200)==(pair.second?uint32_t(kSuccess):uint32_t(kEndOfFile)));
    }
    W64(0x280,0);CHECK(Call(219,{h,0,0,0,0x1200,0,0,0x280})==kPending);
    Await([&]{return f->signal==1;});CHECK(Status(0x1200)==0&&R32(0x1204)==0);
    CHECK(Call(219,{h,0,0,0,0x1200,0x2000,1,0})==kInvalidParameter);
    W64(0x280,UINT64_MAX);CHECK(Call(219,{h,0,0,0,0x1200,0x2000,1,0x280})==kInvalidParameter);
    CHECK(Call(219,{0xBAD,0,0,0,0x1200,0x2000,1,0x280})==kInvalidHandle);
    // Several pending requests retain different offsets and separate completion slots.
    stall=std::unique_lock(f->io);
    for(uint32_t i=0;i<8;i++){W64(0x280,i*99);CHECK(Call(219,{h,0,0,0,0x1300+i*8,0xB000+i*64,64,0x280})==kPending);}
    stall.unlock();Await([&]{return Status(0x1338)!=kPending;});
    for(uint32_t i=0;i<8;i++){CHECK(Status(0x1300+i*8)==0&&R32(0x1304+i*8)==64);CHECK(std::memcmp(memory+0xB000+i*64,content.data()+i*99,64)==0);}
    // Concurrent issuers carry independent stack/offset/IOSB values into the one real queue.
    stall=std::unique_lock(f->io);std::vector<std::thread> submitters;
    for(uint32_t i=0;i<8;i++)submitters.emplace_back([&,i]{
        W64(0x1800+i*8,500+i*71);
        CHECK(Call(219,{h,0,0,0,0x1900+i*8,0x10000+i*64,64,0x1800+i*8},0xE00000+i*0x100)==kPending);
    });
    for(auto& t:submitters)t.join();stall.unlock();
    Await([&]{for(uint32_t i=0;i<8;i++)if(Status(0x1900+i*8)==kPending)return false;return true;});
    for(uint32_t i=0;i<8;i++)CHECK(Status(0x1900+i*8)==0&&std::memcmp(memory+0x10000+i*64,content.data()+500+i*71,64)==0);
    // Write/gather share captured descriptors and the same completion rules.
    stall=std::unique_lock(f->io);W64(0x280,0x100);W32(0x3000,0x4000);W32(0x3008,0x6000);
    CHECK(Call(237,{h,0,0,0,0x1400,0x3000,0x1010,0x280})==kPending);W64(0x280,0);W32(0x3000,0xA000);stall.unlock();
    Await([&]{return Status(0x1400)!=kPending;});CHECK(Status(0x1400)==0&&R32(0x1404)==0x1010);
    W64(0x280,0x100);CHECK(Call(219,{h,0,0,0,0x1400,0xC000,0x1010,0x280})==kPending);
    Await([&]{return Status(0x1400)!=kPending;});CHECK(std::memcmp(memory+0xC000,memory+0x4000,0x1000)==0&&std::memcmp(memory+0xD000,memory+0x6000,0x10)==0);
    CloseHandle(h);
    // A blocked async handle does not turn a different synchronous handle into a queued call.
    h=Open("D:\\source.bin",0x48);f=FileFromHandle(h);auto sync=Open("D:\\source.bin",0x20);stall=std::unique_lock(f->io);
    W64(0x280,0);CHECK(Call(219,{h,0,0,0,0x1500,0xE000,32,0x280})==kPending);
    CHECK(Call(219,{sync,0,0,0,0x1600,0xE100,32,0x280})==0&&Status(0x1500)==kPending);
    stall.unlock();Await([&]{return Status(0x1500)!=kPending;});CloseHandle(h);CloseHandle(sync);
    std::puts("actual async file I/O worker, open modes, captured args, events, issuer APC, EOF, scatter/gather, close and ordering passed");
}
'''


class AsyncFileIoTests(unittest.TestCase):
    def test_actual_worker_modes_completion_and_lifetimes(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ required")
        with tempfile.TemporaryDirectory(prefix="xbexbe-async-io-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(HARNESS + DRIVER, encoding="utf-8")
            result = subprocess.run([compiler, "-std=c++20", "-march=x86-64-v2", "-O1", "-fuse-ld=lld",
                                     "-I", str(SDK), str(source), str(SDK / "kernel/disc.cpp"),
                                     "-o", str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe), str(folder / "disk")], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("actual async file I/O worker", result.stdout)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
