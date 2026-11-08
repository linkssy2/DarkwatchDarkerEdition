#pragma once
#include <cstdint>

namespace darkwatch::view {
// A color outside RGB's 24 bits means keep the game's authored color.
inline constexpr uint32_t kOriginalReticleColor = 0x1000000;
enum class CameraMode : uint32_t { FirstPerson = 0, Centered = 1, Shoulder = 2 };
struct Settings {
    uint32_t fov_percent = 100;
    uint32_t reticle_percent = 100;
    bool show_fps = false;
    bool hd_ui = true;
    uint32_t viewmodel_fov_percent = 100;
    bool cutscene_borders = true;
    bool hd_textures = true;
    bool forever_ragdolls = false;
    bool movie_aspect_fit = true;
    bool show_hud = true;
    uint32_t reticle_normal_color = kOriginalReticleColor;
    uint32_t reticle_enemy_color = kOriginalReticleColor;
    uint32_t reticle_friendly_color = kOriginalReticleColor;
    CameraMode camera_mode = CameraMode::FirstPerson;
    bool original_ui_aspect = false;
    bool vertical_split = false;
};
// Players are zero-based; out-of-range indices use Player One.
Settings Snapshot(uint32_t player = 0);
Settings Normalize(Settings settings);
void Apply(Settings settings, uint32_t player = 0);
void Load(const void* table);
void Save(void* table);
float ReticleScale(uint32_t player = 0);
} // namespace darkwatch::view
