"""Exercise the real audio settings callbacks through the portable TOML file path."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"

FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <toml++/toml.hpp>
#include "app/app.h"
#include "audio/audio.h"
#include "common/audio_settings.h"
#include "core/log.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
const app::GameInfo app::kGame={.settings="settings.toml",.load=darkwatch::AudioLoad,.save=darkwatch::AudioSave};
std::filesystem::path app::ExeDir(){return std::filesystem::current_path();}
void* app::Window(){return nullptr;}
void logx::Write(Level,const char*,...){}
// Device/mixer behavior has its own native fixture; this boundary observes persistence only.
static bool enabled;
void audio::SetSurroundEnabled(bool value){enabled=value;}
bool audio::SurroundEnabled(){return enabled;}
static void Write(const char* text){std::ofstream f("settings.toml");f<<text;CHECK(bool(f));}
int main(){
 // A first run or old settings file must reset a stale preference to the stereo default.
 audio::SetSurroundEnabled(true);app::Load();CHECK(!audio::SurroundEnabled());
 Write("fps_cap=80\nbrightness=90\n");audio::SetSurroundEnabled(true);app::Load();
 CHECK(!audio::SurroundEnabled()&&app::Snapshot().fps_cap==80&&app::Snapshot().brightness_percent==90);
 // Both choices survive a real save/reload, alongside the existing display preferences.
 for(bool choice:{true,false}){
  audio::SetSurroundEnabled(choice);CHECK(app::Save());
  auto saved=toml::parse_file("settings.toml");
  CHECK(saved["surround_sound"].is_boolean()&&saved["surround_sound"].value<bool>()==choice);
  CHECK(saved["fps_cap"].value<int>()==80&&saved["brightness"].value<int>()==90);
  audio::SetSurroundEnabled(!choice);app::Load();CHECK(audio::SurroundEnabled()==choice);
 }
 // Do not coerce strings/numbers/arrays/tables into enabling surround; malformed TOML
 // follows the same safe default as a missing file, without poisoning the next valid load.
 for(const char* invalid:{"surround_sound='true'\n","surround_sound=1\n","surround_sound=1.0\n",
     "surround_sound=[true]\n","[surround_sound]\nenabled=true\n","surround_sound=\n",
     "surround_sound=true\nsurround_sound=false\n"}){
  Write(invalid);audio::SetSurroundEnabled(true);app::Load();CHECK(!audio::SurroundEnabled());
  Write("surround_sound=true\n");app::Load();CHECK(audio::SurroundEnabled());
 }
 // Callback writes must replace a malformed existing key while preserving unrelated entries.
 toml::table table{{"surround_sound","old value"},{"unrelated",42}};
 audio::SetSurroundEnabled(false);darkwatch::AudioSave(&table);
 CHECK(table["surround_sound"].is_boolean()&&!table["surround_sound"].value_or(true));
 CHECK(table["unrelated"].value<int>()==42);
 std::puts("audio settings: real file roundtrip, legacy/first-run defaults, malformed TOML and strict boolean validation passed");
}
'''


class AudioSettingsTests(unittest.TestCase):
    def test_actual_audio_settings_file_roundtrip_and_defaults(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        with tempfile.TemporaryDirectory(prefix="audio-settings-", dir=ROOT / "build") as tmp:
            folder = Path(tmp)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(FIXTURE, encoding="utf-8")
            result = subprocess.run([
                compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK),
                "-I", str(ROOT / "xbexbe/src"),
                "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"),
                str(source), str(SDK / "app/settings.cpp"),
                str(ROOT / "xbexbe/src/common/audio_settings.cpp"),
                "-luser32", "-o", str(exe),
            ], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
