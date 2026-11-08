"""Real ImGui event/interaction checks for the production pre-frame pointer gate."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_xbexbe_io_apc import function

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"
IMGUI = ROOT / "build/xbexbe/_deps/imgui-src"


class UiPointerTests(unittest.TestCase):
    def test_actual_gate_and_flag_only_negative_control(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        source = (SDK / "gpu/d3d12.cpp").read_text(encoding="utf-8")
        helper = function(source, "static void UpdateUiPointer()")
        render = function(source, "void D3D12Backend::RenderUi()")
        self.assertLess(render.index("ImGui_ImplWin32_NewFrame();"), render.index("UpdateUiPointer();"))
        self.assertLess(render.index("UpdateUiPointer();"), render.index("ImGui::NewFrame();"))
        with tempfile.TemporaryDirectory(prefix="ui-pointer-", dir=ROOT / "build") as temporary:
            folder = Path(temporary)
            for name, implementation, expected in (("actual", helper, 0), ("flag-only", FLAG_ONLY, 90)):
                cpp, exe = folder / (name + ".cpp"), folder / (name + ".exe")
                cpp.write_text(PREAMBLE + implementation + DRIVER, encoding="utf-8")
                command = [compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK), "-I", str(IMGUI), str(cpp)]
                command += [str(IMGUI / filename) for filename in
                            ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")]
                built = subprocess.run(command + ["-o", str(exe)], capture_output=True, text=True, timeout=90)
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                ran = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=15)
                self.assertEqual(ran.returncode, expected, ran.stdout + ran.stderr)
                if expected:
                    self.assertIn("g.InputEventsQueue.Size == int(retained.size())", ran.stderr)
                else:
                    print(ran.stdout.strip())


PREAMBLE = r'''
#include <imgui.h>
#include <imgui_internal.h>
#include "core/input.h"
#include <cstdio>
#include <cstdlib>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x); std::exit(90); } } while (0)
static bool enabled = true;
static uint64_t epoch = 0;
namespace input { PointerSnapshot GetPointerSnapshot() { PointerSnapshot p; p.enabled=enabled; p.epoch=epoch; return p; } }
'''

FLAG_ONLY = r'''
static void UpdateUiPointer() {
    auto& io=ImGui::GetIO();
    if (input::GetPointerSnapshot().enabled) io.ConfigFlags&=~ImGuiConfigFlags_NoMouse;
    else io.ConfigFlags|=ImGuiConfigFlags_NoMouse;
}
'''

DRIVER = r'''
struct Fixture {
    ImVec2 button{}, slider{};
    bool hovered=false, clicked=false, focus_lost=false;
    float value=.5f;
    Fixture() {
        enabled=true;
        ImGui::CreateContext();
        auto& io=ImGui::GetIO();
        io.IniFilename=nullptr; io.DisplaySize={640,480}; io.DeltaTime=1.f/60;
        io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad;
        io.BackendFlags|=ImGuiBackendFlags_HasGamepad;
        unsigned char* pixels; int width,height;
        io.Fonts->GetTexDataAsRGBA32(&pixels,&width,&height);
        Frame(); Frame();
    }
    ~Fixture() { ImGui::DestroyContext(); }
    void Frame() {
        UpdateUiPointer();
        ImGui::NewFrame();
        focus_lost=ImGui::GetIO().AppFocusLost;
        ImGui::SetNextWindowPos({30,30}); ImGui::SetNextWindowSize({300,240});
        ImGui::Begin("Settings",nullptr,ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoMove|ImGuiWindowFlags_NoResize);
        clicked=ImGui::Button("Action",{150,40}); hovered=ImGui::IsItemHovered();
        auto a=ImGui::GetItemRectMin(), b=ImGui::GetItemRectMax(); button={(a.x+b.x)*.5f,(a.y+b.y)*.5f};
        ImGui::SliderFloat("Value",&value,0,1);
        a=ImGui::GetItemRectMin();b=ImGui::GetItemRectMax();slider={a.x+40,(a.y+b.y)*.5f};
        ImGui::End(); ImGui::Render();
    }
};

static bool MouseEvent(const ImGuiInputEvent& e) {
    return e.Type==ImGuiInputEventType_MousePos || e.Type==ImGuiInputEventType_MouseButton || e.Type==ImGuiInputEventType_MouseWheel;
}

static void QueuedEvents() {
    Fixture f; auto& io=ImGui::GetIO(); auto& g=*ImGui::GetCurrentContext();
    io.AddMousePosEvent(f.button.x,f.button.y);
    io.AddMouseButtonEvent(0,true);
    io.AddKeyEvent(ImGuiKey_A,true);
    io.AddMouseButtonEvent(1,true);
    io.AddKeyEvent(ImGuiKey_GamepadFaceDown,true);
    io.AddMouseWheelEvent(1,3);
    io.AddInputCharacter('x');
    io.AddFocusEvent(false);
    std::vector<unsigned> retained;
    bool keyboard=false, gamepad=false, text=false, focus=false;
    for(const auto& e:g.InputEventsQueue) if(!MouseEvent(e)) {
        retained.push_back(e.EventId);
        keyboard|=e.Type==ImGuiInputEventType_Key&&e.Key.Key==ImGuiKey_A;
        gamepad|=e.Type==ImGuiInputEventType_Key&&e.Key.Key==ImGuiKey_GamepadFaceDown;
        text|=e.Type==ImGuiInputEventType_Text; focus|=e.Type==ImGuiInputEventType_Focus;
    }
    CHECK(keyboard&&gamepad&&text&&focus);
    enabled=false; UpdateUiPointer();
    CHECK(g.InputEventsQueue.Size == int(retained.size()));
    for(int i=0;i<g.InputEventsQueue.Size;++i) CHECK(g.InputEventsQueue[i].EventId==retained[i]&&!MouseEvent(g.InputEventsQueue[i]));
    CHECK((io.ConfigFlags&ImGuiConfigFlags_NoMouse)&&!ImGui::IsMousePosValid()&&!io.MouseDown[0]&&!io.MouseDown[1]);
    CHECK(io.MouseWheel==0&&io.MouseWheelH==0);
    std::vector<unsigned> processed;
    bool saw_focus_lost=false;
    for(int frame=0;frame<4&&!g.InputEventsQueue.empty();++frame) {
        f.Frame(); saw_focus_lost|=f.focus_lost;
        CHECK(!f.hovered&&!f.clicked);
        for(const auto& e:g.InputEventsTrail) processed.push_back(e.EventId);
    }
    CHECK(processed==retained&&saw_focus_lost);
}

static void Interactions() {
    Fixture f; auto& io=ImGui::GetIO(); auto& g=*ImGui::GetCurrentContext();
    io.AddMousePosEvent(f.button.x,f.button.y); f.Frame(); CHECK(f.hovered);
    enabled=false;
    io.AddMouseButtonEvent(0,true);io.AddMouseButtonEvent(1,true);io.AddMouseWheelEvent(0,2);
    f.Frame();CHECK(!f.hovered&&!f.clicked&&!ImGui::IsMouseClicked(0)&&!ImGui::IsMouseClicked(1)&&io.MouseWheel==0);
    io.AddMouseButtonEvent(0,false);io.AddMouseButtonEvent(1,false);f.Frame();CHECK(!f.clicked);
    g.NavDisableMouseHover=true;
    enabled=true; io.AddMousePosEvent(f.button.x+1,f.button.y); f.Frame();
    CHECK(!(io.ConfigFlags&ImGuiConfigFlags_NoMouse)&&!g.NavDisableMouseHover&&f.hovered);
    io.AddMouseButtonEvent(0,true); f.Frame();
    io.AddMouseButtonEvent(0,false); f.Frame();CHECK(f.clicked);
    io.AddMousePosEvent(f.slider.x,f.slider.y);f.Frame();
    io.AddMouseButtonEvent(0,true);f.Frame();CHECK(g.ActiveId&&g.ActiveIdSource==ImGuiInputSource_Mouse);
    const float before=f.value;
    enabled=false;io.AddMousePosEvent(f.slider.x+70,f.slider.y);UpdateUiPointer();
    CHECK(!g.ActiveId&&!io.MouseDown[0]);f.Frame();CHECK(f.value==before);
    for(auto source:{ImGuiInputSource_Keyboard,ImGuiInputSource_Gamepad}) {
        ImGui::SetActiveID(0x12345678,ImGui::FindWindowByName("Settings"));g.ActiveIdSource=source;
        UpdateUiPointer();CHECK(g.ActiveId==0x12345678&&g.ActiveIdSource==source);
        ImGui::ClearActiveID();
    }
}

int main() {
    QueuedEvents(); Interactions();
    {
        Fixture f; auto& io=ImGui::GetIO();
        io.AddMousePosEvent(f.button.x,f.button.y);f.Frame();CHECK(f.hovered);
        io.AddMouseButtonEvent(0,true);
        // Controller takeover and returning mouse motion both occur before the next UI frame.
        ++epoch; io.AddMousePosEvent(f.button.x+1,f.button.y);f.Frame();
        CHECK(f.hovered&&!ImGui::IsMouseClicked(0));
        io.AddMouseButtonEvent(0,false);f.Frame();CHECK(!f.clicked);
        io.AddMouseButtonEvent(0,true);f.Frame();
        io.AddMouseButtonEvent(0,false);f.Frame();CHECK(f.clicked);
    }
    std::puts("PASS actual pre-frame pointer gate: queued mouse ignored, nav/text/focus preserved, mouse drag canceled, keyboard/gamepad active IDs retained, one movement restores hover and fresh clicks");
}
'''


if __name__ == "__main__":
    unittest.main()
