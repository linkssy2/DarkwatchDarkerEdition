#include "graphics_reticle.h"
#include "graphics_camera.h"
#include "graphics_hud.h"
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
bool Player(const uint8_t* base, uint32_t camera, uint32_t& player) {
    if (!Span(base, camera, 0x68) || Read(base, camera) != 0x43F97C ||
        Read(base, camera + 0x58) || Read(base, camera + 0x60) != 0x3F800000) return false;
    const uint32_t top = Read(base, camera + 0x5C), height = Read(base, camera + 0x64);
    player = 0;
    if (height == 0x3EFEB852 && (top == 0 || top == 0x3F00A3D7)) player = top ? 1 : 0;
    else if (top || height != 0x3F800000) return false;
    return true;
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
    uint32_t player = 0;
    if (!Player(base, camera, player)) return;
    // Third-person shots converge on the centered camera target.
    float aim_x = 0, aim_y = 0;
    if (ctx.ebp >= 0x18 && DarkwatchThirdPersonReticle(base, player, aim_x, aim_y) &&
        Span(base, ctx.ebp - 0x18, 8)) {
        const uint32_t rw_camera = Read(base, camera + 0x34);
        if (Span(base, rw_camera, 0x64)) {
            const uint32_t raster = Read(base, rw_camera + 0x60);
            if (Span(base, raster, 0x14)) {
                const uint32_t width = Read(base, raster + 0xC), height = Read(base, raster + 0x10);
                float center[2];
                std::memcpy(center, base + ctx.ebp - 0x18, sizeof(center));
                // The final HUD quad narrows artwork around screen center.
                // Undo that scale for projected displacement only, so aiming
                // follows the world projection while reticle size stays unchanged.
                const float hud_scale = width <= 16384 && height <= 16384
                    ? DarkwatchHudHorizontalScale(base, camera) : 1;
                center[0] += aim_x * float(width) * 0.5f / hud_scale;
                center[1] -= aim_y * float(height) * 0.5f;
                if (width && height && width <= 32768 && height <= 32768 &&
                    std::isfinite(center[0]) && std::isfinite(center[1]))
                    std::memcpy(base + ctx.ebp - 0x18, center, sizeof(center));
            }
        }
    }
    const float scale = darkwatch::view::ReticleScale(player);
    if (scale == 1 || !std::isfinite(scale) || scale < 0 || scale > 2) return;

    // D6F51: the original reticle path has calculated pixel half-extents.
    // Its vertex consumer uses center +/- half-extents; UV and animation stay original.
    // At zero the native triangle strip is degenerate, so it draws no center pixel.
    float extents[2];
    std::memcpy(extents, base + ctx.ebp + 0x18, sizeof(extents));
    for (float& extent : extents) {
        extent *= scale;
        if (!std::isfinite(extent)) return;
    }
    std::memcpy(base + ctx.ebp + 0x18, extents, sizeof(extents));
}

void DarkwatchReticleColor(X86Context& ctx, uint8_t* base) {
    // 1EDAFE publishes the native vertices. Only D6E39's reticle draw may use
    // this option; scopes, HUD art, text and target markers keep their own tint.
    // 1ED841 uses an EBP biased by -0x74, and reuses its argument slot as UV
    // scratch. Its return is at +78; EBX still holds D6E39's draw rectangle.
    if (ctx.esi < 0x4C || ctx.ebp < 0x24 || !Span(base, ctx.ebp, 0x7C) ||
        Read(base, ctx.ebp + 0x78) != 0xD6FE0 || ctx.ebx != ctx.esi ||
        !Span(base, ctx.esp, 12) || Read(base, ctx.esp) != 4 || Read(base, ctx.esp + 8) != 4 ||
        Read(base, ctx.esp + 4) != ctx.ebp - 0x24 || !Span(base, ctx.ebp - 0x24, 4 * 28)) return;
    const uint32_t owner = ctx.esi - 0x4C;
    if (!Span(base, owner, 0x78) || Read(base, owner) != 0x428378) return;
    const uint32_t root = Read(base, owner + 4), camera = Read(base, ctx.esi + 0x20);
    uint32_t player;
    if (!Span(base, root, 0x1E0) || Read(base, root) != 0x427740 ||
        Read(base, root + 0x74) != owner || Read(base, root + 0x1DC) != camera ||
        !Player(base, camera, player)) return;

    // Native widget colors are byte-order RGBA, whereas the submitted vertex
    // is ARGB. Match authored colors before converting the requested RGB.
    // D77EF chooses normal/enemy; DE891/DE812 applies the teammate override.
    // Compare against this HUD's configured colors, not guessed hue thresholds.
    const uint32_t native = Read(base, owner + 0x74) & 0xFFFFFF;
    const auto settings = darkwatch::view::Snapshot(player);
    uint32_t color = darkwatch::view::kOriginalReticleColor;
    if (native == (Read(base, root + 0x118) & 0xFFFFFF)) color = settings.reticle_normal_color;
    if (native == (Read(base, root + 0x114) & 0xFFFFFF)) color = settings.reticle_enemy_color;
    const uint32_t teams = Read(base, root + 0x154);
    if (Span(base, teams, 0x148) && Read(base, teams) == 0x4281F8) {
        if (native == (Read(base, teams + 0x140) & 0xFFFFFF)) color = settings.reticle_enemy_color;
        if (native == (Read(base, teams + 0x13C) & 0xFFFFFF) ||
            native == (Read(base, teams + 0x144) & 0xFFFFFF)) color = settings.reticle_friendly_color;
    }
    if (color > 0xFFFFFF) return;
    for (unsigned i = 0; i < 4; ++i) {
        const uint32_t address = ctx.ebp - 0x24 + i * 28 + 16;
        const uint32_t tinted = (Read(base, address) & 0xFF000000) | color;
        std::memcpy(base + address, &tinted, sizeof(tinted));
    }
}
