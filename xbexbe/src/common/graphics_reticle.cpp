#include "graphics_reticle.h"
#include "graphics_view.h"
#include <cmath>
#include <cstring>
#include "cpu/x86_context.h"
#include "kernel/memory.h"

namespace {
bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t address) {
    uint32_t value;
    std::memcpy(&value, base + address, sizeof(value));
    return value;
}
}

void DarkwatchScaleReticle(X86Context& ctx, uint8_t* base) {
    if (ctx.ebx < 0x4C || !Span(base, ctx.ebp, 0x20) ||
        !Span(base, uint64_t(ctx.ebx) - 0x4C, 0x70)) return;
    const uint32_t owner = ctx.ebx - 0x4C;
    if (Read(base, owner) != 0x00428378 || Read(base, ctx.ebp + 4) != 0x000DCD20 ||
        Read(base, ctx.ebp + 8) != ctx.ebx || Read(base, ctx.ebp + 0xC) != owner + 0x34) return;

    // D835C copies this player's viewport into the HUD camera. D6F21 obtains
    // that same camera from the reticle draw, independently of pause-menu owner.
    const uint32_t camera = Read(base, ctx.ebx + 0x20);
    if (!Span(base, camera, 0x68) || Read(base, camera) != 0x43F97C ||
        Read(base, camera + 0x58) || Read(base, camera + 0x60) != 0x3F800000) return;
    const uint32_t top = Read(base, camera + 0x5C), height = Read(base, camera + 0x64);
    uint32_t player = 0;
    if (height == 0x3EFEB852 && (top == 0 || top == 0x3F00A3D7)) player = top ? 1 : 0;
    else if (top || height != 0x3F800000) return;
    const float scale = darkwatch::view::ReticleScale(player);
    if (scale == 1 || !std::isfinite(scale) || scale < 0.5f || scale > 2) return;

    // D6F51: the original reticle path has calculated pixel half-extents.
    // Its vertex consumer uses center +/- half-extents; center, UV and animation stay original.
    float extents[2];
    std::memcpy(extents, base + ctx.ebp + 0x18, sizeof(extents));
    for (float& extent : extents) {
        extent *= scale;
        if (!std::isfinite(extent)) return;
    }
    std::memcpy(base + ctx.ebp + 0x18, extents, sizeof(extents));
}
