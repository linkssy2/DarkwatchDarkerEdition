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
struct WeaponView {uint32_t frame = 0, renderer = 0, camera = 0, raster = 0; float scale = 1;};
thread_local WeaponView g_weapon_view;
struct PowerView {uint32_t frame = 0, node = 0, raster = 0; float scale = 1;};
thread_local PowerView g_power_view;

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
bool CameraValid(const uint8_t* base, uint32_t camera, uint32_t raster) {
    return Span(base, camera, 0x68) && Read(base, camera) == 0x43F97C &&
        Read(base, camera + 0x34) == raster && Span(base, raster, 0x78);
}
bool ScaleValid(const uint8_t* base, uint32_t camera, float& previous) {
    float nominal;
    std::memcpy(&previous, base + camera + 0x48, 4);
    std::memcpy(&nominal, base + camera + 0x44, 4);
    return std::isfinite(previous) && previous > 0 &&
        std::isfinite(nominal) && nominal > 0 && nominal < 180;
}
void SetScale(const X86Context& ctx, uint8_t* base, uint32_t camera, float scale, uint32_t resume) {
    std::memcpy(base + camera + 0x48, &scale, 4);
    X86Context call = ctx;
    call.ecx = camera;
    call.esp -= 12;
    std::array<uint8_t, 256> old_stack;
    std::memcpy(old_stack.data(), base + ctx.esp - old_stack.size(), old_stack.size());
    struct Restore {
        uint8_t* target; const std::array<uint8_t, 256>& saved;
        ~Restore() {std::memcpy(target, saved.data(), saved.size());}
    } restore{base + ctx.esp - old_stack.size(), old_stack};
    const uint32_t args[]{resume, Read(base, camera + 0x44), 1};
    std::memcpy(base + call.esp, args, sizeof(args));
    sub_00216B7C(call, base);
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
    SetScale(ctx, base, player.camera, scale, 0x21606D);
}

void DarkwatchBeginWeaponView(X86Context& ctx, uint8_t* base) {
    // DEDD0 draws the registered first-person actor through message DB, between
    // its original camera BeginUpdate/EndUpdate. The world camera is only borrowed.
    if (g_weapon_view.frame) return;
    PlayerCamera player;
    {std::lock_guard lock(g_camera_lock); player = g_player_camera;}
    if (!player.owner || ctx.edi != player.camera || ctx.ecx != player.camera ||
        !Span(base, player.owner, 0x14) || Read(base, player.owner + 0xC) != player.camera ||
        !CameraValid(base, player.camera, player.raster) ||
        Read(base, player.camera + 0x58) || Read(base, player.camera + 0x5C) ||
        Read(base, player.camera + 0x60) != 0x3F800000 || Read(base, player.camera + 0x64) != 0x3F800000 ||
        !Span(base, ctx.esi, 0x20) || Read(base, ctx.esi) != 0x428338 ||
        !Read(base, ctx.esi + 4) || !Span(base, ctx.ebp, 12) ||
        Read(base, ctx.ebp + 8) != player.camera ||
        ctx.esp < 256 || !Span(base, uint64_t(ctx.esp) - 256, 256)) return;
    const uint32_t percent = darkwatch::view::Snapshot().viewmodel_fov_percent;
    if (percent < 50 || percent > 150) return;
    float previous;
    if (!ScaleValid(base, player.camera, previous)) return;
    const float scale = player.aspect_scale * (float(percent) / 100.0f);
    if (previous == scale) return;
    g_weapon_view = {ctx.ebp, ctx.esi, player.camera, player.raster, previous};
    SetScale(ctx, base, player.camera, scale, 0xDEDE6);
}

void DarkwatchEndWeaponView(X86Context& ctx, uint8_t* base) {
    // Match the invocation as well as the camera: a nested draw must not restore
    // the outer draw early. Restore the prior world scale even if settings change.
    const WeaponView saved = g_weapon_view;
    if (!saved.frame || ctx.ebp != saved.frame || ctx.esi != saved.renderer ||
        ctx.edi != saved.camera) return;
    g_weapon_view = {};
    float previous;
    if (!CameraValid(base, saved.camera, saved.raster) ||
        !ScaleValid(base, saved.camera, previous) || ctx.esp < 256 ||
        !Span(base, uint64_t(ctx.esp) - 256, 256)) return;
    SetScale(ctx, base, saved.camera, saved.scale, 0xDEE24);
}

void DarkwatchBeginPowerView(X86Context& ctx, uint8_t* base) {
    // B851D binds this authored screen effect to its player's camera. Its first
    // emitter is a fixed 2.1 x 1.1 rectangle; world FOV must not shrink it.
    // +50 is the original CRC32 of the resolved resource path, not the body aura.
    if (g_power_view.frame || !Span(base, ctx.ecx, 0x70) ||
        Read(base, ctx.ecx + 0x50) != 0x9EA613DE || !base[ctx.ecx + 0x62] ||
        Read(base, ctx.ecx + 0x54) != 1 || !Span(base, ctx.ebp, 12) ||
        !Span(base, ctx.esi, 4) || Read(base, ctx.esi) != ctx.ecx) return;
    PlayerCamera player;
    {std::lock_guard lock(g_camera_lock); player = g_player_camera;}
    float scale;
    if (!player.owner || Read(base, ctx.ebp + 8) != player.camera ||
        !Span(base, player.owner, 0x14) || Read(base, player.owner + 0xC) != player.camera ||
        !CameraValid(base, player.camera, player.raster) ||
        Read(base, ctx.ecx + 0x68) != player.raster ||
        !ScaleValid(base, player.camera, scale) ||
        !std::isfinite(player.aspect_scale) || player.aspect_scale <= 0) return;
    const float factor = scale / player.aspect_scale;
    if (!std::isfinite(factor) || factor < 0.5f || factor > 2.0f || factor == 1) return;
    g_power_view = {ctx.ebp, ctx.esi, player.raster, factor};
}

void DarkwatchEndPowerView(X86Context& ctx, uint8_t*) {
    if (g_power_view.frame == ctx.ebp && g_power_view.node == ctx.esi) g_power_view = {};
}

void DarkwatchPowerViewProjection(X86Context& ctx, uint8_t* base) {
    // 1CD874 has copied the active RW camera's reciprocal view windows into its
    // local particle projection. Change only this draw, leaving zoom, the world,
    // first-person weapons and other particle effects on their original paths.
    if (!g_power_view.frame || ctx.esi != g_power_view.raster ||
        !Span(base, ctx.ebp, 0x14) || base[ctx.ebp + 0x10] ||
        !Span(base, ctx.esp, 0x78)) return;
    float x, y;
    std::memcpy(&x, base + ctx.esp + 0x60, 4);
    std::memcpy(&y, base + ctx.esp + 0x74, 4);
    if (!std::isfinite(x) || !std::isfinite(y) || x <= 0 || y <= 0) return;
    x *= g_power_view.scale;
    y *= g_power_view.scale;
    if (!std::isfinite(x) || !std::isfinite(y)) return;
    std::memcpy(base + ctx.esp + 0x60, &x, 4);
    std::memcpy(base + ctx.esp + 0x74, &y, 4);
}
