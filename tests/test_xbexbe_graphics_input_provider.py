"""One real ImGui gamepad provider and post-menu native-input activation.

Uses the actual project UI, disabled Win32 gamepad function and SyncInput body.
Only window queries/cursor calls and the input SetActive endpoint are recorders.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_xbexbe_graphics_ui import FIXTURE, ROOT, SDK, IMGUI
from test_xbexbe_io_apc import function


class GraphicsInputProviderTests(unittest.TestCase):
    def test_actual_win32_backend_is_disabled_by_project_definition(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        project = (ROOT / "xbexbe/CMakeLists.txt").read_text()
        self.assertRegex(project, r"target_compile_definitions\(darkwatch_xbe\s+PRIVATE\s+IMGUI_IMPL_WIN32_DISABLE_GAMEPAD\)")
        backend = IMGUI / "backends/imgui_impl_win32.cpp"
        common = [compiler, "-std=c++20", "-E", "-P", "-I", str(IMGUI), str(backend)]
        results = []
        for define in ([], ["-DIMGUI_IMPL_WIN32_DISABLE_GAMEPAD"]):
            r = subprocess.run(common + define, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            results.append(function(r.stdout, "static void ImGui_ImplWin32_UpdateGamepads()"))
        self.assertIn("XInputGetState", results[0])  # negative control: upstream's independent provider
        self.assertIn("AddKeyEvent", results[0])
        self.assertEqual(re.sub(r"\s+", "", results[1]), "staticvoidImGui_ImplWin32_UpdateGamepads(){}")

    def test_gated_pad_and_actual_sync_input_recover_after_close(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        backend = (IMGUI / "backends/imgui_impl_win32.cpp").read_text()
        gamepads = function(backend, "static void ImGui_ImplWin32_UpdateGamepads()")
        main = (SDK / "app/main.cpp").read_text()
        sync = function(main, "void SyncInput(")
        # Retain the real project's UI fixture boundaries; replace only its driver.
        setup = FIXTURE[:FIXTURE.index("int main(){")]
        setup = setup.replace("static void Frame(float elapsed=1.f/60){", gamepads + "\nstatic void Frame(float elapsed=1.f/60){")
        setup = setup.replace("ImGui::NewFrame();DarkwatchGraphicsUi", "ImGui_ImplWin32_UpdateGamepads();ImGui::NewFrame();DarkwatchGraphicsUi")
        fixture = setup + WINDOW_BOUNDARY + sync + UNDEFINE_WINDOW + DRIVER
        with tempfile.TemporaryDirectory(prefix="graphics-input-provider-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            src, exe = folder / "test.cpp", folder / "test.exe"
            src.write_text(fixture)
            command = [compiler, "-std=c++20", "-Wno-nontrivial-memcall", "-O1", "-fuse-ld=lld",
                       "-DIMGUI_IMPL_WIN32_DISABLE_GAMEPAD", "-I", str(SDK), "-I", str(ROOT / "xbexbe/src"),
                       "-I", str(IMGUI), "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"), str(src)]
            command += [str(IMGUI / name) for name in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")]
            r = subprocess.run(command + ["-o", str(exe), "-luser32"], capture_output=True, text=True, timeout=90)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=15)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("graphics input recovery passed", r.stdout)
            print(r.stdout.strip())


WINDOW_BOUNDARY = r'''
static bool preparing=false;
static bool PreparingShaders(){return preparing;}
static bool g_pc_enabled=true,g_cursor_captured=false,g_cursor_hidden=false,window_visible=true,window_minimized=false,cursor_clipped=false;
static std::atomic<bool> g_menu_pointer{false};
static HWND window=reinterpret_cast<HWND>(1),foreground=window;
static unsigned clips=0;
static std::recursive_mutex& UiLock(){static std::recursive_mutex lock;return lock;}
static HWND FakeForeground(){return foreground;}
static BOOL FakeVisible(HWND){return window_visible;}
static BOOL FakeIconic(HWND){return window_minimized;}
static BOOL FakeRect(HWND,RECT* r){*r={0,0,1280,720};return TRUE;}
static int FakeMap(HWND,HWND,POINT*,UINT){return 0;}
static BOOL FakeClip(const RECT* r){++clips;cursor_clipped=r!=nullptr;return TRUE;}
static HCURSOR FakeCursor(HCURSOR){return nullptr;}
static HCURSOR FakeLoad(HINSTANCE,const void*){return nullptr;}
#define GetForegroundWindow FakeForeground
#define IsWindowVisible FakeVisible
#define IsIconic FakeIconic
#define GetClientRect FakeRect
#define MapWindowPoints FakeMap
#define ClipCursor FakeClip
#define SetCursor FakeCursor
#define LoadCursorW FakeLoad
'''

UNDEFINE_WINDOW = r'''
#undef GetForegroundWindow
#undef IsWindowVisible
#undef IsIconic
#undef GetClientRect
#undef MapWindowPoints
#undef ClipCursor
#undef SetCursor
#undef LoadCursorW
'''

DRIVER = r'''
int main(){
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
 io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad;
 g_body=io.Fonts->AddFontDefault();g_title=g_body;unsigned char* pixels;int w,h;
 io.Fonts->GetTexDataAsRGBA32(&pixels,&w,&h);g_modes={{2560,1440}};
 Frame();active=false;preparing=true;SyncInput(window);CHECK(!active&&!cursor_clipped&&!clips);
 preparing=false;SyncInput(window);CHECK(active&&cursor_clipped);
 route={darkwatch::GraphicsMenuRoute::Visual,0x123400,0x123500,true,false};
 // The press that entered the original Visual page cannot activate its first host control.
 for(unsigned i=0;i<12;++i){Poll(0,255);Frame();SyncInput(window);CHECK(!g_released&&!g_pad&&!ImGui::IsKeyDown(ImGuiKey_GamepadFaceDown));}
 CHECK(!active&&!cursor_clipped);
 Poll();Frame();CHECK(g_released);
 // Stick directions use the same release-gated source, including a precise deadzone boundary.
 input::Pad stick{};stick.connected=true;stick.ly=16000;DarkwatchGraphicsPad(0,stick);CHECK(g_pad==0);
 stick.ly=16001;DarkwatchGraphicsPad(0,stick);CHECK(g_pad==1&&!stick.ly);Frame();Frame();CHECK(ImGui::IsKeyDown(ImGuiKey_GamepadDpadUp));
 Poll();Frame();Frame();CHECK(!ImGui::IsKeyDown(ImGuiKey_GamepadDpadUp));
 Poll(0,255);Frame();Frame();CHECK(ImGui::IsKeyDown(ImGuiKey_GamepadFaceDown));
 // Close while a control has received A. Original Back is delivered, then held B is quarantined.
 Close();auto pad=Poll(0,0,255);CHECK(pad.analog[1]==255);
 route.route=darkwatch::GraphicsMenuRoute::OptionsMain;pad=Poll(0,0,255);CHECK(!pad.analog[1]&&g_block_release);
 Poll();CHECK(!g_leave&&!g_block_release);
 // The production kSyncInput path is posted every Pace. No extra native mouse event is required.
 bool recovered=false;
 for(unsigned i=0;i<8;++i){Frame();SyncInput(window);if(active){CHECK(!io.WantCaptureKeyboard&&!io.WantCaptureMouse);recovered=true;}}
 CHECK(recovered&&active&&cursor_clipped&&!g_open&&!io.MouseDrawCursor);
 // Recovery still obeys focus, minimize, visible-window and the user's F1 native-input switch.
 foreground=nullptr;SyncInput(window);CHECK(!active&&!cursor_clipped);
 foreground=window;window_minimized=true;SyncInput(window);CHECK(!active);
 window_minimized=false;window_visible=false;SyncInput(window);CHECK(!active);
 window_visible=true;g_pc_enabled=false;SyncInput(window);CHECK(!active);
 g_pc_enabled=true;SyncInput(window);CHECK(active&&cursor_clipped&&clips>=4);
 ImGui::DestroyContext();std::puts("graphics input recovery passed: single provider, held A, stick gate, Back/release, capture drain and actual SyncInput focus recovery");
}
'''


if __name__ == "__main__":
    unittest.main()
