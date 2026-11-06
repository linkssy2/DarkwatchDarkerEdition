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
#include <cstring>
#include <vector>
#include <toml++/toml.hpp>
#include "app/app.h"
#include "audio/audio.h"
#include "kernel/memory.h"
#include "common/audio_settings.h"
#include "core/log.h"
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
const app::GameInfo app::kGame={.settings="settings.toml",.load=darkwatch::AudioLoad,.save=darkwatch::AudioSave};
std::filesystem::path app::ExeDir(){return std::filesystem::current_path();}
void* app::Window(){return nullptr;}
void logx::Write(Level,const char*,...){}
// Device/mixer behavior has its own native fixture; this boundary observes persistence only.
static audio::SoundOutput requested=audio::SoundOutput::Stereo;
static unsigned capacity=2;
static bool committed=true;
bool mem::IsCommitted(uint32_t address){CHECK(address==0x3C5C14);return committed;}
void audio::SetSoundOutput(SoundOutput mode){requested=mode;}
audio::SoundOutput audio::GetSoundOutput(){return requested;}
void audio::SetSurroundEnabled(bool value){requested=value?SoundOutput::Surround51:SoundOutput::Stereo;}
bool audio::SurroundEnabled(){return requested!=SoundOutput::Stereo;}
bool audio::SurroundAvailable(){return capacity>=6;}
static void Write(const char* text){std::ofstream f("settings.toml");f<<text;CHECK(bool(f));}
int main(){
 using audio::SoundOutput;
 const SoundOutput modes[]{SoundOutput::Stereo,SoundOutput::Surround51,SoundOutput::Surround71};
 const char* names[]{"stereo","5.1","7.1"};
 // Only a configured surround device enables native rear calculations; writes stay on the guest thread.
 std::vector<uint8_t> guest(0x400000,0xA5);
 for(auto choice:modes)for(unsigned channels:{2u,6u,8u}){
  requested=choice;capacity=channels;darkwatch::SyncAudioDevice(guest.data());
  uint32_t mode;std::memcpy(&mode,guest.data()+0x3C5C14,4);CHECK(mode==(choice!=SoundOutput::Stereo&&channels>=6?2u:0u));
  auto snapshot=guest;darkwatch::SyncAudioDevice(guest.data());CHECK(snapshot==guest);
 }
 for(size_t i=0;i<guest.size();++i)if(i<0x3C5C14||i>=0x3C5C18)CHECK(guest[i]==0xA5);
 auto snapshot=guest;committed=false;requested=SoundOutput::Stereo;darkwatch::SyncAudioDevice(guest.data());
 CHECK(snapshot==guest);darkwatch::SyncAudioDevice(nullptr);committed=true;
 // A first run or old settings file must reset a stale preference to the stereo default.
 audio::SetSurroundEnabled(true);app::Load();CHECK(!audio::SurroundEnabled());
 Write("fps_cap=80\nbrightness=90\n");audio::SetSurroundEnabled(true);app::Load();
 CHECK(!audio::SurroundEnabled()&&app::Snapshot().fps_cap==80&&app::Snapshot().brightness_percent==90);
 // The requested choice survives fallback hardware and restart. Save a compatible
 // boolean for rollback; never replace a 7.1 request with the current device mode.
 for(unsigned i=0;i<3;++i)for(unsigned channels:{2u,6u,8u}){
  capacity=channels;audio::SetSoundOutput(modes[i]);CHECK(app::Save());
  auto saved=toml::parse_file("settings.toml");
  CHECK(saved["sound_output"].value<std::string>()==names[i]);
  CHECK(saved["surround_sound"].is_boolean()&&saved["surround_sound"].value<bool>()==(i!=0));
  CHECK(saved["fps_cap"].value<int>()==80&&saved["brightness"].value<int>()==90);
  audio::SetSoundOutput(modes[(i+1)%3]);app::Load();CHECK(audio::GetSoundOutput()==modes[i]);
 }
 // A legacy surround preference means 5.1. An explicit new setting has precedence,
 // even when the rollback boolean disagrees, and invalid new settings fail closed.
 Write("surround_sound=true\n");app::Load();CHECK(audio::GetSoundOutput()==SoundOutput::Surround51);
 Write("surround_sound=false\n");app::Load();CHECK(audio::GetSoundOutput()==SoundOutput::Stereo);
 for(unsigned i=0;i<3;++i){
  const std::string value=std::string("sound_output='")+names[i]+"'\nsurround_sound="+(i?"false":"true")+"\n";
  Write(value.c_str());app::Load();CHECK(audio::GetSoundOutput()==modes[i]);
 }
 for(const char* invalid:{"'auto'","'7.1 Surround'","'STEREO'","''","7.1","true","1","['7.1']","{mode='7.1'}"}){
  const std::string text=std::string("sound_output=")+invalid+"\nsurround_sound=true\n";
  Write(text.c_str());audio::SetSoundOutput(SoundOutput::Surround71);app::Load();
  CHECK(audio::GetSoundOutput()==SoundOutput::Stereo);
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
 toml::table table{{"surround_sound","old value"},{"sound_output",42},{"unrelated",42}};
 audio::SetSurroundEnabled(false);darkwatch::AudioSave(&table);
 CHECK(table["surround_sound"].is_boolean()&&!table["surround_sound"].value_or(true));
 CHECK(table["sound_output"].value<std::string>()=="stereo");
 CHECK(table["unrelated"].value<int>()==42);
 std::puts("audio settings: three-mode roundtrip on 2/6/8-channel devices, native mode, legacy migration, new-key precedence, malformed TOML and strict validation passed");
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
