#pragma once
#include <cstdint>
#include <string>
#include "core/input.h"

namespace darkwatch {
struct ControlsSettings {
    input::PcBindings bindings;
    uint32_t mouse_millidegrees = 50;
    uint32_t zoom_sensitivity_percent = 100;
    std::array<bool, 2> sight_toggle{{true, true}};
    bool aim_assistance = true;
    bool aim_centering = true;
    bool carry_all_weapons = false;
    bool keep_starting_revolver = false;
    std::array<std::array<int, 2>, 2> weapon_buttons{{{{-1, -1}}, {{-1, -1}}}};
    std::array<bool, 2> walk_toggle{};
    std::array<int, 2> walk_buttons{{-1, -1}};
    std::array<int, 2> shoulder_buttons{{-1, -1}};
};

bool GetCarryAllWeapons();
bool GetKeepStartingRevolver();
ControlsSettings ControlsDefaults();
ControlsSettings ControlsSnapshot();
bool ControlsApply(const ControlsSettings& settings); // Live changes; app::Save persists them.
void ControlsLoad(const void* table);
void ControlsSave(void* table);
void ControlsWalkInput(int port, input::Pad& pad, bool on_foot, bool right_stick, uint32_t owner);

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
