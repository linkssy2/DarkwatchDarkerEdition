"""Exercise production input startup against pinned SDL, without a game or window."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"
SDL = ROOT / "build/xbexbe/_deps/sdl3-src"
SDL_LIB = ROOT / "build/xbexbe/_deps/sdl3-build/SDL3-static.lib"
CLANG = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/Llvm/x64/bin/clang++.exe")


class ReleaseSdlLoggingTests(unittest.TestCase):
    def test_release_blocks_inherited_verbosity_and_retains_capped_errors(self):
        self.assertTrue(CLANG.is_file() and SDL_LIB.is_file(), "Pinned built SDL and Clang are required")
        with tempfile.TemporaryDirectory(prefix="sdl-quiet-", dir=ROOT / "build") as temporary:
            folder = Path(temporary)
            source = folder / "test.cpp"
            source.write_text(FIXTURE, encoding="utf-8")
            for release in (False, True):
                with self.subTest(release=release):
                    profile = "release" if release else "diagnostic"
                    exe = folder / (profile + ".exe")
                    args = [str(CLANG), "-std=c++20", "-O1", "-fms-runtime-lib=dll",
                            "-Wl,/NODEFAULTLIB:libcmt", "-DSDL_STATIC_LIB", "-I", str(SDK),
                            "-I", str(SDL / "include"), str(source), str(SDK / "core/log.cpp"), str(SDL_LIB)]
                    if release:
                        args.append("-DXBE_RELEASE")
                    args += ["-l" + name for name in ("kernel32", "user32", "gdi32", "winmm", "imm32",
                             "ole32", "oleaut32", "version", "uuid", "advapi32", "setupapi", "shell32", "dinput8")]
                    built = subprocess.run(args + ["-o", str(exe)], capture_output=True, text=True, timeout=90)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    # All values are inherited by the real SDL process, rather than a mock.
                    env = dict(os.environ, SDL_LOGGING="verbose", DEBUG_INVOCATION="1",
                               XBE_PERF="1", XBE_D3D12_DEBUG="1", XBE_CAPTURE_DIR=str(folder / "captures"))
                    result = subprocess.run([str(exe), str(folder / profile)], env=env,
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, "")
                    if release:
                        self.assertEqual(result.stderr, "")
                        error = folder / profile / "logs/test-error.log"
                        self.assertEqual(error.stat().st_size, 65536)
                        text = error.read_text()
                        self.assertIn("SDL: kept error 100%", text)
                        self.assertIn("SDL: kept critical", text)
                        self.assertNotIn("routine marker", text)
                    self.assertFalse((folder / "captures").exists())


FIXTURE = r'''
#include <filesystem>
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "core/input.cpp"
namespace fs = std::filesystem;
#define CHECK(x) do { if(!(x)) { std::fprintf(stderr,"line %d: %s [%s]\n",__LINE__,#x,SDL_GetError());std::exit(90); } } while(0)
const app::GameInfo app::kGame = {};
static unsigned diagnostic_calls = 0;
static void SDLCALL DiagnosticSink(void*, int, SDL_LogPriority, const char*) { ++diagnostic_calls; }
int main(int argc, char** argv) {
    CHECK(argc == 2);
    const fs::path root = argv[1], logs = root / "logs";
    logx::Init(logs.string(), "test");
#ifndef XBE_RELEASE
    // A diagnostic build must retain an existing logger and environment priorities.
    SDL_SetLogOutputFunction(DiagnosticSink, nullptr);
#endif
    // Isolate the fixture from real pads and rumble; no game/window/video subsystem.
    for (const char* hint : {SDL_HINT_JOYSTICK_HIDAPI, SDL_HINT_JOYSTICK_WGI, SDL_HINT_XINPUT_ENABLED,
                            SDL_HINT_JOYSTICK_DIRECTINPUT, SDL_HINT_JOYSTICK_RAWINPUT, SDL_HINT_JOYSTICK_THREAD})
        CHECK(SDL_SetHintWithPriority(hint, "0", SDL_HINT_OVERRIDE));
    input::Init();
    CHECK(SDL_WasInit(SDL_INIT_GAMEPAD));
    SDL_LogOutputFunction sink = nullptr;
    void* data = nullptr;
    SDL_GetLogOutputFunction(&sink, &data);
#ifdef XBE_RELEASE
    CHECK(sink && sink != SDL_GetDefaultLogOutputFunction() && sink != DiagnosticSink);
    CHECK(std::strcmp(SDL_GetHint(SDL_HINT_LOGGING), "error") == 0);
    CHECK(!SDL_SetHint(SDL_HINT_LOGGING, "verbose"));
    SDL_ResetLogPriorities();
    for (int category : {SDL_LOG_CATEGORY_APPLICATION, SDL_LOG_CATEGORY_ASSERT,
                         SDL_LOG_CATEGORY_TEST, SDL_LOG_CATEGORY_SYSTEM, SDL_LOG_CATEGORY_CUSTOM})
        CHECK(SDL_GetLogPriority(category) == SDL_LOG_PRIORITY_ERROR);
    CHECK(!fs::exists(logs));
    // Even a later library priority change cannot reopen routine console/file output.
    SDL_SetLogPriorities(SDL_LOG_PRIORITY_VERBOSE);
    SDL_LogVerbose(SDL_LOG_CATEGORY_APPLICATION, "routine marker verbose");
    SDL_LogDebug(SDL_LOG_CATEGORY_SYSTEM, "routine marker debug");
    SDL_LogInfo(SDL_LOG_CATEGORY_APPLICATION, "routine marker info");
    SDL_LogWarn(SDL_LOG_CATEGORY_ASSERT, "routine marker warning");
    CHECK(!fs::exists(logs));
    SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "kept error 100%%");
    SDL_LogCritical(SDL_LOG_CATEGORY_SYSTEM, "kept critical");
    logx::Flush();
    CHECK(fs::exists(logs / "test-error.log"));
    const std::string large(4000, 'x');
    for (int i = 0; i < 40; ++i) SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "%s", large.c_str());
    CHECK(fs::file_size(logs / "test-error.log") == 65536);
#else
    CHECK(sink == DiagnosticSink);
    CHECK(std::strcmp(SDL_GetHint(SDL_HINT_LOGGING), "verbose") == 0);
    CHECK(SDL_GetLogPriority(SDL_LOG_CATEGORY_APPLICATION) == SDL_LOG_PRIORITY_VERBOSE);
    auto before = diagnostic_calls;
    SDL_LogVerbose(SDL_LOG_CATEGORY_APPLICATION, "routine marker verbose");
    SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "diagnostic error");
    CHECK(diagnostic_calls == before + 2);
#endif
    SDL_Quit();
}
'''


if __name__ == "__main__":
    unittest.main()
