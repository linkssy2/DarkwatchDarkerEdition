#pragma once
// Guest keyboard and mouse as player 2, using the title's default PC bindings
// (controls.cpp ControlsDefaults) so the guest plays with the keys the host knows.
#include <algorithm>
#include <cstdint>
#include "common/coop_protocol.h"

namespace darkwatch::coop::keys {

struct Binding {uint8_t keys[2];};
// Order: the 8 digital buttons, the 8 analog buttons, then forward/back/left/right.
constexpr Binding kBindings[20] = {
    {{0x26, 0}}, {{0x28, 0}}, {{0x25, 0}}, {{0x27, 0}},  // D-pad: arrows
    {{0x1B, 0x0D}}, {{0x09, 0}}, {{'C', 0}}, {{'F', 0}},  // Start Esc/Enter, Back Tab, thumbs C/F
    {{0x20, 'E'}}, {{'B', 0}}, {{'R', 0}}, {{'Q', 0}},    // A Space/E, B, X R, Y Q
    {{'G', 0}}, {{0x10, 0}}, {{0x02, 0}}, {{0x01, 0}},    // Black G, White Shift, LT right mouse, RT left mouse
    {{'W', 0}}, {{'S', 0}}, {{'A', 0}}, {{'D', 0}},
};

// Mouse counts per microsecond to stick, as the runtime's mouse-to-stick fallback.
inline int16_t MouseAxis(int64_t counts, uint64_t elapsed_us) {
    if (!elapsed_us || elapsed_us > 250000) return 0;
    return int16_t(std::clamp(double(counts) * 17066667.0 / double(elapsed_us), -32768.0, 32767.0));
}

// Adds held keys to a controller state; keys win only where they are active.
template <class Held>
void Merge(PadState& p, Held held, int64_t mouse_dx, int64_t mouse_dy, uint64_t elapsed_us) {
    auto action = [&](unsigned i) {return (kBindings[i].keys[0] && held(kBindings[i].keys[0])) ||
                                          (kBindings[i].keys[1] && held(kBindings[i].keys[1]));};
    for (unsigned i = 0; i < 8; ++i) if (action(i)) p.buttons |= uint16_t(1u << i);
    for (unsigned i = 0; i < 8; ++i) if (action(i + 8)) p.analog[i] = 255;
    const bool forward = action(16), backward = action(17), left = action(18), right = action(19);
    if (forward || backward || left || right) {
        const int x = int(right) - int(left), y = int(forward) - int(backward);
        const int scale = x && y ? 23170 : 32767;
        p.lx = int16_t(x * scale); p.ly = int16_t(y * scale);
    }
    const int16_t rx = MouseAxis(mouse_dx, elapsed_us), ry = MouseAxis(-mouse_dy, elapsed_us);
    if (rx || ry) {p.rx = rx; p.ry = ry;}
}

} // namespace darkwatch::coop::keys
