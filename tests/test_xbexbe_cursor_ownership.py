"""Actual host cursor paths versus the pinned ImGui Win32 cursor updater, without UI."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_xbexbe_io_apc import function

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"
IMGUI = ROOT / "build/xbexbe/_deps/imgui-src"


class CursorOwnershipTests(unittest.TestCase):
    def test_window_thread_owns_hardware_cursor(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        main = (SDK / "app/main.cpp").read_text()
        backend = (IMGUI / "backends/imgui_impl_win32.cpp").read_text()
        flags = re.search(r"io.ConfigFlags \|= [^;]+;", main).group()
        declarations = main[main.index("HWND g_hwnd ="):main.index("void SyncInput(")]
        update = function(backend, "static bool ImGui_ImplWin32_UpdateMouseCursor()")
        frame_begin = backend.index("    ImGuiMouseCursor mouse_cursor = io.MouseDrawCursor")
        frame_end = backend.index("    // Update game controllers", frame_begin)
        fixture = (PREAMBLE + update + "\n" + FRAME_PREFIX + backend[frame_begin:frame_end] + "}\n" + BACKEND_MESSAGE
                   + "\nnamespace app {\n" + declarations + function(main, "void SyncInput(")
                   + function(main, "LRESULT CALLBACK WndProc(") + function(main, "void SetMenuPointer(") + "}\n" + DRIVER.replace("CURSOR_CONFIG", flags))
        with tempfile.TemporaryDirectory(prefix="cursor-ownership-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(fixture, encoding="utf-8")
            command = [compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK), "-I", str(IMGUI), str(source)]
            command += [str(IMGUI / name) for name in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")]
            result = subprocess.run(command + ["-o", str(exe), "-luser32"], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


PREAMBLE = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <imgui.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include "app/app.h"
#include "core/input.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
static HWND window=reinterpret_cast<HWND>(1),foreground=window;
static HCURSOR arrow=reinterpret_cast<HCURSOR>(2),cursor=arrow;
static bool visible=true,iconic=false,clipped=false,active=false,input_foreground=false;
static unsigned cursor_calls=0,visible_calls=0,clip_calls=0;
static int32_t pointer_x=0,pointer_y=0,pointer_wheel=0;
static uint32_t pointer_width=0,pointer_height=0,pointer_key=0;
static bool pointer_down=false,pointer_enabled=true,pointer_motion=false;
static unsigned pc_activity=0;
static HWND FakeForeground(){return foreground;}
static BOOL FakeVisible(HWND){return visible;}
static BOOL FakeIconic(HWND){return iconic;}
static BOOL FakeClient(HWND,RECT* r){*r={0,0,1280,720};return TRUE;}
static int FakeMap(HWND,HWND,POINT*,UINT){return 0;}
static BOOL FakeClip(const RECT* r){clipped=r!=nullptr;++clip_calls;return TRUE;}
static HCURSOR FakeCursor(HCURSOR next){auto old=cursor;cursor=next;++cursor_calls;if(next)++visible_calls;return old;}
static HCURSOR FakeLoad(HINSTANCE,const void*){return arrow;}
static LRESULT FakeDefault(HWND,UINT,WPARAM,LPARAM){return 17;}
static UINT FakeRaw(HRAWINPUT,UINT,LPVOID,PUINT,UINT){return 0;}
static void FakeQuit(int){}
#define GetForegroundWindow FakeForeground
#define IsWindowVisible FakeVisible
#define IsIconic FakeIconic
#define GetClientRect FakeClient
#define MapWindowPoints FakeMap
#define ClipCursor FakeClip
#define SetCursor FakeCursor
#undef LoadCursor
#define LoadCursor FakeLoad
#define LoadCursorW FakeLoad
#define DefWindowProcW FakeDefault
#define GetRawInputData FakeRaw
#define PostQuitMessage FakeQuit
#define GetKeyState(key) 0
namespace input {
void SetActive(bool value){active=value;}void Key(uint32_t,bool,bool,bool){}void Mouse(int32_t,int32_t){}
void SetForeground(bool value){input_foreground=value;}
void SetMenuMode(bool){}void NotePcActivity(bool motion){++pc_activity;if(motion)pointer_enabled=true;}
void Wheel(int32_t){}
void PointerPosition(int32_t x,int32_t y,uint32_t w,uint32_t h,bool motion){pointer_x=x;pointer_y=y;pointer_width=w;pointer_height=h;pointer_motion=motion;}
void PointerButton(uint32_t key,bool down){pointer_key=key;pointer_down=down;}
void PointerWheel(int32_t wheel){pointer_wheel=wheel;}
PointerSnapshot GetPointerSnapshot(){PointerSnapshot p;p.x=pointer_x;p.y=pointer_y;p.width=pointer_width;p.height=pointer_height;p.enabled=pointer_enabled;return p;}
}
namespace kernel {bool g_relaunching=false;}
namespace app {
bool PreparingShaders(){return false;}
[[noreturn]] void FinishPreparation(int){std::abort();}
const GameInfo kGame{};
std::recursive_mutex& UiLock(){static std::recursive_mutex lock;return lock;}
Settings Snapshot(){return {};}
void DumpThreads(){}void ApplyNow(){}void CloseSplash(){}void InvalidateOutput(){}
}
'''

FRAME_PREFIX = r'''
static void BackendFrameCursor(){
 struct Data{ImGuiMouseCursor LastMouseCursor=ImGuiMouseCursor_COUNT;};
 static Data data;auto* bd=&data;auto& io=ImGui::GetIO();
'''

BACKEND_MESSAGE = r'''
// The backend message calls the same unchanged updater only for the client area.
static LRESULT ImGui_ImplWin32_WndProcHandler(HWND,UINT msg,WPARAM,LPARAM lp){
 return msg==WM_SETCURSOR&&LOWORD(lp)==HTCLIENT&&ImGui_ImplWin32_UpdateMouseCursor();
}
'''

DRIVER = r'''
static LRESULT Message(UINT msg,WPARAM wp=0,LPARAM lp=0){return app::WndProc(window,msg,wp,lp);}
int main(){
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
 CURSOR_CONFIG
 ImGui::SetMouseCursor(ImGuiMouseCursor_Arrow);
 app::SyncInput(window);CHECK(active&&clipped&&!cursor&&app::g_cursor_hidden&&input_foreground);
 // Negative control: the actual backend can revive the arrow while capture is unchanged.
 io.ConfigFlags&=~ImGuiConfigFlags_NoMouseCursorChange;
 CHECK(ImGui_ImplWin32_UpdateMouseCursor()&&cursor==arrow);
 app::SyncInput(window);CHECK(cursor==arrow&&active);
 io.ConfigFlags|=ImGuiConfigFlags_NoMouseCursorChange;
 Message(WM_SETCURSOR,0,HTCLIENT);CHECK(!cursor);
 unsigned shown=visible_calls;
 for(int i=0;i<100;i++){
  ImGui::SetMouseCursor(i&1?ImGuiMouseCursor_Hand:ImGuiMouseCursor_Arrow);
  BackendFrameCursor();CHECK(!cursor);
  Message(WM_MOUSEMOVE);CHECK(!cursor);
  CHECK(Message(WM_SETCURSOR,0,HTCLIENT)==TRUE&&!cursor);
 }
 CHECK(visible_calls==shown); // Native gameplay and original menus share this capture path.
 app::SetMenuPointer(true);Message(app::kSyncInput);CHECK(active&&!clipped&&!cursor);
 pointer_enabled=false;auto activities=pc_activity;
 Message(WM_MOUSEMOVE,0,MAKELPARAM(pointer_x,pointer_y));CHECK(!pointer_enabled&&pc_activity==activities);
 Message(WM_RBUTTONDOWN,0,MAKELPARAM(10,15));CHECK(!pointer_enabled&&!pointer_motion&&pc_activity==activities);
 Message(WM_MOUSEWHEEL,MAKEWPARAM(0,120));CHECK(!pointer_enabled&&pc_activity==activities);
 Message(WM_KEYDOWN,'Z');CHECK(!pointer_enabled&&pc_activity==activities+1);
 io.WantCaptureMouse=true;Message(WM_MOUSEMOVE,0,MAKELPARAM(11,15));CHECK(pointer_enabled&&pointer_motion&&!active);io.WantCaptureMouse=false;
 Message(WM_MOUSEMOVE,0,MAKELPARAM(-15,75));CHECK(pointer_x==-15&&pointer_y==75&&pointer_width==1280&&pointer_height==720);
 Message(WM_RBUTTONDOWN,0,MAKELPARAM(100,200));CHECK(pointer_key==VK_RBUTTON&&pointer_down&&pointer_x==100&&pointer_y==200);
 Message(WM_RBUTTONUP);CHECK(pointer_key==VK_RBUTTON&&!pointer_down);
 Message(WM_KEYDOWN,VK_ESCAPE);CHECK(pointer_key==VK_ESCAPE&&pointer_down);
 Message(WM_KEYUP,VK_ESCAPE);CHECK(pointer_key==VK_ESCAPE&&!pointer_down);
 Message(WM_KEYDOWN,VK_ESCAPE);CHECK(pointer_down);
 Message(WM_SYSKEYUP,VK_ESCAPE);CHECK(pointer_key==VK_ESCAPE&&!pointer_down);
 Message(WM_SYSKEYDOWN,VK_ESCAPE);CHECK(pointer_key==VK_ESCAPE&&pointer_down);
 Message(WM_KEYUP,VK_ESCAPE);CHECK(!pointer_down);
 Message(WM_MOUSEWHEEL,MAKEWPARAM(0,-120));CHECK(pointer_wheel==-120);
 for(int i=0;i<20;i++){BackendFrameCursor();Message(WM_MOUSEMOVE);CHECK(active&&!clipped&&!cursor);}
 foreground=nullptr;Message(WM_KILLFOCUS);CHECK(!active&&!clipped&&cursor==arrow&&!input_foreground);
 foreground=window;Message(app::kSyncInput);CHECK(active&&!clipped&&!cursor&&input_foreground);
 app::SetMenuPointer(false);Message(app::kSyncInput);CHECK(active&&clipped&&!cursor);
 shown=visible_calls;
 // Graphics draws a software cursor: release clipping without showing a second OS arrow.
 io.WantCaptureMouse=true;io.MouseDrawCursor=true;app::SyncInput(window);
 CHECK(!active&&!clipped&&!cursor&&io.MouseDrawCursor&&input_foreground);
 BackendFrameCursor();Message(WM_SETCURSOR,0,HTCLIENT);CHECK(!cursor&&visible_calls==shown);
 // Closing Graphics cannot let the render-thread backend flash an arrow before SyncInput.
 io.MouseDrawCursor=false;io.WantCaptureMouse=false;BackendFrameCursor();CHECK(!cursor);
 Message(app::kSyncInput);CHECK(active&&clipped&&!cursor);
 // F1 releases the native cursor; an autorepeat does not toggle it back.
 Message(WM_KEYDOWN,VK_F1);CHECK(!active&&!clipped&&cursor==arrow&&input_foreground);
 Message(WM_KEYDOWN,VK_F1,LPARAM(1)<<30);CHECK(!app::g_pc_enabled&&cursor==arrow);
 BackendFrameCursor();Message(WM_SETCURSOR,0,HTCLIENT);CHECK(cursor==arrow);
 Message(WM_KEYDOWN,VK_F1);CHECK(active&&clipped&&!cursor);
 // Focus loss and destruction release both capture and cursor, including software UI mode.
 foreground=nullptr;Message(WM_KILLFOCUS);CHECK(!active&&!clipped&&cursor==arrow&&!app::g_cursor_hidden);
 foreground=window;Message(app::kSyncInput);CHECK(active&&clipped&&!cursor);
 io.WantCaptureKeyboard=true;io.MouseDrawCursor=true;Message(app::kSyncInput);CHECK(!active&&!clipped&&!cursor);
 foreground=nullptr;Message(WM_KILLFOCUS);CHECK(cursor==arrow&&!app::g_cursor_hidden);
 foreground=window;Message(app::kSyncInput);CHECK(!cursor&&!clipped&&io.MouseDrawCursor);
 io.WantCaptureKeyboard=false;io.MouseDrawCursor=false;Message(app::kSyncInput);CHECK(active&&clipped&&!cursor);
 iconic=true;Message(app::kSyncInput);CHECK(!active&&!clipped&&cursor==arrow&&!input_foreground);
 iconic=false;Message(app::kSyncInput);CHECK(active&&clipped&&!cursor&&input_foreground);
 visible=false;Message(app::kSyncInput);CHECK(!active&&!clipped&&cursor==arrow&&!input_foreground);
 visible=true;Message(app::kSyncInput);CHECK(active&&clipped&&!cursor&&input_foreground);
 auto clips=clip_calls;Message(WM_SIZE);CHECK(clip_calls==clips+1&&clipped&&!cursor);
 CHECK(Message(WM_SETCURSOR,0,HTCAPTION)==17); // Preserve normal nonclient handling.
 Message(WM_DESTROY);CHECK(!active&&!clipped&&cursor==arrow&&!app::g_cursor_hidden&&!input_foreground);
 ImGui::DestroyContext();std::puts("cursor ownership: actual backend negative control, 100 movement/frame cycles, software UI, F1, focus, visibility and resize passed");
}
'''


if __name__ == "__main__":
    unittest.main()
