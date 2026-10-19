#include "graphics_view.h"
#include <algorithm>
#include <atomic>
#include <toml++/toml.hpp>

namespace darkwatch::view {
namespace {
std::atomic<uint64_t> g_settings{(uint64_t(1) << 62) | (uint64_t(1) << 61) |
    (uint64_t(100) << 32) | (uint64_t(100) << 16) | 100};
}

Settings Normalize(Settings settings) {
    settings.fov_percent = std::clamp(settings.fov_percent, 50u, 150u);
    settings.reticle_percent = std::clamp(settings.reticle_percent, 50u, 200u);
    settings.viewmodel_fov_percent = std::clamp(settings.viewmodel_fov_percent, 50u, 150u);
    return settings;
}
Settings Snapshot() {
    const uint64_t value = g_settings.load();
    return {uint32_t(value & 0xFFFFu), uint32_t((value >> 16) & 0xFFFFu),
            (value >> 63) != 0, ((value >> 62) & 1) != 0,
            uint32_t((value >> 32) & 0xFFFFu), ((value >> 61) & 1) != 0};
}
void Apply(Settings settings) {
    settings = Normalize(settings);
    g_settings = (uint64_t(settings.show_fps) << 63) | (uint64_t(settings.hd_ui) << 62) |
                 (uint64_t(settings.cutscene_borders) << 61) | (uint64_t(settings.viewmodel_fov_percent) << 32) |
                 (uint64_t(settings.reticle_percent) << 16) | settings.fov_percent;
}
void Load(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    Settings settings;
    if (auto value = t["field_of_view_scale"].is_integer() ? t["field_of_view_scale"].value<int64_t>() : std::nullopt)
        settings.fov_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(150)));
    if (auto value = t["reticle_size"].is_integer() ? t["reticle_size"].value<int64_t>() : std::nullopt)
        settings.reticle_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(200)));
    if (auto value = t["weapon_field_of_view_scale"].is_integer() ? t["weapon_field_of_view_scale"].value<int64_t>() : std::nullopt)
        settings.viewmodel_fov_percent = uint32_t(std::clamp(*value, int64_t(50), int64_t(150)));
    settings.show_fps = t["show_fps"].is_boolean() && t["show_fps"].value_or(false);
    settings.hd_ui = t["hd_ui"].is_boolean() ? t["hd_ui"].value_or(true) : true;
    settings.cutscene_borders = t["cutscene_borders"].is_boolean() ? t["cutscene_borders"].value_or(true) : true;
    Apply(settings);
}
void Save(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    const Settings settings = Snapshot();
    t.insert_or_assign("field_of_view_scale", int64_t(settings.fov_percent));
    t.insert_or_assign("reticle_size", int64_t(settings.reticle_percent));
    t.insert_or_assign("show_fps", settings.show_fps);
    t.insert_or_assign("hd_ui", settings.hd_ui);
    t.insert_or_assign("weapon_field_of_view_scale", int64_t(settings.viewmodel_fov_percent));
    t.insert_or_assign("cutscene_borders", settings.cutscene_borders);
}
float ReticleScale() {return float(Snapshot().reticle_percent) / 100.0f;}
} // namespace darkwatch::view
