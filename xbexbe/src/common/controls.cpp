#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <cstdio>
#include <mutex>
#include <toml++/toml.hpp>
#include "common/controls.h"
#include "core/log.h"

namespace darkwatch {
namespace {
std::mutex g_controls_lock, g_capture_lock;
bool g_capturing = false;
uint32_t g_captured = 0;
constexpr const char* kBindingKeys[] = {
    "dpad_up", "dpad_down", "dpad_left", "dpad_right", "start", "back", "left_thumb", "right_thumb",
    "a", "b", "x", "y", "black", "white", "left_trigger", "right_trigger",
    "move_forward", "move_backward", "move_left", "move_right"
};
static_assert(std::size(kBindingKeys) == size_t(input::PcAction::Count));

ControlsSettings& Settings() {
    static ControlsSettings settings = ControlsDefaults();
    return settings;
}
} // namespace

ControlsSettings ControlsDefaults() {
    ControlsSettings defaults{input::DefaultPcBindings()};
    defaults.bindings[size_t(input::PcAction::Start)] = {{VK_ESCAPE, VK_RETURN}};
    defaults.bindings[size_t(input::PcAction::B)] = {{'B', 0}};
    return defaults;
}

ControlsSettings ControlsSnapshot() {
    std::lock_guard lock(g_controls_lock);
    return Settings();
}

bool ControlsApply(const ControlsSettings& settings) {
    auto next = settings;
    next.mouse_millidegrees = std::clamp(next.mouse_millidegrees, 1u, 1000u);
    next.zoom_sensitivity_percent = std::clamp(next.zoom_sensitivity_percent, 10u, 200u);
    std::lock_guard lock(g_controls_lock);
    // Rebinding also invalidates motion/held input before the new settings are visible.
    if (!input::SetPcBindings(next.bindings)) return false;
    // Original SwitchPrimaryWeapon states require a 0.1-second held input.
    input::SetWheelPulseDuration(150000);
    input::SetMouseToStick(false);
    Settings() = next;
    return true;
}

void ControlsLoad(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    auto next = ControlsDefaults();
    auto sensitivity = t["mouse_millidegrees_per_count"].value<int64_t>();
    if (sensitivity) next.mouse_millidegrees = uint32_t(std::clamp(*sensitivity, int64_t(1), int64_t(1000)));
    auto zoom = t["zoom_sensitivity_percent"].value<int64_t>();
    if (zoom) next.zoom_sensitivity_percent = uint32_t(std::clamp(*zoom, int64_t(10), int64_t(200)));
    next.aim_assistance = t["aim_assistance"].value_or(next.aim_assistance);
    next.aim_centering = t["aim_centering"].value_or(next.aim_centering);
    bool malformed = false;
    if (auto* bindings = t["key_bindings"].as_table()) {
        for (size_t i = 0; i < next.bindings.size(); ++i) {
            auto node = (*bindings)[kBindingKeys[i]];
            if (!node) continue;
            auto* row = node.as_array();
            if (!row || row->size() != 2) { malformed = true; continue; }
            for (size_t slot = 0; slot < 2; ++slot) {
                auto key = (*row)[slot].value<int64_t>();
                if (!key || *key < 0 || *key > input::kMouseWheel) { malformed = true; break; }
                next.bindings[i].keys[slot] = uint32_t(*key);
            }
        }
    } else if (t.contains("key_bindings")) malformed = true;
    if (malformed || !ControlsApply(next)) {
        LOGW("controls: invalid or conflicting bindings; default bindings restored");
        next.bindings = ControlsDefaults().bindings;
        ControlsApply(next);
    }
    const auto* controllers = t["controller_bindings"].as_table();
    for (int port = 0; port < 2; ++port) {
        auto bindings = input::DefaultPadBindings();
        const auto* row = controllers ? (*controllers)[port ? "player_2" : "player_1"].as_array() : nullptr;
        bool valid = row && row->size() == bindings.size();
        if (valid) for (size_t i = 0; i < bindings.size(); ++i) {
            const auto button = (*row)[i].value<int64_t>();
            if (!button || *button < 0 || *button >= int64_t(bindings.size())) { valid = false; break; }
            bindings[i] = uint8_t(*button);
        }
        if (!valid || !input::SetPadBindings(port, bindings)) input::SetPadBindings(port, input::DefaultPadBindings());
    }
}

void ControlsSave(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    auto settings = ControlsSnapshot();
    t.erase("direct_mouse"); // Retire the legacy mouse-to-stick preference.
    t.insert_or_assign("mouse_millidegrees_per_count", int64_t(settings.mouse_millidegrees));
    t.insert_or_assign("zoom_sensitivity_percent", int64_t(settings.zoom_sensitivity_percent));
    t.insert_or_assign("aim_assistance", settings.aim_assistance);
    t.insert_or_assign("aim_centering", settings.aim_centering);
    toml::table bindings;
    for (size_t i = 0; i < settings.bindings.size(); ++i)
        bindings.insert(kBindingKeys[i], toml::array{int64_t(settings.bindings[i].keys[0]), int64_t(settings.bindings[i].keys[1])});
    t.insert_or_assign("key_bindings", std::move(bindings));
    toml::table controllers;
    for (int port = 0; port < 2; ++port) {
        toml::array row;
        for (auto button : input::GetPadBindings(port)) row.push_back(int64_t(button));
        controllers.insert(port ? "player_2" : "player_1", std::move(row));
    }
    t.insert_or_assign("controller_bindings", std::move(controllers));
}

void ControlsBeginCapture() {
    input::CancelPadCapture();
    std::lock_guard lock(g_capture_lock);
    g_captured = 0; g_capturing = true;
}
void ControlsCancelCapture() {
    input::CancelPadCapture();
    std::lock_guard lock(g_capture_lock);
    g_captured = 0; g_capturing = false;
}
bool ControlsCapturing() {
    std::lock_guard lock(g_capture_lock);
    return g_capturing;
}
uint32_t ControlsTakeCapture() {
    std::lock_guard lock(g_capture_lock);
    uint32_t result = g_captured;
    g_captured = 0;
    return result;
}

bool ControlsMessage(void*, uint32_t message, uintptr_t wp, intptr_t lp, intptr_t* result) {
    std::lock_guard lock(g_capture_lock);
    if (message == WM_KILLFOCUS || message == WM_DESTROY ||
        (message == WM_ACTIVATE && LOWORD(wp) == WA_INACTIVE)) {
        input::CancelPadCapture();
        if (!g_capturing) return false;
        g_capturing = false; g_captured = kCaptureCancelled;
        return false;
    }
    if (!g_capturing) return false;
    uint32_t key = 0;
    if (message == WM_KEYDOWN || message == WM_SYSKEYDOWN) {
        if (lp & (intptr_t(1) << 30)) { *result = 0; return true; }
        key = uint32_t(wp);
    } else if (message == WM_LBUTTONDOWN) key = VK_LBUTTON;
    else if (message == WM_RBUTTONDOWN) key = VK_RBUTTON;
    else if (message == WM_MBUTTONDOWN) key = VK_MBUTTON;
    else if (message == WM_XBUTTONDOWN) key = HIWORD(wp) == XBUTTON1 ? VK_XBUTTON1 : VK_XBUTTON2;
    else if (message == WM_MOUSEWHEEL) {
        if (!int16_t(HIWORD(wp))) { *result = 0; return true; }
        key = input::kMouseWheel;
    }
    else return false;
    if (key == VK_ESCAPE) { g_captured = kCaptureCancelled; g_capturing = false; }
    else if (key == VK_BACK || key == VK_DELETE) { g_captured = kCaptureClear; g_capturing = false; }
    else if (!key || key > input::kMouseWheel || key == VK_F1 || key == VK_F3 || key == VK_LWIN || key == VK_RWIN) {
        g_captured = kCaptureReserved;
    } else { g_captured = key; g_capturing = false; }
    *result = message == WM_XBUTTONDOWN ? TRUE : 0;
    return true;
}

std::string ControlsKeyName(uint32_t key) {
    switch (key) {
        case 0: return "Unbound";
        case VK_LBUTTON: return "Mouse 1";
        case VK_RBUTTON: return "Mouse 2";
        case VK_MBUTTON: return "Mouse 3";
        case VK_XBUTTON1: return "Mouse 4";
        case VK_XBUTTON2: return "Mouse 5";
        case input::kMouseWheel: return "Mouse Wheel";
        case VK_SHIFT: return "Shift";
        case VK_CONTROL: return "Ctrl";
        case VK_MENU: return "Alt";
    }
    UINT scan = MapVirtualKeyW(key, MAPVK_VK_TO_VSC);
    LONG code = LONG(scan << 16);
    if ((key >= VK_PRIOR && key <= VK_DOWN) || key == VK_INSERT || key == VK_DELETE || key == VK_DIVIDE || key == VK_NUMLOCK)
        code |= 1 << 24;
    wchar_t name[64]{};
    char utf8[256]{};
    if (scan && GetKeyNameTextW(code, name, int(std::size(name))) &&
        WideCharToMultiByte(CP_UTF8, 0, name, -1, utf8, int(std::size(utf8)), nullptr, nullptr)) return utf8;
    std::snprintf(utf8, sizeof(utf8), "Key %u", key);
    return utf8;
}
} // namespace darkwatch
