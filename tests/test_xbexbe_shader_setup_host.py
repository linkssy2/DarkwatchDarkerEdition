"""Execute setup boot branches with recorded services; no window/game/GPU starts."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_xbexbe_io_apc import function

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'third_party/XboxXBERecomp/runtime/app/main.cpp'

FIXTURE = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <csignal>
#include <cstdio>
#include <cwchar>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
namespace fs=std::filesystem;
struct Stopped {int code;};
static std::vector<std::string> calls;
static int prepare_result, boot_mode, instance;
static bool find_ok=true, window_ok=true;
static uint64_t tick=200;
static std::wstring command_line;
static fs::path root, boot_data;
static void Seen(const char* s){calls.push_back(s);}
static bool Saw(const char* s){return std::find(calls.begin(),calls.end(),s)!=calls.end();}
[[noreturn]] static void FakeExitProcess(UINT code){Seen("exit");throw Stopped{int(code)};}
static void FakeSetUnhandledExceptionFilter(LPTOP_LEVEL_EXCEPTION_FILTER){Seen("exception_filter");}
static void FakeSetErrorMode(UINT){Seen("error_mode");}
static void FakeTimeBeginPeriod(unsigned){Seen("timer");}
static void FakeSetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT){Seen("dpi");}
static wchar_t* FakeGetCommandLineW(){return command_line.data();}
static HICON FakeLoadIconW(HINSTANCE,LPCWSTR){Seen("icon");return nullptr;}
static HGDIOBJ FakeGetStockObject(int){return nullptr;}
static ATOM FakeRegisterClassExW(const WNDCLASSEXW*){Seen("class");return 1;}
static HWND FakeCreateWindowExW(DWORD,LPCWSTR,LPCWSTR,DWORD,int,int,int,int,HWND,HMENU,HINSTANCE,LPVOID){Seen("hidden_window");return window_ok?reinterpret_cast<HWND>(1):nullptr;}
static void FakeShowWindow(HWND,int){Seen("show");}
static BOOL FakeRegisterRawInputDevices(PCRAWINPUTDEVICE,UINT,UINT){Seen("raw_input");return TRUE;}
static DWORD FakeGetCurrentProcessId(){return 123;}
static ULONGLONG FakeGetTickCount64(){return ++tick;}
static void FakeSetWindowTextW(HWND,LPCWSTR){Seen("window_title");}
static int FakeMessageBoxW(HWND,LPCWSTR,LPCWSTR,UINT){Seen("message_box");return 0;}
static BOOL FakeGetMessageW(MSG*,HWND,UINT,UINT){Seen("messages");return 0;}
static void FakeTranslateMessage(MSG*){Seen("translate");}
static void FakeDispatchMessageW(MSG*){Seen("dispatch");}
static void FakeChangeDisplaySettingsW(DEVMODEW*,DWORD){Seen("display_reset");}
#define ExitProcess FakeExitProcess
#define SetUnhandledExceptionFilter FakeSetUnhandledExceptionFilter
#define SetErrorMode FakeSetErrorMode
#define timeBeginPeriod FakeTimeBeginPeriod
#define SetProcessDpiAwarenessContext FakeSetProcessDpiAwarenessContext
#define GetCommandLineW FakeGetCommandLineW
#define LoadIconW FakeLoadIconW
#define GetStockObject FakeGetStockObject
#define RegisterClassExW FakeRegisterClassExW
#define CreateWindowExW FakeCreateWindowExW
#define ShowWindow FakeShowWindow
#define RegisterRawInputDevices FakeRegisterRawInputDevices
#define GetCurrentProcessId FakeGetCurrentProcessId
#define GetTickCount64 FakeGetTickCount64
#define SetWindowTextW FakeSetWindowTextW
#define MessageBoxW FakeMessageBoxW
#define GetMessageW FakeGetMessageW
#define TranslateMessage FakeTranslateMessage
#define DispatchMessageW FakeDispatchMessageW
#define ChangeDisplaySettingsW FakeChangeDisplaySettingsW
#define LOGE(...) ((void)0)
#define XBE_RELEASE 1
#define IMAGE_XBE "default.xbe"
#define IMGUI_CHECKVERSION() ((void)0)
struct ImGuiIO{const char* IniFilename=nullptr;int ConfigFlags=0;};
constexpr int ImGuiConfigFlags_NavEnableKeyboard=1,ImGuiConfigFlags_NavEnableGamepad=2,ImGuiConfigFlags_NoMouseCursorChange=4;
namespace ImGui{static ImGuiIO io;void CreateContext(){Seen("imgui");}ImGuiIO& GetIO(){return io;}}
static void ImGui_ImplWin32_Init(HWND){Seen("imgui_win32");}
namespace input{void Init(){Seen("input");}}
namespace logx{void Init(const std::string&,const std::string&,bool){Seen("log_init");}void Flush(){Seen("flush");}}
namespace app {
static bool g_preparing=false,g_mode_changed=false;
static HWND g_hwnd=nullptr;
static fs::path g_preparation_hdd;
bool PreparingShaders(){return g_preparing;}
[[noreturn]] void FinishPreparation(int);
LONG WINAPI WriteCrashDump(EXCEPTION_POINTERS*){Seen("crash_handler");return 0;}
static int Prepare(){Seen("prepare");return prepare_result;}
static void Init(){Seen("title_init");}
static void OnWindow(void*){Seen("title_window");}
struct Game{const wchar_t* name=L"fixture",*title=L"fixture",*short_title=L"fixture";const char* log="fixture";int(*prepare)()=Prepare;void(*init)()=Init;void(*window)(void*)=OnWindow;} kGame;
struct GameFiles{std::vector<unsigned char> xbe;fs::path dir;};
int Instance(){return instance;}
fs::path ExeDir(){return root;}
void Load(){Seen("settings");}
bool FindGame(GameFiles& game){Seen("find");game.dir=root/"assets";return find_ok;}
bool OpenSplash(){Seen("splash");return false;}
bool StartHandover(){Seen("handover");return false;}
void ApplyNow(){Seen("apply_display");}
void SyncInput(HWND){Seen("sync_input");}
LRESULT CALLBACK WndProc(HWND,UINT,WPARAM,LPARAM){return 0;}
}
namespace kernel {
bool Boot(std::vector<unsigned char>,const char*,const std::string&,const std::string& hdd){
    Seen("boot");boot_data=fs::path(hdd);
    if(app::PreparingShaders()){
        CHECK(boot_data.parent_path()==root/"cache/shader-preparation-hdd");
        CHECK(boot_data!=root/"hdd" && fs::is_directory(boot_data));
        std::ofstream(boot_data/"scratch-save.bin")<<"isolated";
    }
    if(boot_mode==1)app::FinishPreparation(0);
    return boot_mode!=2;
}
[[noreturn]] void Shutdown(int code){Seen("shutdown");throw Stopped{code};}
}
'''

DRIVER = r'''
static void Reset(){calls.clear();prepare_result=1;boot_mode=0;instance=0;find_ok=true;window_ok=true;app::g_preparing=false;app::g_mode_changed=false;app::g_preparation_hdd.clear();app::kGame.prepare=app::Prepare;boot_data.clear();}
static int Run(const wchar_t* text){command_line=text;try{return wWinMain(nullptr,nullptr,command_line.data(),0);}catch(Stopped e){return e.code;}}
static void NoPlayerMutation(){
    CHECK(fs::is_regular_file(root/"hdd/player-save.bin"));
    CHECK(fs::file_size(root/"hdd/player-save.bin")==6);
    CHECK(fs::file_size(root/"settings.toml")==8);
    for(const char* name:{"settings","title_init","title_window","show","apply_display","input","raw_input","sync_input","splash","handover","message_box","shutdown","display_reset"})CHECK(!Saw(name));
}
static void NoBoot(){CHECK(!Saw("boot")&&!Saw("hidden_window")&&!Saw("imgui")&&!Saw("timer")&&!Saw("log_init"));}
int main(int argc,char** argv){
    CHECK(argc==2);root=fs::path(argv[1]);fs::create_directories(root/"hdd");
    std::ofstream(root/"hdd/player-save.bin")<<"player";std::ofstream(root/"settings.toml")<<"settings";
    Reset();prepare_result=0;CHECK(Run(L"--prepare-shaders")==0);CHECK(Saw("prepare"));NoBoot();NoPlayerMutation();
    Reset();prepare_result=-1;CHECK(Run(L"--prepare-shaders")==1);NoBoot();NoPlayerMutation();
    Reset();app::kGame.prepare=nullptr;CHECK(Run(L"--prepare-shaders")==1);CHECK(!Saw("prepare"));NoBoot();NoPlayerMutation();
    Reset();find_ok=false;CHECK(Run(L"--prepare-shaders")==1);CHECK(!Saw("boot")&&!Saw("hidden_window"));NoPlayerMutation();
    Reset();window_ok=false;CHECK(Run(L"--prepare-shaders")==1);CHECK(!Saw("boot"));NoPlayerMutation();
    Reset();boot_mode=1;CHECK(Run(L"--prepare-shaders")==0);CHECK(Saw("hidden_window")&&Saw("boot")&&Saw("exit"));CHECK(!fs::exists(boot_data));NoPlayerMutation();auto first=boot_data;
    Reset();boot_mode=1;CHECK(Run(L"--prepare-shaders")==0);CHECK(boot_data!=first&&!fs::exists(boot_data));NoPlayerMutation();
    Reset();boot_mode=2;CHECK(Run(L"--prepare-shaders")==1);CHECK(Saw("boot")&&Saw("exit"));CHECK(!fs::exists(boot_data));NoPlayerMutation();
    Reset();CHECK(Run(L"--prepare-shaders")==1);CHECK(Saw("messages")&&Saw("exit"));CHECK(!fs::exists(boot_data));NoPlayerMutation();
    Reset();CHECK(Run(L"")==0);CHECK(!Saw("prepare"));CHECK(boot_data==root/"hdd");
    for(const char* name:{"settings","title_init","title_window","show","apply_display","input","raw_input","sync_input","splash","handover","shutdown"})CHECK(Saw(name));
    CHECK(fs::is_directory(root/"hdd"));
    std::puts("PASS setup boot: warm, errors, cold, fresh HDD, cleanup, normal mode");
}
'''


class ShaderSetupHostTests(unittest.TestCase):
    def test_executed_setup_and_normal_boot_branches(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ required for native host check')
        source = MAIN.read_text()
        fixture = FIXTURE + '\nnamespace app {\n' + function(source, '[[noreturn]] void FinishPreparation(int code)') + '\n}\n'
        fixture += function(source, 'int WINAPI wWinMain(') + DRIVER
        with tempfile.TemporaryDirectory(prefix='shader-setup-host-') as temporary:
            directory = Path(temporary)
            cpp, exe = directory / 'fixture.cpp', directory / 'fixture.exe'
            cpp.write_text(fixture)
            build = subprocess.run([compiler, '-std=c++20', '-O0', '-fuse-ld=lld', str(cpp), '-o', str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe), str(directory / 'owned-data')], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('PASS setup boot:', run.stdout)


if __name__ == '__main__':
    unittest.main()
