"""Network co-op host: wire format, single-guest session rules and the real UDP host path."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOML = Path(os.environ.get("DARKWATCH_TOML_INCLUDE", ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"))

# Only Pad and the log macros are needed; the host module must not depend on more runtime.
INPUT_H = r'''
#pragma once
#include <cstdint>
namespace input {
struct Pad { bool connected = false; uint16_t buttons = 0; uint8_t analog[8] = {}; int16_t lx = 0, ly = 0, rx = 0, ry = 0; };
}
'''
LOG_H = r'''
#pragma once
#include <atomic>
inline std::atomic<int> g_errors{0}, g_reports{0};
#define LOGE(...) (++g_errors)
#define LOGR(...) (++g_reports)
'''

FIXTURE = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <toml++/toml.hpp>
#include "core/input.h"
#include "core/log.h"
#include "common/coop.h"
#include "tools/coop_keys.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line%d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
using namespace darkwatch::coop;

static Packet Round(const Packet& in){uint8_t d[kMaxPacket];size_t n=Encode(in,d);CHECK(n);Packet out;CHECK(Decode(d,n,out));return out;}
static void Protocol(){
 Packet h;h.type=Type::Hello;h.token=0xA1B2C3D4;h.sequence=7;CHECK(SetCode(h,"lantern"));
 auto r=Round(h);CHECK(r.type==Type::Hello&&r.token==0xA1B2C3D4&&r.sequence==7&&CodeMatches(r,"lantern")&&!CodeMatches(r,"lanter")&&!CodeMatches(r,"lantern2"));
 CHECK(!CodeMatches(r,"")&&!SetCode(h,"")&&!SetCode(h,std::string(33,'x'))&&SetCode(h,std::string(32,'x')));
 Packet p;p.type=Type::Pad;p.pad.buttons=0x80F1;for(int i=0;i<8;++i)p.pad.analog[i]=uint8_t(i*31);p.pad.lx=-32768;p.pad.ly=32767;p.pad.rx=-1;p.pad.ry=12345;
 r=Round(p);CHECK(r.pad.buttons==0x80F1&&r.pad.analog[7]==217&&r.pad.lx==-32768&&r.pad.ly==32767&&r.pad.rx==-1&&r.pad.ry==12345);
 Packet w;w.type=Type::Welcome;w.status=Status::Busy;CHECK(Round(w).status==Status::Busy);
 Packet m;m.type=Type::Rumble;m.left=65535;m.right=3;r=Round(m);CHECK(r.left==65535&&r.right==3);
 Packet b;b.type=Type::Bye;CHECK(Round(b).type==Type::Bye);
 uint8_t d[kMaxPacket];size_t n=Encode(p,d);Packet out;
 CHECK(!Decode(d,n-1,out)&&!Decode(d,n+1,out)&&!Decode(d,15,out));
 d[0]^=1;CHECK(!Decode(d,n,out));d[0]^=1;
 d[5]=9;CHECK(!Decode(d,n,out));d[5]=uint8_t(Type::Pad);
 d[4]=2;CHECK(!Decode(d,n,out));  // only a Hello survives a version mismatch
 n=Encode(h,d);d[4]=2;CHECK(Decode(d,n,out)&&out.version==2&&out.type==Type::Hello);
 n=Encode(w,d);d[kHeaderBytes]=9;CHECK(!Decode(d,n,out));
 CHECK(Newer(1,0)&&!Newer(0,1)&&!Newer(5,5)&&Newer(0,0xFFFFFFFF)&&!Newer(0xFFFFFFFF,0));
}

static void Keys(){using darkwatch::coop::keys::Merge;
 auto only=[](std::initializer_list<int> keys){return [keys](uint8_t k){for(int key:keys)if(key==k)return true;return false;};};
 PadState p;Merge(p,only({}),0,0,8000);CHECK(p.buttons==0&&p.lx==0&&p.ly==0&&p.rx==0&&p.ry==0);
 p={};Merge(p,only({0x1B,0x09,'F',0x26}),0,0,8000);CHECK(p.buttons==(16|32|128|1));  // Start, Back, right thumb, up
 p={};Merge(p,only({0x0D}),0,0,8000);CHECK(p.buttons==16);  // Enter is also Start
 p={};Merge(p,only({'E','B','R','Q','G',0x10,0x02,0x01}),0,0,8000);for(int i=0;i<8;++i)CHECK(p.analog[i]==255);
 p={};Merge(p,only({0x20}),0,0,8000);CHECK(p.analog[0]==255&&p.analog[1]==0);
 p={};Merge(p,only({'W'}),0,0,8000);CHECK(p.lx==0&&p.ly==32767);
 p={};Merge(p,only({'S','A'}),0,0,8000);CHECK(p.lx==-23170&&p.ly==-23170);
 p={};Merge(p,only({'W','S'}),0,0,8000);CHECK(p.lx==0&&p.ly==0);
 p={};p.lx=1000;p.rx=-2000;Merge(p,only({}),0,0,8000);CHECK(p.lx==1000&&p.rx==-2000);  // a controller keeps its sticks
 p={};Merge(p,only({}),3,-2,8000);CHECK(p.rx==6400&&p.ry==4266);  // mouse up looks up
 p={};Merge(p,only({}),1000,1000,8000);CHECK(p.rx==32767&&p.ry==-32768);
 p={};p.rx=500;Merge(p,only({}),5,0,0);CHECK(p.rx==500);Merge(p,only({}),5,0,300000);CHECK(p.rx==500);  // no or stale timing
}

static Packet Hello(uint32_t token,const char* code,uint32_t seq=0){Packet h;h.type=Type::Hello;h.token=token;h.sequence=seq;SetCode(h,code);return h;}
static Packet PadPacket(uint32_t token,uint32_t seq,uint16_t buttons){Packet p;p.type=Type::Pad;p.token=token;p.sequence=seq;p.pad.buttons=buttons;return p;}
static void Sessions(){
 Session s("code");Address a{0x0100007F,1000},b{0x0200007F,2000};PadState pad;
 CHECK(!s.Active(0)&&!s.Current(pad,0));
 auto r=s.Receive(Hello(5,"nope"),a,10);CHECK(r&&r->type==Type::Welcome&&r->status==Status::BadCode&&r->token==5&&!s.Active(10));
 Packet old=Hello(5,"code");old.version=0;r=s.Receive(old,a,10);CHECK(r&&r->status==Status::BadVersion&&!s.Active(10));
 CHECK(!s.Receive(PadPacket(5,1,1),a,10)&&!s.Active(10));  // pads need a session
 r=s.Receive(Hello(5,"code",100),a,20);CHECK(r&&r->status==Status::Accepted&&s.Active(20)&&s.Current(pad,20)&&pad.buttons==0);
 CHECK(s.Guest(20)==a);
 r=s.Receive(Hello(9,"code"),b,30);CHECK(r&&r->status==Status::Busy&&s.Guest(30)==a);
 s.Receive(PadPacket(5,101,0x11),a,40);CHECK(s.Current(pad,40)&&pad.buttons==0x11);
 s.Receive(PadPacket(5,100,0x22),a,50);CHECK(s.Current(pad,50)&&pad.buttons==0x11);  // reordered
 s.Receive(PadPacket(6,102,0x33),a,60);s.Receive(PadPacket(5,103,0x44),b,60);CHECK(s.Current(pad,60)&&pad.buttons==0x11);
 r=s.Receive(Hello(5,"code",999),a,70);CHECK(r&&r->status==Status::Accepted);  // repeated hello keeps state
 s.Receive(PadPacket(5,102,0x55),a,70);CHECK(s.Current(pad,70)&&pad.buttons==0x55);
 CHECK(s.Active(70+kTimeoutMs-1)&&!s.Active(70+kTimeoutMs)&&!s.Current(pad,70+kTimeoutMs));
 r=s.Receive(Hello(9,"code",0),b,70+kTimeoutMs);CHECK(r&&r->status==Status::Accepted&&s.Guest(70+kTimeoutMs)==b&&s.Current(pad,70+kTimeoutMs)&&pad.buttons==0);
 const uint64_t t=70+kTimeoutMs;
 r=s.Receive(Hello(10,"code",0),b,t+1);CHECK(r&&r->status==Status::Accepted&&s.Token()==10);  // guest restarted
 s.Receive(PadPacket(9,5,1),b,t+2);CHECK(s.Current(pad,t+2)&&pad.buttons==0);
 Packet bye;bye.type=Type::Bye;bye.token=10;s.Receive(bye,b,t+3);CHECK(!s.Active(t+3));
 r=s.Receive(Hello(11,"code"),a,t+4);CHECK(r&&r->status==Status::Accepted);
}

struct Guest{SOCKET s;sockaddr_in host{};
 explicit Guest(uint16_t port){s=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);CHECK(s!=INVALID_SOCKET);DWORD t=500;setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(const char*)&t,sizeof(t));
  host.sin_family=AF_INET;host.sin_port=htons(port);host.sin_addr.s_addr=htonl(INADDR_LOOPBACK);}
 void Send(const Packet& p){uint8_t d[kMaxPacket];size_t n=Encode(p,d);CHECK(sendto(s,(const char*)d,int(n),0,(sockaddr*)&host,sizeof(host))==int(n));}
 bool Receive(Packet& p,Type type){for(int i=0;i<40;++i){uint8_t d[kMaxPacket+1];int n=recv(s,(char*)d,sizeof(d),0);if(n<=0)return false;if(Decode(d,size_t(n),p)&&p.type==type)return true;}return false;}
};
static input::Pad Local(){input::Pad p;p.connected=true;p.buttons=0x0F;p.lx=100;return p;}
static bool Wait(auto done){for(int i=0;i<200;++i){if(done())return true;std::this_thread::sleep_for(std::chrono::milliseconds(5));}return false;}

static void HostPath(uint16_t port){
 g_errors=0;g_reports=0;
 Start();CHECK(g_errors==0&&g_reports==0);  // default settings never open a socket
 Load(&static_cast<const toml::table&>(toml::parse("coop_host=true\n")));Start();CHECK(g_errors==1);  // a code is required
 Load(&static_cast<const toml::table&>(toml::parse("coop_host=true\ncoop_port=80\ncoop_code='"+std::string(33,'x')+"'\n")));
 CHECK(Snapshot().port==1024&&Snapshot().code.empty());
 Load(&static_cast<const toml::table&>(toml::parse("coop_host='yes'\ncoop_port='41330'\ncoop_code=5\n")));
 CHECK(!Snapshot().host&&Snapshot().port==kDefaultPort&&Snapshot().code.empty()&&!Snapshot().campaign);
 auto text="coop_host=true\ncoop_port="+std::to_string(port)+"\ncoop_code='lantern'\ncoop_campaign=true\n";
 auto table=toml::parse(text);Load(&static_cast<const toml::table&>(table));
 toml::table saved;Save(&saved);CHECK(saved["coop_host"].value_or(false)&&saved["coop_port"].value_or(0)==port&&saved["coop_code"].value_or(std::string())=="lantern"&&saved["coop_campaign"].value_or(false));
 Start();CHECK(g_errors==1&&g_reports==1);Start();CHECK(g_reports==1);  // one host per process
 auto pad=Local();Pad(1,pad);CHECK(pad.buttons==0x0F&&pad.lx==100);  // no guest: local split screen
 uint16_t l=10,r=20;Rumble(1,l,r);CHECK(l==10&&r==20);
 Guest g(port);Packet p;
 g.Send(Hello(77,"wrong"));CHECK(g.Receive(p,Type::Welcome)&&p.status==Status::BadCode&&p.token==77);
 g.Send(Hello(77,"lantern",50));CHECK(g.Receive(p,Type::Welcome)&&p.status==Status::Accepted&&p.token==77);
 CHECK(Wait([]{input::Pad q;Pad(1,q);return q.connected;}));
 pad={};Pad(1,pad);CHECK(pad.connected&&pad.buttons==0);  // neutral until the first pad
 Packet state=PadPacket(77,51,0x1234);state.pad.analog[0]=255;state.pad.analog[7]=128;state.pad.lx=-5;state.pad.ry=-32768;g.Send(state);
 CHECK(Wait([]{input::Pad q;Pad(1,q);return q.buttons==0x1234;}));
 pad={};Pad(1,pad);CHECK(pad.connected&&pad.analog[0]==255&&pad.analog[7]==128&&pad.lx==-5&&pad.ry==-32768);
 pad=Local();Pad(0,pad);CHECK(pad.buttons==0x0F);pad=Local();Pad(2,pad);CHECK(pad.buttons==0x0F);
 pad=Local();Pad(1,pad);CHECK(pad.buttons==0x1234&&pad.lx==-5);  // the guest replaces a local port-1 pad
 l=40000;r=123;Rumble(1,l,r);CHECK(l==0&&r==0);
 CHECK(g.Receive(p,Type::Rumble)&&p.token==77);
 while(p.left!=40000)CHECK(g.Receive(p,Type::Rumble));CHECK(p.right==123);
 Guest other(port);other.Send(Hello(88,"lantern"));CHECK(other.Receive(p,Type::Welcome)&&p.status==Status::Busy);
 Packet bye;bye.type=Type::Bye;bye.token=77;bye.sequence=52;g.Send(bye);
 CHECK(Wait([]{input::Pad q=Local();Pad(1,q);return q.buttons==0x0F;}));
 l=7;r=8;Rumble(1,l,r);CHECK(l==7&&r==8);
 other.Send(Hello(88,"lantern"));CHECK(other.Receive(p,Type::Welcome)&&p.status==Status::Accepted);
 auto silent=std::chrono::steady_clock::now();  // a silent guest unplugs port 1
 CHECK(Wait([]{input::Pad q;Pad(1,q);return q.connected;}));
 while(true){input::Pad q;Pad(1,q);if(!q.connected)break;CHECK(std::chrono::steady_clock::now()-silent<std::chrono::milliseconds(kTimeoutMs+500));std::this_thread::sleep_for(std::chrono::milliseconds(20));}
 CHECK(std::chrono::steady_clock::now()-silent>=std::chrono::milliseconds(kTimeoutMs-50));
}

int main(int argc,char** argv){
 WSADATA wsa;CHECK(!WSAStartup(MAKEWORD(2,2),&wsa));
 Protocol();Keys();Sessions();HostPath(uint16_t(std::atoi(argv[1])));
 std::puts("coop: wire format, guest keys, session rules and live UDP host passed");
}
'''


def free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CoopTests(unittest.TestCase):
    def test_wire_session_and_live_host(self):
        compiler = shutil.which("clang++") or shutil.which("g++")
        self.assertIsNotNone(compiler)
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="coop-", dir=ROOT / "build") as name:
            folder = Path(name)
            (folder / "core").mkdir()
            (folder / "core/input.h").write_text(INPUT_H)
            (folder / "core/log.h").write_text(LOG_H)
            cpp, exe = folder / "test.cpp", folder / "test.exe"
            cpp.write_text(FIXTURE)
            linker = ["-fuse-ld=lld"] if "clang" in Path(compiler).name else []
            result = subprocess.run([compiler, "-std=c++20", "-O1", *linker, "-I", str(folder),
                "-I", str(ROOT / "xbexbe/src"), "-I", str(TOML),
                str(cpp), str(ROOT / "xbexbe/src/common/coop.cpp"), "-lws2_32", "-o", str(exe)],
                capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe), str(free_port())], cwd=folder, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
