#pragma once
#include <cstdint>
#include <string>
#include "core/input.h"

namespace darkwatch {
struct ControlsSettings {
    input::PcBindings bindings;
    uint32_t mouse_millidegrees = 50;
    uint32_t zoom_sensitivity_percent = 100;
    bool aim_assistance = true;
    bool aim_centering = true;
    bool carry_all_weapons = false;
    std::array<std::array<int, 2>, 2> weapon_buttons{{{{-1, -1}}, {{-1, -1}}}};
};

bool GetCarryAllWeapons();
ControlsSettings ControlsDefaults();
ControlsSettings ControlsSnapshot();
bool ControlsApply(const ControlsSettings& settings); // Live changes; app::Save persists them.
void ControlsLoad(const void* table);
void ControlsSave(void* table);

constexpr uint32_t kCaptureCancelled = UINT32_MAX;
constexpr uint32_t kCaptureClear = UINT32_MAX - 1;
constexpr uint32_t kCaptureReserved = UINT32_MAX - 2;
void ControlsBeginCapture();
void ControlsCancelCapture();
bool ControlsCapturing();
uint32_t ControlsTakeCapture(); // 0 pending, a virtual key/kMouseWheel, or a kCapture result.
std::string ControlsKeyName(uint32_t key);
bool ControlsMessage(void* window, uint32_t message, uintptr_t wp, intptr_t lp, intptr_t* result);
} // namespace darkwatch
