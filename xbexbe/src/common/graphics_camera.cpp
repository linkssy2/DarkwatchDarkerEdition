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
struct Configuration {uint32_t address; std::array<uint32_t, 7> words;};
// FA277 selects these original layouts by active player count and co-op mode.
// The final word is the viewport/player index; the two split layouts have
// different authored FOV scales, which remain unchanged at 100%.
constexpr std::array<Configuration, 5> kConfigurations{{
    {0x491668, {0x3F800000, 0x3FAAAAAB, 0, 0, 0x3F800000, 0x3F800000, 0}},
    {0x4915F8, {0x3FB33333, 0x402AAAAB, 0, 0, 0x3F800000, 0x3EFEB852, 0}},
    {0x491614, {0x3FB33333, 0x402AAAAB, 0, 0x3F00A3D7, 0x3F800000, 0x3EFEB852, 1}},
    {0x4916D8, {0x40000000, 0x402AAAAB, 0, 0, 0x3F800000, 0x3EFEB852, 0}},
    {0x4916F4, {0x40000000, 0x402AAAAB, 0, 0x3F00A3D7, 0x3F800000, 0x3EFEB852, 1}},
}};
struct PlayerCamera {
    uint8_t* base = nullptr;
    uint32_t owner = 0, camera = 0, raster = 0, player = 0;
    float aspect_scale = 1;
    std::array<uint32_t, 4> viewport{};
};
std::mutex g_camera_lock;
std::array<PlayerCamera, 2> g_player_cameras;
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
bool PlayerValid(const uint8_t* base, const PlayerCamera& player) {
    return base == player.base && player.owner && Span(base, player.owner, 0x14) &&
        Read(base, player.owner + 0xC) == player.camera &&
        CameraValid(base, player.camera, player.raster) &&
        !std::memcmp(base + player.camera + 0x58, player.viewport.data(), sizeof(player.viewport));
}
PlayerCamera FindPlayer(uint32_t address, bool owner) {
    std::lock_guard lock(g_camera_lock);
    for (const auto& player : g_player_cameras)
        if (address && address == (owner ? player.owner : player.camera)) return player;
    return {};
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
    const Configuration* configuration = nullptr;
    for (const auto& candidate : kConfigurations)
        if (ctx.esi == candidate.address) {configuration = &candidate; break;}
    if (!configuration || !Span(base, ctx.esi, sizeof(configuration->words)) ||
        std::memcmp(base + ctx.esi, configuration->words.data(), sizeof(configuration->words)) ||
        !Span(base, ctx.esp, 8) || Read(base, ctx.esp) != configuration->words[1] ||
        Read(base, ctx.esp + 4) != configuration->words[0] || !Span(base, ctx.edi, 0x14) ||
        Read(base, ctx.edi + 0xC) != ctx.ecx || !Span(base, ctx.ecx, 0x68) ||
        Read(base, ctx.ecx) != 0x0043F97C ||
        std::memcmp(base + ctx.ecx + 0x58, configuration->words.data() + 2, 16)) return;

    const bool full = ctx.esi == 0x491668, wide = full && app::Widescreen();
    float aspect, aspect_scale;
    std::memcpy(&aspect, base + ctx.esi + 4, 4);
    std::memcpy(&aspect_scale, base + ctx.esi, 4);
    if (wide) {aspect = 16.0f / 9.0f; aspect_scale = aspect / (4.0f / 3.0f);}
    const uint32_t index = configuration->words[6];
    const float scale = aspect_scale * (float(darkwatch::view::Snapshot(index).fov_percent) / 100.0f);
    if (wide || scale != aspect_scale) {
        // Original FOV updates use tan(FOV/2)*scale, then divide by aspect for Y.
        // Widescreen adjusts both; the preference changes scale only and retains zoom.
        std::memcpy(base + ctx.esp, &aspect, sizeof(aspect));
        std::memcpy(base + ctx.esp + 4, &scale, sizeof(scale));
    }
    {
        std::lock_guard lock(g_camera_lock);
        if (full) g_player_cameras = {};
        // A recycled component/camera cannot keep another player's old binding.
        for (auto& player : g_player_cameras)
            if (player.owner == ctx.edi || player.camera == ctx.ecx) player = {};
        auto& player = g_player_cameras[index];
        player = {base, ctx.edi, ctx.ecx, Read(base, ctx.ecx + 0x34), index, aspect_scale, {}};
        std::memcpy(player.viewport.data(), configuration->words.data() + 2, 16);
    }
    LOG_FIRST(4, "Player %u camera %08X: %s projection (authored zoom retained)",
              index + 1, ctx.ecx, full ? (wide ? "16:9" : "4:3") : "split");
}

void DarkwatchUpdatePlayerView(X86Context& ctx, uint8_t* base) {
    const PlayerCamera player = FindPlayer(ctx.esi, true);
    // At 21606D the original active-camera update has finished; ESI is its owning
    // component. Never apply this preference to a separate weapon/render camera.
    if (!PlayerValid(base, player)) return;
    const float scale = player.aspect_scale * (float(darkwatch::view::Snapshot(player.player).fov_percent) / 100.0f);
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
    const PlayerCamera player = FindPlayer(ctx.edi, false);
    if (!PlayerValid(base, player) || ctx.ecx != player.camera ||
        !Span(base, ctx.esi, 0x20) || Read(base, ctx.esi) != 0x428338 ||
        !Read(base, ctx.esi + 4) || !Span(base, ctx.ebp, 12) ||
        Read(base, ctx.ebp + 8) != player.camera ||
        ctx.esp < 256 || !Span(base, uint64_t(ctx.esp) - 256, 256)) return;
    const uint32_t percent = darkwatch::view::Snapshot(player.player).viewmodel_fov_percent;
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
    const PlayerCamera player = FindPlayer(Read(base, ctx.ebp + 8), false);
    float scale;
    if (!PlayerValid(base, player) ||
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
