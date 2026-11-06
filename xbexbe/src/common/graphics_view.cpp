#include "graphics_view.h"
#include <algorithm>
#include <atomic>
#include <array>
#include <toml++/toml.hpp>

namespace darkwatch::view {
namespace {
constexpr uint64_t kViewMask = 0xFFFFFFu;
constexpr uint64_t kFlagsMask = uint64_t(0x7F) << 57;
constexpr uint64_t kDefaultView = (uint64_t(100) << 16) | (uint64_t(100) << 8) | 100;
// One atomic value keeps each view and the shared display flags coherent.
std::atomic<uint64_t> g_settings{(uint64_t(7) << 60) | (uint64_t(1) << 58) | (uint64_t(3) << 48) | (kDefaultView << 24) | kDefaultView};
// Colors are independent choices, read only when emitting the reticle quad.
// Keep the hot FOV/scale/flag snapshot in its existing single atomic word.
std::array<std::array<std::atomic<uint32_t>, 3>, 2> g_colors{{
    {kOriginalReticleColor, kOriginalReticleColor, kOriginalReticleColor},
    {kOriginalReticleColor, kOriginalReticleColor, kOriginalReticleColor}}};

uint32_t ViewShift(uint32_t player) { return player == 1 ? 24u : 0u; }
uint32_t CameraShift(uint32_t player) { return player == 1 ? 52u : 50u; }
uint64_t PackView(const Settings& settings) {
    return (uint64_t(settings.viewmodel_fov_percent) << 16) |
           (uint64_t(settings.reticle_percent) << 8) | settings.fov_percent;
}
uint64_t PackFlags(const Settings& settings) {
    return (uint64_t(settings.show_fps) << 63) | (uint64_t(settings.hd_ui) << 62) |
           (uint64_t(settings.cutscene_borders) << 61) | (uint64_t(settings.hd_textures) << 60) |
           (uint64_t(settings.forever_ragdolls) << 59) | (uint64_t(settings.movie_aspect_fit) << 58) |
           (uint64_t(settings.original_ui_aspect) << 57);
}
Settings Unpack(uint64_t value, uint32_t player) {
    player = player == 1 ? 1 : 0;
    const uint64_t view = value >> ViewShift(player);
    return {uint32_t(view & 0xFFu), uint32_t((view >> 8) & 0xFFu),
            (value >> 63) != 0, ((value >> 62) & 1) != 0,
            uint32_t((view >> 16) & 0xFFu), ((value >> 61) & 1) != 0, ((value >> 60) & 1) != 0,
            ((value >> 59) & 1) != 0, ((value >> 58) & 1) != 0,
            ((value >> (48 + player)) & 1) != 0,
            g_colors[player][0].load(), g_colors[player][1].load(), g_colors[player][2].load(),
            CameraMode((value >> CameraShift(player)) & 3), ((value >> 57) & 1) != 0};
}
void StoreColors(const Settings& settings, uint32_t player) {
    auto& colors = g_colors[player == 1 ? 1 : 0];
    colors[0] = settings.reticle_normal_color;
    colors[1] = settings.reticle_enemy_color;
    colors[2] = settings.reticle_friendly_color;
}
void LoadView(const toml::table& table, Settings& settings) {
    if (auto value = table["field_of_view_scale"].is_integer() ? table["field_of_view_scale"].value<int64_t>() : std::nullopt)
        settings.fov_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(200)));
    if (auto value = table["reticle_size"].is_integer() ? table["reticle_size"].value<int64_t>() : std::nullopt)
        settings.reticle_percent = uint32_t(std::clamp(*value, int64_t(0), int64_t(200)));
    if (auto value = table["weapon_field_of_view_scale"].is_integer() ? table["weapon_field_of_view_scale"].value<int64_t>() : std::nullopt)
        settings.viewmodel_fov_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(150)));
    if (table["show_hud"].is_boolean()) settings.show_hud = table["show_hud"].value_or(true);
    if (table.contains("camera_mode")) {
        const auto value = table["camera_mode"].is_integer() ? table["camera_mode"].value<int64_t>() : std::nullopt;
        settings.camera_mode = value && *value >= 0 && *value <= 2 ? CameraMode(*value) : CameraMode::FirstPerson;
    }
    const char* keys[]{"reticle_normal_color", "reticle_enemy_color", "reticle_friendly_color"};
    uint32_t* colors[]{&settings.reticle_normal_color, &settings.reticle_enemy_color, &settings.reticle_friendly_color};
    for (unsigned i = 0; i < 3; ++i)
        if (auto value = table[keys[i]].is_integer() ? table[keys[i]].value<int64_t>() : std::nullopt)
            *colors[i] = *value >= 0 && *value <= 0xFFFFFF ? uint32_t(*value) : kOriginalReticleColor;
}
void SaveView(toml::table& table, const Settings& settings) {
    table.insert_or_assign("field_of_view_scale", int64_t(settings.fov_percent));
    table.insert_or_assign("reticle_size", int64_t(settings.reticle_percent));
    table.insert_or_assign("weapon_field_of_view_scale", int64_t(settings.viewmodel_fov_percent));
    table.insert_or_assign("show_hud", settings.show_hud);
    table.insert_or_assign("camera_mode", int64_t(settings.camera_mode));
    table.insert_or_assign("reticle_normal_color", int64_t(settings.reticle_normal_color));
    table.insert_or_assign("reticle_enemy_color", int64_t(settings.reticle_enemy_color));
    table.insert_or_assign("reticle_friendly_color", int64_t(settings.reticle_friendly_color));
}
}

Settings Normalize(Settings settings) {
    settings.fov_percent = std::clamp(settings.fov_percent, 50u, 200u);
    settings.reticle_percent = std::min(settings.reticle_percent, 200u);
    settings.viewmodel_fov_percent = std::clamp(settings.viewmodel_fov_percent, 50u, 150u);
    if (uint32_t(settings.camera_mode) > uint32_t(CameraMode::Shoulder)) settings.camera_mode = CameraMode::FirstPerson;
    for (uint32_t* color : {&settings.reticle_normal_color, &settings.reticle_enemy_color, &settings.reticle_friendly_color})
        if (*color > 0xFFFFFF) *color = kOriginalReticleColor;
    return settings;
}
Settings Snapshot(uint32_t player) {
    return Unpack(g_settings.load(), player);
}
void Apply(Settings settings, uint32_t player) {
    settings = Normalize(settings);
    const uint32_t shift = ViewShift(player);
    const uint32_t hud_bit = 48 + (player == 1 ? 1 : 0);
    const uint32_t camera_shift = CameraShift(player);
    const uint64_t mask = kFlagsMask | (kViewMask << shift) | (uint64_t(1) << hud_bit) | (uint64_t(3) << camera_shift);
    const uint64_t replacement = PackFlags(settings) | (PackView(settings) << shift) | (uint64_t(settings.show_hud) << hud_bit) |
        (uint64_t(settings.camera_mode) << camera_shift);
    StoreColors(settings, player);
    uint64_t previous = g_settings.load();
    while (!g_settings.compare_exchange_weak(previous, (previous & ~mask) | replacement)) {}
}
void Load(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    Settings settings;
    LoadView(t, settings);
    settings.show_fps = t["show_fps"].is_boolean() && t["show_fps"].value_or(false);
    settings.hd_ui = t["hd_ui"].is_boolean() ? t["hd_ui"].value_or(true) : true;
    settings.cutscene_borders = t["cutscene_borders"].is_boolean() ? t["cutscene_borders"].value_or(true) : true;
    settings.hd_textures = t["hd_textures"].is_boolean() ? t["hd_textures"].value_or(true) : true;
    settings.forever_ragdolls = t["forever_ragdolls"].is_boolean() && t["forever_ragdolls"].value_or(false);
    settings.movie_aspect_fit = t["movie_aspect_fit"].is_boolean() ? t["movie_aspect_fit"].value_or(true) : true;
    settings.original_ui_aspect = t["original_ui_aspect"].is_boolean() && t["original_ui_aspect"].value_or(false);
    // Existing installations keep their previous view for both players until edited.
    Settings player2 = settings;
    if (const auto* view = t["player2_view"].as_table()) LoadView(*view, player2);
    StoreColors(settings, 0);
    StoreColors(player2, 1);
    g_settings = PackFlags(settings) | PackView(settings) | (PackView(player2) << 24) |
        (uint64_t(settings.show_hud) << 48) | (uint64_t(player2.show_hud) << 49) |
        (uint64_t(settings.camera_mode) << CameraShift(0)) | (uint64_t(player2.camera_mode) << CameraShift(1));
}
void Save(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    const uint64_t value = g_settings.load();
    const Settings settings = Unpack(value, 0);
    SaveView(t, settings);
    t.insert_or_assign("show_fps", settings.show_fps);
    t.insert_or_assign("hd_ui", settings.hd_ui);
    t.insert_or_assign("cutscene_borders", settings.cutscene_borders);
    t.insert_or_assign("hd_textures", settings.hd_textures);
    t.insert_or_assign("forever_ragdolls", settings.forever_ragdolls);
    t.insert_or_assign("movie_aspect_fit", settings.movie_aspect_fit);
    t.insert_or_assign("original_ui_aspect", settings.original_ui_aspect);
    toml::table player2;
    SaveView(player2, Unpack(value, 1));
    t.insert_or_assign("player2_view", std::move(player2));
}
float ReticleScale(uint32_t player) {return float(Snapshot(player).reticle_percent) / 100.0f;}
} // namespace darkwatch::view
