"""One real ImGui gamepad provider and post-menu native-input activation.

Uses the actual project UI, disabled Win32 gamepad function and SyncInput body.
Only window queries/cursor calls and the input focus/capture endpoints are recorders.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_xbexbe_graphics_ui import FIXTURE, GAMEPAD_UI, ROOT, SDK, IMGUI
from test_xbexbe_io_apc import function


def pointer_fixture():
    gate = function((SDK / "gpu/d3d12.cpp").read_text(encoding="utf-8"), "static void UpdateUiPointer()")
    setup = FIXTURE[:FIXTURE.index("int main(){")]
    setup = setup.replace("static double fixture_fps=60;", """
static input::PointerSnapshot pointer_state;
namespace input { PointerSnapshot GetPointerSnapshot(){return pointer_state;} }
""" + gate + "\nstatic double fixture_fps=60;")
    return setup.replace("ImGui::NewFrame();DarkwatchGraphicsUi", "UpdateUiPointer();ImGui::NewFrame();DarkwatchGraphicsUi")


class GraphicsInputProviderTests(unittest.TestCase):
    def test_second_controller_claims_focused_host_panels_with_pc_captured(self):
        from test_xbexbe_native_input import SDL as CONTROLLED_SDL
        main = (SDK / "app/main.cpp").read_text()
        sync = function(main, "void SyncInput(")
        setup = FIXTURE[:FIXTURE.index("int main(){")]
        first = setup.index("namespace input {")
        last = setup.index("namespace darkwatch {", first)
        setup = setup[:first] + '#include "core/input.cpp"\n' + setup[last:]
        setup = setup.replace('const GameInfo kGame{.settings="test-settings.toml"};',
                              'const GameInfo kGame{.settings="test-settings.toml",.pad=DarkwatchGraphicsPad};')
        boundary = WINDOW_BOUNDARY.replace("namespace input {void SetForeground(bool value){input_foreground=value;}}", "")
        fixture = setup + boundary + sync + UNDEFINE_WINDOW + CONNECTED_DRIVER
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="graphics-controller-ownership-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            (folder / "SDL3").mkdir()
            (folder / "SDL3/SDL.h").write_text(CONTROLLED_SDL)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(fixture, encoding="utf-8")
            command = [compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(folder), "-I", str(SDK),
                       "-I", str(ROOT / "xbexbe/src"), "-I", str(IMGUI),
                       "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"), str(source)]
            command += [str(IMGUI / name) for name in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")]
            built = subprocess.run(command + ["-o", str(exe), "-luser32"], capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=15)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            print(ran.stdout.strip())
            # The previous PC-capture guard fails this same connected host-page case.
            production = (SDK / "core/input.cpp").read_text()
            old = production.replace("selected < 0 || !g_foreground", "selected < 0 || !g_pc_active")
            self.assertNotEqual(old, production)
            source.write_text(fixture.replace('#include "core/input.cpp"', old), encoding="utf-8")
            built = subprocess.run(command + ["-o", str(exe), "-luser32"], capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=15)
            self.assertEqual(ran.returncode, 90, ran.stdout + ran.stderr)
            self.assertIn("SDL_GetGamepadID(input::g_pads[0])==owner+1", ran.stderr)

    def test_controller_recovers_host_focus_after_outside_mouse_click(self):
        from test_xbexbe_graphics_ui import GraphicsUiTests
        fixture = pointer_fixture() + GAMEPAD_UI[:GAMEPAD_UI.index("int main(){")] + HANDOFF_DRIVER
        runner = GraphicsUiTests()
        ran = runner.run_fixture(fixture)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        source = (ROOT / "xbexbe/src/common/graphics.cpp").read_text(encoding="utf-8")
        self.assertIn("if (g_open && !GImGui->NavWindow)", source)
        old = source.replace("if (g_open && !GImGui->NavWindow)", "if (false)")
        ran = runner.run_fixture(fixture.replace('#include "common/graphics.cpp"', old))
        self.assertEqual(ran.returncode, 90, ran.stdout + ran.stderr)
        self.assertIn("GImGui->NavWindow&&GImGui->NavId", ran.stderr)

    def test_controls_row_highlight_tracks_navigation_while_scrolling(self):
        from test_xbexbe_graphics_ui import GraphicsUiTests
        source = (ROOT / "xbexbe/src/common/graphics.cpp").read_text(encoding="utf-8")
        # Observe the selected row sent to the skin without changing hit testing or ImGui navigation.
        source = source.replace("struct MenuRow {", "static std::vector<std::string> observed_rows;\nstruct MenuRow {\n    std::string observed_label;")
        begin = source.index("struct MenuRow {")
        source = source[:begin] + source[begin:].replace("text = language::Text(text);", "text = language::Text(text); observed_label=text;", 1).replace(
            "skin::Row(draw, a, b, selected);", "if(selected)observed_rows.emplace_back(observed_label); skin::Row(draw, a, b, selected);", 1)
        setup = pointer_fixture().replace("rendered_text.clear();", "rendered_text.clear();observed_rows.clear();")
        fixture = setup + GAMEPAD_UI[:GAMEPAD_UI.index("int main(){")] + HIGHLIGHT_DRIVER
        runner = GraphicsUiTests()
        ran = runner.run_fixture(fixture.replace('#include "common/graphics.cpp"', source))
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertIn("ImGui::WindowRectRelToAbs(window, nav).GetCenter().y", source)
        old = source.replace("ImGui::WindowRectRelToAbs(window, nav).GetCenter().y", "pos.y + nav.GetCenter().y")
        ran = runner.run_fixture(fixture.replace('#include "common/graphics.cpp"', old))
        self.assertEqual(ran.returncode, 90, ran.stdout + ran.stderr)
        self.assertIn("observed_rows.size()==1&&observed_rows[0]==label", ran.stderr)

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
void logx::Write(logx::Level,const char*,...){}
static bool input_foreground=false;
namespace input {void SetForeground(bool value){input_foreground=value;}}
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
 preparing=false;SyncInput(window);CHECK(active&&cursor_clipped&&input_foreground);
 route={darkwatch::GraphicsMenuRoute::Visual,0x123400,0x123500,true,false};
 // The press that entered the original Visual page cannot activate its first host control.
 for(unsigned i=0;i<12;++i){Poll(0,255);Frame();SyncInput(window);CHECK(!g_released&&!g_pad&&!ImGui::IsKeyDown(ImGuiKey_GamepadFaceDown));}
 CHECK(!active&&!cursor_clipped&&input_foreground);
 Poll();Frame();CHECK(g_released);
 // Analog face buttons use the same threshold as the native input provider.
 Poll(0,30,30);CHECK(!g_pad);
 Poll(0,31);CHECK(g_pad==16);
 Poll(0,0,31);CHECK(g_pad==32);
 Poll();CHECK(!g_pad);
 // Stick directions use the same release-gated source, including a precise deadzone boundary.
 input::Pad stick{};stick.connected=true;stick.ly=16000;DarkwatchGraphicsPad(0,stick);CHECK(g_pad==0);
 stick.ly=16001;DarkwatchGraphicsPad(0,stick);CHECK(g_pad==1&&!stick.ly);Frame();Frame();CHECK(ImGui::IsKeyDown(ImGuiKey_GamepadDpadUp));
 Poll();Frame();Frame();CHECK(!ImGui::IsKeyDown(ImGuiKey_GamepadDpadUp));
 Poll(0,255);Frame();Frame();CHECK(ImGui::IsKeyDown(ImGuiKey_GamepadFaceDown));
 // Close while a control has received A. Original Back is delivered, then held B is quarantined.
 Close();auto pad=Poll(0,0,255);CHECK(pad.analog[1]==255);
 route.route=darkwatch::GraphicsMenuRoute::OptionsMain;pad=Poll(0,0,255);CHECK(!pad.analog[1]&&g_block_release);
 // Neutral analog noise must not permanently block keyboard or gamepad input after a page closes.
 input::Pad drift{};drift.connected=true;drift.analog[0]=30;drift.analog[1]=30;drift.analog[6]=1;drift.analog[7]=30;
 drift.lx=10000;drift.ly=-16000;drift.rx=16000;drift.ry=-10000;
 auto neutral=drift;DarkwatchGraphicsPad(0,neutral);CHECK(!g_leave&&!g_block_release);
 // Co-op releases each player's input separately, with the same neutral thresholds.
 g_coop_block_release={true,true};
 for(unsigned port:{0u,1u}){neutral=drift;DarkwatchGraphicsPad(port,neutral);CHECK(!g_coop_block_release[port]);}
 // A deliberate trigger pull or menu direction still has to be released.
 for(unsigned kind=0;kind<3;++kind){
  g_block_release=true;auto held=drift;
  if(kind==0)held.analog[7]=31;else if(kind==1)held.lx=16001;else held.buttons=8;
  DarkwatchGraphicsPad(0,held);CHECK(g_block_release);
  neutral=drift;DarkwatchGraphicsPad(0,neutral);CHECK(!g_block_release);
 }
 // The production kSyncInput path is posted every Pace. No extra native mouse event is required.
 bool recovered=false;
 for(unsigned i=0;i<8;++i){Frame();SyncInput(window);if(active){CHECK(!io.WantCaptureKeyboard&&!io.WantCaptureMouse);recovered=true;}}
 CHECK(recovered&&active&&cursor_clipped&&!g_open&&!io.MouseDrawCursor);
 // Recovery still obeys focus, minimize, visible-window and the user's F1 native-input switch.
 foreground=nullptr;SyncInput(window);CHECK(!active&&!cursor_clipped&&!input_foreground);
 foreground=window;window_minimized=true;SyncInput(window);CHECK(!active&&!input_foreground);
 window_minimized=false;window_visible=false;SyncInput(window);CHECK(!active&&!input_foreground);
 window_visible=true;g_pc_enabled=false;SyncInput(window);CHECK(!active&&input_foreground);
 g_pc_enabled=true;SyncInput(window);CHECK(active&&cursor_clipped&&clips>=4);
 ImGui::DestroyContext();std::puts("graphics input recovery passed: single provider, held A, stick gate, Back/release, capture drain and actual SyncInput focus recovery");
}
'''

CONNECTED_DRIVER = r'''
static void ConnectedFrames(unsigned count=3){
 for(unsigned i=0;i<count;++i){++fake_ticks;input::Poll(0);input::Poll(1);Frame();SyncInput(window);}
}
int main(){
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
 io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad;
 g_body=io.Fonts->AddFontDefault();g_title=g_body;unsigned char* pixels;int w,h;
 io.Fonts->GetTexDataAsRGBA32(&pixels,&w,&h);g_modes={{1280,720}};
 fake_init=true;fake_count=2;input::SetSinglePlayerController(true);input::Init();input::SetMenuMode(true);
 Frame();SyncInput(window);ConnectedFrames();
 unsigned owner=0;
 for(auto page:{darkwatch::GraphicsMenuRoute::Visual,darkwatch::GraphicsMenuRoute::Controls,darkwatch::GraphicsMenuRoute::Audio}){
  route.route=page;route.options=0x123400;route.page=0x123500;route.audio_available=route.controls_available=true;
  ConnectedFrames(8);CHECK(g_open&&!input::g_pc_active&&input::g_foreground);
  // Original host handler owns the pad callback and disables guest PC input.
  owner^=1;fake_pads[owner].buttons[SDL_GAMEPAD_BUTTON_DPAD_DOWN]=true;ConnectedFrames(3);
  CHECK(SDL_GetGamepadID(input::g_pads[0])==owner+1);
  CHECK(g_pad==2&&ImGui::IsKeyDown(ImGuiKey_GamepadDpadDown));
  CHECK(!input::GetPointerSnapshot().enabled&&!input::g_pc_active);
  fake_pads[owner].buttons[SDL_GAMEPAD_BUTTON_DPAD_DOWN]=false;ConnectedFrames();
  CHECK(!g_pad&&!ImGui::IsKeyDown(ImGuiKey_GamepadDpadDown));
  // Actual SyncInput distinguishes a background window from a foreground captured panel.
  foreground=nullptr;SyncInput(window);const auto other=owner^1;
  fake_pads[other].buttons[SDL_GAMEPAD_BUTTON_SOUTH]=true;ConnectedFrames();
  CHECK(SDL_GetGamepadID(input::g_pads[0])==owner+1&&!input::g_foreground);
  foreground=window;SyncInput(window);ConnectedFrames();
  CHECK(SDL_GetGamepadID(input::g_pads[0])==owner+1);
  fake_pads[other].buttons[SDL_GAMEPAD_BUTTON_SOUTH]=false;ConnectedFrames();
 }
 ImGui::DestroyContext();std::puts("PASS connected production input + Graphics/Controls/Audio + SyncInput: second-pad navigation with captured PC, background claim rejected");
}
'''

HANDOFF_DRIVER = r'''
int main(){
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
 io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad;
 ImFontConfig font;font.SizePixels=22;g_body=io.Fonts->AddFontDefault(&font);g_title=g_body;
 unsigned char* pixels;int width,height;io.Fonts->GetTexDataAsRGBA32(&pixels,&width,&height);
 record_combo_text=false;g_modes={{1280,720},{1920,1080},{2560,1440}};
 for(auto page:{darkwatch::GraphicsMenuRoute::Controls,darkwatch::GraphicsMenuRoute::Audio,darkwatch::GraphicsMenuRoute::Visual}){
  pointer_state.enabled=true;HidePage();
  route.route=page;route.options=0x433300;route.page=0x433400;route.audio_available=route.controls_available=true;
  route.sensitivity_min=1;route.sensitivity_max=10;route.sensitivity=5;
  PadFrames(0,0,5);CHECK(g_open);
  const char* field=page==darkwatch::GraphicsMenuRoute::Controls?"##zoom sensitivity":
                    page==darkwatch::GraphicsMenuRoute::Audio?"##music":"##internal";
  ClickField(field,.5f);CHECK(GImGui->NavId==field_ids[field]);
  pointer_state.enabled=false;++pointer_state.epoch;PadFrames(0,2,4);
  CHECK(GImGui->NavWindow&&GImGui->NavId&&GImGui->NavId!=field_ids[field]);
  CHECK(!GImGui->NavDisableHighlight&&(io.ConfigFlags&ImGuiConfigFlags_NoMouse));PadFrames(0);
  pointer_state.enabled=true;io.AddMousePosEvent(5,5);Frame();Click(5,5);
  CHECK(!GImGui->NavWindow&&!GImGui->NavId);
  pointer_state.enabled=false;++pointer_state.epoch;PadFrames(0,2,4);
  CHECK(GImGui->NavWindow&&GImGui->NavId);
  const auto selected=GImGui->NavId;PadTap(0,1);CHECK(GImGui->NavId&&GImGui->NavId!=selected);
  CHECK(g_open&&!g_leave&&!GImGui->NavDisableHighlight);
 }
 ImGui::DestroyContext();std::puts("PASS mouse-to-controller host focus recovery: Graphics, Controls and Audio with the production pointer gate");
}
'''

HIGHLIGHT_DRIVER = r'''
static void CheckRow(const char* field,const char* label){
 CHECK(GImGui->NavId==field_ids[field]);
 if(observed_rows.size()!=1||observed_rows[0]!=label){
  std::fprintf(stderr,"focused %s, painted",label);for(const auto& row:observed_rows)std::fprintf(stderr," [%s]",row.c_str());std::fputc('\n',stderr);
 }
 CHECK(observed_rows.size()==1&&observed_rows[0]==label);
}
int main(){
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
 io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad;
 ImFontConfig font;font.SizePixels=22;g_body=io.Fonts->AddFontDefault(&font);g_title=g_body;
 unsigned char* pixels;int width,height;io.Fonts->GetTexDataAsRGBA32(&pixels,&width,&height);
 record_combo_text=false;g_modes={{1280,720},{1920,1080},{2560,1440}};
 pointer_state.enabled=false;++pointer_state.epoch;OpenControls(0);
 Navigate(0,2,field_ids["##sight mode"]);PadTap(0,16);PadTap(0,2);PadTap(0,16);
 CHECK(!ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId|ImGuiPopupFlags_AnyPopupLevel));
 CheckRow("##sight mode","SIGHT MODE");
 const char* fields[]={"##walk mode","##aim assistance","##look centering","##invert look","##vibration",
                      "##controller sensitivity","##carry all weapons","##keep starting revolver"};
 const char* labels[]={"WALK MODE","AIMING ASSISTANCE","LOOK CENTERING","INVERT LOOK","PAD VIBRATION",
                      "PAD SENSITIVITY","CARRY ALL WEAPONS","KEEP STARTING REVOLVER"};
 for(unsigned i=0;i<std::size(fields);++i){Navigate(0,2,field_ids[fields[i]]);CheckRow(fields[i],labels[i]);}
 CHECK(ImGui::FindWindowByName("Controls")->DC.ChildWindows[0]->Scroll.y>0);
 for(int i=int(std::size(fields))-2;i>=0;--i){Navigate(0,1,field_ids[fields[i]]);CheckRow(fields[i],labels[i]);}
 Navigate(0,1,field_ids["##sight mode"]);CheckRow("##sight mode","SIGHT MODE");
 ImGui::DestroyContext();std::puts("PASS Controls row highlight matches the focused widget after selection and scrolling in both directions");
}
'''


if __name__ == "__main__":
    unittest.main()
