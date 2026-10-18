#include "graphics_camera.h"
#include <array>
#include <cmath>
#include <cstring>
#include <mutex>
#include "graphics_view.h"
#include "app/app.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"

extern "C" void sub_00216B7C(X86Context& ctx, uint8_t* base);

namespace {
constexpr uint32_t kPlayerCamera = 0x00491668;
constexpr std::array<uint32_t, 7> kConfiguration = {
    0x3F800000, 0x3FAAAAAB, 0, 0, 0x3F800000, 0x3F800000, 0};
struct PlayerCamera {uint32_t owner = 0, camera = 0, raster = 0; float aspect_scale = 1;};
std::mutex g_camera_lock;
PlayerCamera g_player_camera;

bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || !size || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t address) {
    uint32_t value;
    std::memcpy(&value, base + address, sizeof(value));
    return value;
}
}  // namespace

void DarkwatchConfigurePlayerCamera(X86Context& ctx, uint8_t* base) {
    // F9B1D owns this component; F9B78 passes aspect then scale to the original setter.
    // Other view layouts and temporary cameras keep their authored settings.
    if (ctx.esi != kPlayerCamera || !Span(base, kPlayerCamera, sizeof(kConfiguration)) ||
        std::memcmp(base + kPlayerCamera, kConfiguration.data(), sizeof(kConfiguration)) ||
        !Span(base, ctx.esp, 8) || Read(base, ctx.esp) != kConfiguration[1] ||
        Read(base, ctx.esp + 4) != kConfiguration[0] || !Span(base, ctx.edi, 0x14) ||
        Read(base, ctx.edi + 0xC) != ctx.ecx || !Span(base, ctx.ecx, 0x68) ||
        Read(base, ctx.ecx) != 0x0043F97C) return;

    const bool wide = app::Widescreen();
    const float aspect = wide ? 16.0f / 9.0f : 4.0f / 3.0f;
    const float aspect_scale = wide ? aspect / (4.0f / 3.0f) : 1.0f;
    const float scale = aspect_scale * (float(darkwatch::view::Snapshot().fov_percent) / 100.0f);
    if (wide || scale != 1.0f) {
        // Original FOV updates use tan(FOV/2)*scale, then divide by aspect for Y.
        // Scaling both preserves vertical framing and widens X, including later zooms.
        std::memcpy(base + ctx.esp, &aspect, sizeof(aspect));
        std::memcpy(base + ctx.esp + 4, &scale, sizeof(scale));
    }
    {
        std::lock_guard lock(g_camera_lock);
        g_player_camera = {ctx.edi, ctx.ecx, Read(base, ctx.ecx + 0x34), aspect_scale};
    }
    LOG_FIRST(4, "Player camera %08X: %s projection (authored zoom retained)",
              ctx.ecx, wide ? "16:9" : "4:3");
}

void DarkwatchUpdatePlayerView(X86Context& ctx, uint8_t* base) {
    PlayerCamera player;
    {std::lock_guard lock(g_camera_lock); player = g_player_camera;}
    // At 21606D the original active-camera update has finished; ESI is its owning
    // component. Never apply this preference to a separate weapon/render camera.
    if (!player.owner || ctx.esi != player.owner || !Span(base, player.owner, 0x14) ||
        Read(base, player.owner + 0xC) != player.camera || !Span(base, player.camera, 0x68) ||
        Read(base, player.camera) != 0x43F97C || Read(base, player.camera + 0x34) != player.raster ||
        !Span(base, player.raster, 0x78)) return;
    const float scale = player.aspect_scale * (float(darkwatch::view::Snapshot().fov_percent) / 100.0f);
    float previous, nominal;
    std::memcpy(&previous, base + player.camera + 0x48, 4);
    std::memcpy(&nominal, base + player.camera + 0x44, 4);
    if (previous == scale || !std::isfinite(previous) || previous <= 0 ||
        !std::isfinite(nominal) || nominal <= 0 || nominal >= 180 ||
        ctx.esp < 256 || !Span(base, uint64_t(ctx.esp) - 256, 256)) return;

    // Preserve the authored nominal angle/zoom. Only the original view-window
    // scale changes, and the original setter updates projection and dirty state.
    std::memcpy(base + player.camera + 0x48, &scale, 4);
    X86Context call = ctx;
    call.ecx = player.camera;
    call.esp -= 12;
    std::array<uint8_t, 12> old_args;
    std::memcpy(old_args.data(), base + call.esp, old_args.size());
    struct Restore {
        uint8_t* target; const std::array<uint8_t, 12>& saved;
        ~Restore() {std::memcpy(target, saved.data(), saved.size());}
    } restore{base + call.esp, old_args};
    const uint32_t args[]{0x21606D, Read(base, player.camera + 0x44), 1};
    std::memcpy(base + call.esp, args, sizeof(args));
    sub_00216B7C(call, base);
}
