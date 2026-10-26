#pragma once
#include <cstdint>

namespace darkwatch::view {
struct Settings {
    uint32_t fov_percent = 100;
    uint32_t reticle_percent = 100;
    bool show_fps = false;
    bool hd_ui = true;
    uint32_t viewmodel_fov_percent = 100;
    bool cutscene_borders = true;
    bool hd_textures = true;
};
// Players are zero-based; out-of-range indices use Player One.
Settings Snapshot(uint32_t player = 0);
Settings Normalize(Settings settings);
void Apply(Settings settings, uint32_t player = 0);
void Load(const void* table);
void Save(void* table);
float ReticleScale(uint32_t player = 0);
} // namespace darkwatch::view
