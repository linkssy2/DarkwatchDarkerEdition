#pragma once
#include <cstdint>

namespace darkwatch::view {
struct Settings {
    uint32_t fov_percent = 100;
    uint32_t reticle_percent = 100;
    bool show_fps = false;
    bool hd_ui = true;
};
Settings Snapshot();
Settings Normalize(Settings settings);
void Apply(Settings settings);
void Load(const void* table);
void Save(void* table);
float ReticleScale();
} // namespace darkwatch::view
