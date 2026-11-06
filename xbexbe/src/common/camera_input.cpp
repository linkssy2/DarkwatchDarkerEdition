#include "camera_input.h"
#include "controls.h"
#include "graphics_camera.h"
#include "kernel/kernel.h"
#include <array>
#include <mutex>

namespace {
struct ShoulderInput {
    uint64_t epoch = 0;
    uint32_t actor = 0;
    bool held = false;
};
std::mutex g_shoulder_lock;
std::array<ShoulderInput, 2> g_shoulder_input;
}

void DarkwatchShoulderInput(int port, input::Pad& pad, bool on_foot, uint32_t actor) {
    if (port < 0 || port >= 2) return;
    const auto frame = input::GetMouseSnapshot();
    const int button = darkwatch::ControlsSnapshot().shoulder_buttons[port];
    const bool physical = button >= 0 && button < 16 && (pad.physical_buttons & (1u << button));
    const bool held = physical || (port == 0 && input::PcActionDown(input::PcAction::SwapShoulder));
    std::lock_guard lock(g_shoulder_lock);
    auto& state = g_shoulder_input[port];
    if (!on_foot || !actor || !frame.active || !frame.published_us ||
        !DarkwatchShoulderAvailable(kernel::g_base, actor)) {
        state = {frame.active_epoch, 0, held};
        return;
    }
    // Preserve a fresh press requirement through pause, focus and respawn changes.
    if (state.epoch != frame.active_epoch || state.actor != actor)
        state = {frame.active_epoch, actor, held};
    else if (held && !state.held) DarkwatchSwapShoulder(kernel::g_base, actor);
    state.held = held;
    if (!physical) return;
    const auto mapping = input::GetPadBindings(port);
    for (unsigned action = 0; action < mapping.size(); ++action) if (mapping[action] == button) {
        const bool pc = port == 0 && input::PcActionDown(input::PcAction(action));
        if (action < 8) {if (!pc) pad.buttons &= uint16_t(~(1u << action));}
        else pad.analog[action - 8] = pc ? 255 : 0;
    }
}
