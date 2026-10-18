#pragma once
#include <cstdint>

namespace darkwatch {
enum class GraphicsMenuRoute { Hidden, OptionsMain, Visual, Controls };
struct GraphicsRouteState {
    GraphicsMenuRoute route = GraphicsMenuRoute::Hidden;
    uint32_t options = 0;
    uint32_t page = 0;
    bool subtitles_available = false;
    bool subtitles = false;
    bool controls_available = false;
    bool invert = false, vibration = false;
    int32_t sensitivity = 0, sensitivity_min = 0, sensitivity_max = 0;
    int32_t controller_preset = -1; // Default, Chieftain, Lefty, Hopalong, Hoss; -1 unknown.
    bool paused = false;
    bool pause_settings_available = false;
};

// Call on the guest thread. UI callers must use a published snapshot instead.
GraphicsRouteState QueryGraphicsMenuRoute(const uint8_t* base);
// Rejects an old UI request if its original Options object is no longer active.
bool SetGraphicsSubtitles(uint8_t* base, uint32_t expected_options, bool enabled);
bool SetOriginalControls(uint8_t* base, uint32_t expected_options, bool invert, bool vibration, int32_t sensitivity);
bool SetControllerPreset(uint8_t* base, uint32_t expected_options, int32_t preset);
bool OpenControllerConfiguration(uint8_t* base, uint32_t expected_options);
// Use the Pause owner's registered original Controls page and normal page push.
bool OpenPauseSettings(uint8_t* base, uint32_t expected_options);
// Add real original MenuItem objects to the validated Pause main list.
bool EnsureNativePauseEntries(uint8_t* base);
// Consume the added row after the original action opened its Controls handler:
// 0 = no added entry, 1 = Graphics, 2 = Controls.
uint32_t TakeNativePauseEntry(uint8_t* base, uint32_t expected_options);
}  // namespace darkwatch

struct X86Context;
// Original localization result for GEN_Visual, after its owned reference is assigned.
void DarkwatchGraphicsLabel(X86Context& ctx, uint8_t* base);
