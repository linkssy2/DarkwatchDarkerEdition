#pragma once
#include <array>
#include <cstdint>

namespace darkwatch::viewport {
enum class Kind { Invalid, Full, Horizontal, Vertical };
struct View {
    Kind kind = Kind::Invalid;
    uint32_t player = 0;
    bool Split() const {return kind == Kind::Horizontal || kind == Kind::Vertical;}
};
// Match only the native full view and the two supported split layouts.
inline View Identify(uint32_t x, uint32_t y, uint32_t width, uint32_t height) {
    constexpr uint32_t one = 0x3F800000, half = 0x3EFEB852, second = 0x3F00A3D7;
    if (!x && !y && width == one && height == one) return {Kind::Full, 0};
    if (!x && width == one && height == half && (!y || y == second))
        return {Kind::Horizontal, y ? 1u : 0u};
    if (!y && height == one && width == half && (!x || x == second))
        return {Kind::Vertical, x ? 1u : 0u};
    return {};
}
inline std::array<uint32_t, 4> Split(bool vertical, uint32_t player) {
    const uint32_t offset = player == 1 ? 0x3F00A3D7 : 0;
    return vertical ? std::array<uint32_t, 4>{offset, 0, 0x3EFEB852, 0x3F800000}
                    : std::array<uint32_t, 4>{0, offset, 0x3F800000, 0x3EFEB852};
}
} // namespace darkwatch::viewport
