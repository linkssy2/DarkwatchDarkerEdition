#include "graphics_cinematic.h"
#include <cstring>
#include "graphics_view.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"

namespace {
bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || end > (uint64_t(1) << 32)) return false;
    for (uint64_t p = address & ~(uint64_t(mem::kPage) - 1); p < end; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t address) {
    uint32_t value; std::memcpy(&value, base + address, sizeof(value)); return value;
}
} // namespace

bool DarkwatchHideCinematicBorder(X86Context& ctx, uint8_t* base) {
    if (darkwatch::view::Snapshot().cutscene_borders || ctx.esi < 0x29 ||
        !Span(base, 0x4B7A41, 0x2B)) return false;
    // PlayMovie sets this flag around its separate movie renderer. The original
    // cinematic manager uses phases 1/2/3 for entering, playing and leaving.
    const uint32_t phase = Read(base, 0x4B7A4C);
    if (base[0x4B7A41] || phase < 1 || phase > 3) return false;
    const uint32_t effect = ctx.esi - 0x29;
    // At both quad calls in ScreenMaskEffect::Draw, ESI points at its color.
    // Only the manager's own border effect is skipped; its update/lifetime,
    // camera begin/end, ordinary fades and subtitle drawings remain original.
    return Read(base, 0x4B7A68) == effect && Span(base, effect, 0x3C) &&
           Read(base, effect) == 0x478244;
}
