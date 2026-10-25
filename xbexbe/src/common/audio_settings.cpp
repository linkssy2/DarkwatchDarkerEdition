#include "audio_settings.h"
#include "audio/audio.h"
#include <toml++/toml.hpp>

namespace darkwatch {
void AudioLoad(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    audio::SetSurroundEnabled(t["surround_sound"].is_boolean() && t["surround_sound"].value_or(false));
}
void AudioSave(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    t.insert_or_assign("surround_sound", audio::SurroundEnabled());
}
}
