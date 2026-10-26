#include "graphics_view.h"
#include <algorithm>
#include <atomic>
#include <toml++/toml.hpp>

namespace darkwatch::view {
namespace {
constexpr uint64_t kViewMask = 0xFFFFFFu;
constexpr uint64_t kFlagsMask = uint64_t(0xF) << 60;
constexpr uint64_t kDefaultView = (uint64_t(100) << 16) | (uint64_t(100) << 8) | 100;
// One atomic value keeps each view and the shared display flags coherent.
std::atomic<uint64_t> g_settings{(uint64_t(7) << 60) | (kDefaultView << 24) | kDefaultView};

uint32_t ViewShift(uint32_t player) { return player == 1 ? 24u : 0u; }
uint64_t PackView(const Settings& settings) {
    return (uint64_t(settings.viewmodel_fov_percent) << 16) |
           (uint64_t(settings.reticle_percent) << 8) | settings.fov_percent;
}
uint64_t PackFlags(const Settings& settings) {
    return (uint64_t(settings.show_fps) << 63) | (uint64_t(settings.hd_ui) << 62) |
           (uint64_t(settings.cutscene_borders) << 61) | (uint64_t(settings.hd_textures) << 60);
}
Settings Unpack(uint64_t value, uint32_t player) {
    const uint64_t view = value >> ViewShift(player);
    return {uint32_t(view & 0xFFu), uint32_t((view >> 8) & 0xFFu),
            (value >> 63) != 0, ((value >> 62) & 1) != 0,
            uint32_t((view >> 16) & 0xFFu), ((value >> 61) & 1) != 0, ((value >> 60) & 1) != 0};
}
void LoadView(const toml::table& table, Settings& settings) {
    if (auto value = table["field_of_view_scale"].is_integer() ? table["field_of_view_scale"].value<int64_t>() : std::nullopt)
        settings.fov_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(200)));
    if (auto value = table["reticle_size"].is_integer() ? table["reticle_size"].value<int64_t>() : std::nullopt)
        settings.reticle_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(200)));
    if (auto value = table["weapon_field_of_view_scale"].is_integer() ? table["weapon_field_of_view_scale"].value<int64_t>() : std::nullopt)
        settings.viewmodel_fov_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(150)));
}
void SaveView(toml::table& table, const Settings& settings) {
    table.insert_or_assign("field_of_view_scale", int64_t(settings.fov_percent));
    table.insert_or_assign("reticle_size", int64_t(settings.reticle_percent));
    table.insert_or_assign("weapon_field_of_view_scale", int64_t(settings.viewmodel_fov_percent));
}
}

Settings Normalize(Settings settings) {
    settings.fov_percent = std::clamp(settings.fov_percent, 50u, 200u);
    settings.reticle_percent = std::clamp(settings.reticle_percent, 50u, 200u);
    settings.viewmodel_fov_percent = std::clamp(settings.viewmodel_fov_percent, 50u, 150u);
    return settings;
}
Settings Snapshot(uint32_t player) {
    return Unpack(g_settings.load(), player);
}
void Apply(Settings settings, uint32_t player) {
    settings = Normalize(settings);
    const uint32_t shift = ViewShift(player);
    const uint64_t mask = kFlagsMask | (kViewMask << shift);
    const uint64_t replacement = PackFlags(settings) | (PackView(settings) << shift);
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
    // Existing installations keep their previous view for both players until edited.
    Settings player2 = settings;
    if (const auto* view = t["player2_view"].as_table()) LoadView(*view, player2);
    g_settings = PackFlags(settings) | PackView(settings) | (PackView(player2) << 24);
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
    toml::table player2;
    SaveView(player2, Unpack(value, 1));
    t.insert_or_assign("player2_view", std::move(player2));
}
float ReticleScale(uint32_t player) {return float(Snapshot(player).reticle_percent) / 100.0f;}
} // namespace darkwatch::view
