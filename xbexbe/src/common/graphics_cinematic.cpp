#include "graphics_cinematic.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include "app/app.h"
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
bool MenuBackground(const X86Context& ctx, const uint8_t* base, uint32_t info, bool active_frontend = false) {
    // E4EBD draws only the frontend background movie at manager+74. Unlike
    // fullscreen playback, its manager is in the quad's saved EDI, not ESI.
    if (!Span(base, ctx.ebp - 0x90, 0xAC) || Read(base, ctx.ebp + 4) != 0x1EEB44 ||
        Read(base, ctx.ebp + 0x18) != 0xE4F73) return false;
    const uint32_t manager = Read(base, ctx.ebp - 0x90);
    if (!Span(base, manager, 0x78)) return false;
    if (active_frontend && (!Span(base, 0x4AD664, 4) || Read(base, 0x4AD664) != manager ||
        Read(base, manager + 8) == 0 || Read(base, manager + 8) > 20)) return false;
    const uint32_t owner = Read(base, manager + 0x74);
    if (!Span(base, owner, 0x2C) || Read(base, owner + 0x24) != info ||
        Read(base, owner + 0x28) != ctx.esi) return false;
    constexpr char expected[] = "movies/mainmenu.sfd";
    const uint32_t name = Read(base, owner);
    if (!Span(base, name, 2 + sizeof(expected))) return false;
    for (unsigned i = 0; i < sizeof(expected); ++i) {
        const char c = char(base[uint64_t(name) + 2 + i]);
        const char normalized = c == '\\' ? '/' : c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
        if (normalized != expected[i]) return false;
    }
    return true;
}
struct MovieBars { uint16_t top = 0, bottom = 0; };
MovieBars AuthoredMovieBars(const X86Context& ctx, const uint8_t* base, uint32_t info) {
    // Original fullscreen caller preserves the movie owner in the quad's saved ESI.
    if (!Span(base, ctx.ebp - 0x90, 0xAC) || Read(base, ctx.ebp + 4) != 0x1EEB44 ||
        Read(base, ctx.ebp + 0x18) != 0x1EB609) return {};
    const uint32_t owner = Read(base, ctx.ebp - 0x8C);
    if (!Span(base, owner, 0x2C) || Read(base, owner + 0x24) != info ||
        Read(base, owner + 0x28) != ctx.esi) return {};
    const uint32_t name = Read(base, owner);
    if (!Span(base, name, 2)) return {};
    char path[96];
    for (unsigned i = 0; i < sizeof(path); ++i) {
        const uint64_t address = uint64_t(name) + 2 + i;
        if (!Span(base, address, 1)) return {};
        const char c = char(base[address]);
        path[i] = c == '\\' ? '/' : c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
        if (!c) break;
        if (i == sizeof(path) - 1) return {};
    }
    // Audited scene bounds retain a margin; the two flash-spill exceptions are noted below.
    static constexpr struct { const char* name; MovieBars bars; } movies[] = {
        {"movies/animatic1.sfd", {18, 14}},
        {"movies/animatic2.sfd", {18, 14}},
        {"movies/animatic3.sfd", {18, 14}},
        {"movies/conceptart_movie1.sfd", {12, 12}},
        {"movies/conceptart_movie10.sfd", {12, 12}},
        {"movies/conceptart_movie11.sfd", {12, 12}},
        {"movies/conceptart_movie2.sfd", {12, 12}},
        {"movies/conceptart_movie3.sfd", {12, 12}},
        {"movies/conceptart_movie4.sfd", {12, 12}},
        {"movies/conceptart_movie5.sfd", {12, 12}},
        {"movies/conceptart_movie6.sfd", {12, 12}},
        {"movies/conceptart_movie7.sfd", {12, 12}},
        {"movies/conceptart_movie8.sfd", {12, 12}},
        {"movies/conceptart_movie9.sfd", {12, 12}},
        {"movies/dwe3trailer.sfd", {14, 54}},
        {"movies/intro.sfd", {64, 66}},
        {"movies/m01s1.sfd", {64, 64}},
        // Brief bloom spills into the bars; retain scene framing instead of shrinking the whole movie.
        {"movies/m01s2.sfd", {60, 60}},
        {"movies/m01s4.sfd", {64, 62}},
        {"movies/m02s1.sfd", {60, 66}},
        {"movies/m04s1.sfd", {64, 64}},
        {"movies/m05s1.sfd", {62, 62}},
        {"movies/m07s1.sfd", {64, 64}},
        {"movies/m08s1.sfd", {64, 66}},
        {"movies/m09s2.sfd", {66, 66}},
        {"movies/m09s3.sfd", {64, 64}},
        {"movies/m10s1.sfd", {64, 64}},
        {"movies/m11s2.sfd", {60, 60}}, // Same authored flash spill as M01S2.
        {"movies/m12s2.sfd", {62, 60}},
        {"movies/m21s1.sfd", {64, 64}},
        {"movies/m22s1.sfd", {62, 60}},
        {"movies/m22s2.sfd", {62, 62}},
        {"movies/m22s3.sfd", {62, 60}},
        {"movies/m22s4.sfd", {64, 64}},
    };
    for (const auto& movie : movies)
        if (std::strcmp(path, movie.name) == 0) return movie.bars;
    return {};
}
} // namespace

void DarkwatchFitMovie(X86Context& ctx, uint8_t* base) {
    if (!Span(base, 0x4B7A41, 1) ||
        ctx.ebp < 0x90 || ctx.esp != ctx.ebp - 0x90 ||
        !Span(base, ctx.ebp - 0x84, 0x98)) return;
    const uint32_t info = Read(base, ctx.ebp + 0x10);
    if (!Span(base, info, 0x10)) return;
    const bool fullscreen = base[0x4B7A41] != 0;
    const bool original_menu = !fullscreen && darkwatch::view::Snapshot().original_ui_aspect &&
        MenuBackground(ctx, base, info, true);
    // The scoped frontend viewport already fits the logical canvas. Replacement
    // movies with another aspect fit inside it; story FMVs retain their own setting.
    const float display = original_menu ? 4.f / 3.f : app::RenderAspect();
    if (!std::isfinite(display) || display <= 0 ||
        (!fullscreen && !original_menu &&
         (display <= 4.f / 3.f || display == 16.f / 9.f || !MenuBackground(ctx, base, info)))) return;
    const uint32_t width = Read(base, info + 8), height = Read(base, info + 12);
    if (!width || !height || width > 8192 || height > 8192) return;
    struct Vertex { float x, y, z, rhw; uint32_t color; float u, v; } vertices[4];
    static_assert(sizeof(Vertex) == 28);
    std::memcpy(vertices, base + ctx.ebp - 0x84, sizeof(vertices));
    const float screen_w = vertices[2].x, screen_h = vertices[1].y;
    if (!std::isfinite(screen_w) || !std::isfinite(screen_h) ||
        screen_w <= 0 || screen_h <= 0 || screen_w > 8192 || screen_h > 8192 ||
        vertices[0].x != 0 || vertices[0].y != 0 || vertices[1].x != 0 ||
        vertices[2].y != 0 || vertices[3].x != screen_w || vertices[3].y != screen_h) return;
    if (!fullscreen && !original_menu) {
        // Cover the screen proportionally from the existing 16:9 menu composition.
        // Crop its sides on 16:10 and its top/bottom on ultrawide; UI/FMVs are separate.
        const float left = vertices[0].u, right = vertices[2].u;
        const float top = vertices[0].v, bottom = vertices[1].v;
        if (!std::isfinite(left) || !std::isfinite(right) || left < 0 || right > 1 ||
            left >= right || vertices[1].u != left || vertices[3].u != right ||
            !std::isfinite(top) || !std::isfinite(bottom) || top < 0 || bottom > 1 ||
            top >= bottom || vertices[2].v != top || vertices[3].v != bottom) return;
        if (display < 16.f / 9.f) {
            const float inset = (right - left) * (1 - display / (16.f / 9.f)) * .5f;
            vertices[0].u = vertices[1].u = left + inset;
            vertices[2].u = vertices[3].u = right - inset;
        } else {
            const float inset = (bottom - top) * (1 - (16.f / 9.f) / display) * .5f;
            vertices[0].v = vertices[2].v = top + inset;
            vertices[1].v = vertices[3].v = bottom - inset;
        }
        std::memcpy(base + ctx.ebp - 0x84, vertices, sizeof(vertices));
        return;
    }
    MovieBars bars;
    if (fullscreen && !darkwatch::view::Snapshot().movie_aspect_fit && width == 640 && height == 480 &&
        vertices[0].v == 0 && vertices[2].v == 0 && vertices[1].v == vertices[3].v &&
        std::isfinite(vertices[1].v) && vertices[1].v > 0 && vertices[1].v <= 1) {
        bars = AuthoredMovieBars(ctx, base, info);
        const float v = vertices[1].v;
        vertices[0].v = vertices[2].v = v * float(bars.top) / float(height);
        vertices[1].v = vertices[3].v = v * float(height - bars.bottom) / float(height);
    }
    // Fit proportionally inside the audited scene bounds in Fill mode.
    const float aspect = float(width) / float(height - bars.top - bars.bottom);
    const float w = screen_w * std::min(1.f, aspect / display);
    const float h = screen_h * std::min(1.f, display / aspect);
    for (auto& vertex : vertices) {
        vertex.x = (screen_w - w) * .5f + vertex.x / screen_w * w;
        vertex.y = (screen_h - h) * .5f + vertex.y / screen_h * h;
    }
    std::memcpy(base + ctx.ebp - 0x84, vertices, sizeof(vertices));
}

void DarkwatchCinematicBorderProjection(X86Context& ctx, uint8_t* base) {
    if (!app::Widescreen() || !darkwatch::view::Snapshot().cutscene_borders ||
        !Span(base, 0x4B7A41, 0x2B) || base[0x4B7A41] ||
        Read(base, 0x4B7A4C) < 1 || Read(base, 0x4B7A4C) > 3 ||
        Read(base, 0x4B7A68) != ctx.esi || !Span(base, ctx.esi, 0x3C) ||
        Read(base, ctx.esi) != 0x478244 || ctx.ebp < 0x68 ||
        ctx.esp != ctx.ebp - 0x68 || !Span(base, ctx.ebp, 12)) return;
    float target, amount;
    std::memcpy(&target, base + ctx.esi + 0x30, 4);
    std::memcpy(&amount, base + ctx.esi + 0x24, 4);
    if (!std::isfinite(target) || target < 0.5f || target > 1.0f ||
        !std::isfinite(amount) || amount < 0 || amount > 1) return;
    // Ultrawide cameras extend the 16:9 shot horizontally, retaining its vertical framing.
    const float ratio = std::min(app::RenderAspect(), 16.0f / 9.0f) / (4.0f / 3.0f);
    const float thickness = std::max(0.0f, 0.5f - (target - 0.5f) * ratio) * amount;
    std::memcpy(base + ctx.ebp + 8, &thickness, 4);
}

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

bool DarkwatchHideSubtitleBackground(X86Context& ctx, uint8_t* base) {
    if (ctx.ebp < 0x78 || ctx.esp != ctx.ebp - 0x78 ||
        !Span(base, ctx.esp, 0x78) ||
        !Span(base, ctx.ebx, 0x10)) return false;
    // ClearSubtitle clears the current owner before its queued final draw is removed.
    // The subtitle type and exact panel call remain valid throughout that lifetime.
    return Read(base, ctx.ebx) == 0x43FB40 &&
           Read(base, ctx.esp) == ctx.ebp - 0x68 &&
           Read(base, ctx.ebp - 4) == 0xB4000000;
}
