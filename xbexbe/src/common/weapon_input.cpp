#include "common/weapon_input.h"
#include "common/controls.h"
#include "common/carry_all_weapons.h"
#include <array>
#include <cstdint>
#include <mutex>

namespace {
struct State {
    uint64_t epoch = 0, started = 0;
    unsigned held = 0;
    int action = -1;
    bool release = false;
};
std::mutex lock;
std::array<State, 2> states;
}

void DarkwatchWeaponInput(int port, input::Pad& pad) {
    if (port < 0 || port >= 2) return;
    const auto frame = input::GetMouseSnapshot();
    const auto controls = darkwatch::ControlsSnapshot();
    const auto mapping = input::GetPadBindings(port);
    unsigned down = 0;
    if (frame.active) for (unsigned i = 0; i < 2; ++i) {
        const int physical = controls.weapon_buttons[port][i];
        if (physical >= 0 && (pad.physical_buttons & (1u << physical))) {
            down |= 1u << i;
            // Override only this physical button; retain an independently held PC action.
            for (unsigned action = 0; action < mapping.size(); ++action) if (mapping[action] == physical) {
                const bool pc = port == 0 && input::PcActionDown(input::PcAction(action));
                if (action < 8) {if (!pc) pad.buttons &= uint16_t(~(1u << action));}
                else pad.analog[action - 8] = pc ? 255 : 0;
            }
        }
        if (port == 0 && input::PcActionDown(i ? input::PcAction::PreviousWeapon : input::PcAction::NextWeapon))
            down |= 1u << i;
    }
    std::lock_guard guard(lock);
    auto& state = states[port];
    if (!frame.active || !frame.published_us || frame.active_epoch != state.epoch) {
        state = {frame.active_epoch, 0, down};
        DarkwatchQueueWeaponCycle(unsigned(port), 0);
        return;
    }
    const unsigned pressed = down & ~state.held;
    state.held = down;
    if (state.action >= 0 && frame.published_us - state.started >= 150000) {
        state.action = -1; state.release = true; state.started = frame.published_us;
    }
    // The original state machine must observe a released frame between swaps.
    if (state.release) {
        if (frame.published_us == state.started) return;
        state.release = false;
    }
    if (state.action < 0 && (pressed == 1 || pressed == 2)) {
        const int action = DarkwatchWeaponCycleAction(unsigned(port));
        if (action >= 0 && action < 16) {
            DarkwatchQueueWeaponCycle(unsigned(port), pressed == 1 ? 1 : -1);
            state.action = action; state.started = frame.published_us;
        }
    }
    if (state.action >= 0) {
        if (state.action < 8) pad.buttons |= uint16_t(1u << state.action);
        else pad.analog[state.action - 8] = 255;
    }
}
