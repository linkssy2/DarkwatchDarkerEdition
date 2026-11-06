"""Exercise the real framing classifier/scopes; SDK geometry is tested separately."""
from pathlib import Path
import hashlib
import unittest
from test_xbexbe_graphics_cinematic import compile_and_run

ROOT = Path(__file__).resolve().parents[1]


class MenuAspectTests(unittest.TestCase):
    def test_actual_root_classification_and_scoped_state(self):
        compile_and_run(self, SOURCE, 'original menu canvas passed')


SOURCE = r'''
#include "graphics_presentation.cpp"
#include <cstdio>
#include <cstdlib>
#include <set>
#include <stdexcept>
static uint8_t memory[0x500000];
static unsigned cases,calls;
static std::set<uint32_t> blocked;
static darkwatch::view::Settings settings;
static bool want_overlay,want_safe,want_original,throws;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"case%u line%d: %s\n",cases,__LINE__,#x);std::exit(90);}}while(0)
namespace d3d {
gpu::State& State(){static gpu::State state;return state;}
std::recursive_mutex& Lock(){static std::recursive_mutex lock;return lock;}
}
darkwatch::view::Settings darkwatch::view::Snapshot(uint32_t){return settings;}
bool mem::IsCommitted(uint32_t p){return p<sizeof(memory)&&!blocked.contains(p);}
static void W(uint32_t p,uint32_t v){std::memcpy(memory+p,&v,4);}
static void Original(X86Context& c,uint8_t* b){
 CHECK(b==memory);auto& s=d3d::State();++calls;
 CHECK(s.presentation_overlay==want_overlay&&s.presentation_safe_area==want_safe&&s.presentation_original_aspect==want_original);
 if(throws)throw std::runtime_error("test renderer failure");
 c.esp+=8;c.eax=0xABCDEF; // Observe that wrappers preserve the native call's ABI effects.
}
X86_FUNC(__imp__sub_000E4EBD){Original(ctx,base);}
X86_FUNC(__imp__sub_001EC5F4){Original(ctx,base);}
X86_FUNC(__imp__sub_0021B0D1){Original(ctx,base);}
X86_FUNC(__imp__sub_000EF592){Original(ctx,base);}
X86_FUNC(__imp__sub_00326CD1){Original(ctx,base);}
X86_FUNC(__imp__sub_001F16EF){Original(ctx,base);}
X86_FUNC(__imp__sub_001ED841){Original(ctx,base);}
X86_FUNC(__imp__sub_00132B60){CHECK(false);}
X86_FUNC(__imp__sub_00130D70){CHECK(false);}
constexpr uint32_t manager=0x10000,root=0x20000,other=0x21000,table=0x30000,camera=0x40000,stack=0x50000;
static X86Context Setup(){
 std::memset(memory,0,sizeof(memory));blocked.clear();settings={};settings.original_ui_aspect=true;
 d3d::State().presentation_overlay=d3d::State().presentation_safe_area=d3d::State().presentation_original_aspect=false;
 W(0x4AD664,manager);W(manager+8,1);W(manager+12,root);W(root,table);W(other,table);W(table+0x30,0x1EC5F4);
 W(0x427770,0xD955F);W(0x43FB70,0x21B0D1);W(0x42A4F0,0x1EC5F4);W(stack+4,camera);
 X86Context c{};c.ecx=root;c.esp=stack;c.ebp=0x45678;c.esi=0x98765;return c;
}
static void Run(X86Context c,X86Func& f,bool overlay,bool safe,bool original){
 auto& s=d3d::State();auto o=s.presentation_overlay,a=s.presentation_safe_area,r=s.presentation_original_aspect;
 const auto before=c;want_overlay=overlay;want_safe=safe;want_original=original;const auto old=calls;
 try{f(c,memory);CHECK(!throws);}catch(const std::runtime_error&){CHECK(throws);}
 CHECK(calls==old+1&&s.presentation_overlay==o&&s.presentation_safe_area==a&&s.presentation_original_aspect==r);
 CHECK(c.ecx==before.ecx&&c.ebp==before.ebp&&c.esi==before.esi);
 CHECK(c.esp==before.esp+(throws?0:8));if(!throws)CHECK(c.eax==0xABCDEF);++cases;
}
int main(){
 for(bool option:{false,true})for(unsigned kind=0;kind<9;++kind)for(bool failure:{false,true}){
  auto c=Setup();settings.original_ui_aspect=option;bool original=false,safe=true,overlay=true;
  switch(kind){
   case 0:original=option;break; // Registered main/title/logo/still page.
   case 1:W(manager+8,0);W(manager+0x5C,root);original=option;break; // Outgoing native page.
   case 2:W(root,0x42A4C0);W(0x4AD664,0);overlay=false;original=option;break; // LoadingRect.
   case 3:W(root,0x427740);safe=false;break; // HUD, even if erroneously present in stack.
   case 4:W(root,0x43FB40);break; // Subtitles keep current16:9safe area.
   case 5:W(manager+12,other);break; // In-game choice/tutorial/dialog outside frontend.
   case 6:W(0x4AD664,0);break; // Native pause or gameplay overlay.
   case 7:W(manager+8,21);break; // Corrupt/unrecognized frontend manager.
   case 8:blocked.insert(manager);break;
  }
  CHECK(darkwatch::presentation::OriginalRoot(memory,root)==original);
  throws=failure;Run(c,sub_001EC5F4,overlay,safe,original);
 }
 for(bool outer:{false,true}){
  auto c=Setup();W(root,0x43FB40);d3d::State().presentation_original_aspect=outer;throws=false;
  Run(c,sub_0021B0D1,true,true,false);
 }
 for(bool option:{false,true})for(unsigned fault=0;fault<5;++fault){
  auto c=Setup();c.ecx=manager;settings.original_ui_aspect=option;throws=false;
  if(fault==1)W(manager+8,0);if(fault==2)W(0x4AD664,0);if(fault==3)W(manager+8,21);if(fault==4)W(stack+4,0);
  const bool active=option&&fault<2;Run(c,sub_000E4EBD,false,active,active);
 }
 // The full-display black scrim temporarily leaves the canvas and then restores it.
 auto c=Setup();W(stack,0xED75A);W(stack+4,0x60000);W(0x60020,camera);W(0x60028,0xFF000000);
 const float rect[]{0,0,1,1};std::memcpy(memory+0x60000,rect,sizeof(rect));
 d3d::State().presentation_overlay=d3d::State().presentation_safe_area=d3d::State().presentation_original_aspect=true;
 Run(c,sub_001ED841,true,false,false);
 CHECK(!darkwatch::presentation::OriginalRoot(nullptr,root));CHECK(!darkwatch::presentation::OriginalRoot(memory,0xFFFFFFF0));
 std::printf("original menu canvas passed: %u root/ABI/reset cases\n",cases);
}
'''

if __name__ == '__main__':
    unittest.main()
