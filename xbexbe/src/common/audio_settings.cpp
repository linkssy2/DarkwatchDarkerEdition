#include "audio_settings.h"
#include "audio/audio.h"
#include "kernel/memory.h"
#include <cstring>
#include <toml++/toml.hpp>

namespace darkwatch {
void SyncAudioDevice(uint8_t* base) {
    // HLE device creation skips the native constructor; XACT still reads its speaker mode.
    constexpr uint32_t address = 0x003C5C14;
    if (!base || !mem::IsCommitted(address)) return;
    const uint32_t mode = audio::SurroundEnabled() && audio::SurroundAvailable() ? 2 : 0;
    uint32_t current;
    std::memcpy(&current, base + address, sizeof current);
    if (current != mode) std::memcpy(base + address, &mode, sizeof mode);
}
void AudioLoad(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    auto mode = audio::SoundOutput::Stereo;
    if (t.contains("sound_output")) {
        const auto value = t["sound_output"].value<std::string>();
        if (value == "5.1") mode = audio::SoundOutput::Surround51;
        else if (value == "7.1") mode = audio::SoundOutput::Surround71;
    } else if (t["surround_sound"].is_boolean() && t["surround_sound"].value_or(false)) {
        mode = audio::SoundOutput::Surround51;
    }
    audio::SetSoundOutput(mode);
}
void AudioSave(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    const auto mode = audio::GetSoundOutput();
    t.insert_or_assign("sound_output", mode == audio::SoundOutput::Surround71 ? "7.1" :
                                     mode == audio::SoundOutput::Surround51 ? "5.1" : "stereo");
    // Retain the old preference for users who roll back to a previous build.
    t.insert_or_assign("surround_sound", mode != audio::SoundOutput::Stereo);
}
}
