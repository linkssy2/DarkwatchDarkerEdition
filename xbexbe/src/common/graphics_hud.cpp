#include "graphics_hud.h"
#include <array>
#include <cmath>
#include <cstring>
#include "app/app.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"

X86_EXTERN_FUNC(__imp__sub_001EE8BE);

namespace {
struct HudScope {uint8_t* base = nullptr; uint32_t root = 0, camera = 0; float anchor = 0;};
thread_local HudScope g_hud;

bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || !size || end > (uint64_t(1) << 32)) return false;
    for (uint64_t p = address & ~(uint64_t(mem::kPage) - 1); p < end; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t address) {
    uint32_t value; std::memcpy(&value, base + address, 4); return value;
}
float Float(const uint8_t* base, uint32_t address) {
    float value; std::memcpy(&value, base + address, 4); return value;
}
void Store(uint8_t* base, uint32_t address, float value) {
    std::memcpy(base + address, &value, 4);
}
bool Camera(const HudScope& scope) {
    // D835C copies the player's viewport into the HUD's own camera. Split views
    // retain their original layout, as do menus and unrelated screen overlays.
    if (!Span(scope.base, scope.root, 0x1E0) || Read(scope.base, scope.root) != 0x427740 ||
        Read(scope.base, scope.root + 0x1DC) != scope.camera ||
        !Span(scope.base, scope.camera, 0x68) || Read(scope.base, scope.camera) != 0x43F97C)
        return false;
    constexpr std::array<uint32_t, 4> viewport{0, 0, 0x3F800000, 0x3F800000};
    return !std::memcmp(scope.base + scope.camera + 0x58, viewport.data(), sizeof(viewport));
}
HudScope Scope(X86Context& ctx, uint8_t* base) {
    if (!app::Widescreen() || !Span(base, ctx.esp, 8)) return {};
    uint32_t child = ctx.ecx;
    for (unsigned depth = 0; depth < 24; ++depth) {
        if (!Span(base, child, 8)) return {};
        const uint32_t parent = Read(base, child + 4);
        if (!Span(base, parent, 8) || child == parent) return {};
        if (Read(base, parent) == 0x427740) {
            HudScope result{base, parent, Read(base, ctx.esp + 4), 0};
            if (!Camera(result)) return {};
            // Constructor DBB4C and layout D9FEC bind these complete groups.
            // Their descendants inherit one anchor, including numbers and art.
            for (uint32_t field : {0x64u, 0x6Cu, 0x78u, 0x68u})
                if (Read(base, parent + field) == child) return result;
            for (uint32_t field : {0x70u, 0x7Cu})
                if (Read(base, parent + field) == child) {result.anchor = 1; return result;}
            for (uint32_t field : {0x74u, 0x80u, 0x94u, 0xA8u, 0xF4u, 0xF8u, 0x10Cu})
                if (Read(base, parent + field) == child) {result.anchor = 0.5f; return result;}
            return {};
        }
        child = parent;
    }
    return {};
}
bool Active(uint8_t* base) {return g_hud.base == base && Camera(g_hud);}
} // namespace

X86_FUNC(sub_001EE8BE) {
    const HudScope previous = g_hud;
    g_hud = Scope(ctx, base);
    struct Restore {HudScope previous; ~Restore() {g_hud = previous;}} restore{previous};
    __imp__sub_001EE8BE(ctx, base);
}

void DarkwatchHudQuad(X86Context& ctx, uint8_t* base) {
    if (!Active(base) || !Span(base, ctx.esi, 0x24) ||
        Read(base, ctx.esi + 0x20) != g_hud.camera ||
        !Span(base, ctx.esp, 12) || Read(base, ctx.esp) != 4 || Read(base, ctx.esp + 8) != 4)
        return;
    const uint32_t vertices = Read(base, ctx.esp + 4);
    const uint32_t rw_camera = Read(base, g_hud.camera + 0x34);
    if (ctx.ebp < 0x24 || vertices != ctx.ebp - 0x24 || !Span(base, vertices, 4 * 28) ||
        !Span(base, rw_camera, 0x64)) return;
    const uint32_t raster = Read(base, rw_camera + 0x60);
    if (!Span(base, raster, 0x14)) return;
    const uint32_t width = Read(base, raster + 0xC), height = Read(base, raster + 0x10);
    if (!width || !height || width > 16384 || height > 16384) return;
    std::array<float, 4> x;
    for (unsigned i = 0; i < x.size(); ++i) {
        x[i] = Float(base, vertices + 28 * i);
        if (!std::isfinite(x[i])) return;
        x[i] = x[i] * 0.75f + float(width) * g_hud.anchor * 0.25f;
        if (!std::isfinite(x[i])) return;
    }
    for (unsigned i = 0; i < x.size(); ++i) Store(base, vertices + 28 * i, x[i]);
}

void DarkwatchHudFont(X86Context&, uint8_t* base) {
    if (!Active(base) || !Span(base, 0x4E37B0, 4) || !Span(base, 0x4E38B0, 16)) return;
    // 1EC5F4 selects the original [-1,1] HUD source rectangle via 113110.
    constexpr std::array<float, 4> rectangle{-1, -1, 2, 2};
    if (std::memcmp(base + 0x4E38B0, rectangle.data(), sizeof(rectangle))) return;
    const uint32_t index = Read(base, 0x4E37B0);
    // 112A80 allocates 32 matrices; the glyph renderer has just pushed its copy.
    if (!index || index >= 32 || !Span(base, 0x4E3730 + index * 4, 4)) return;
    const uint32_t matrix = Read(base, 0x4E3730 + index * 4);
    if (!Span(base, matrix, 0x40)) return;
    std::array<float, 4> x;
    for (unsigned i = 0; i < x.size(); ++i) {
        x[i] = Float(base, matrix + 0x10 * i);
        if (!std::isfinite(x[i])) return;
    }
    // This HUD text path is axis aligned. Do not reinterpret rotated 3D text.
    if (x[1] != 0 || x[2] != 0) return;
    for (float& value : x) value *= 0.75f;
    x[3] += (2 * g_hud.anchor - 1) * 0.25f;
    if (!std::isfinite(x[3])) return;
    for (unsigned i = 0; i < x.size(); ++i) Store(base, matrix + 0x10 * i, x[i]);
}
