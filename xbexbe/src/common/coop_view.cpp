#include "common/coop_view.h"
#include <array>
#include <atomic>
#include <cstring>
#include <initializer_list>
#include <utility>
#include "common/coop.h"
#include "app/app.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

namespace {
// Original XBE layout table: scale, aspect, x, y, w, h, view index. Two-player entries
// exist in the main table (index 4, 5) and the alternate table FA11C selects (0, 1).
using Entry = std::array<uint32_t, 7>;
struct Split {uint32_t address; Entry original;};
constexpr uint32_t kTop = 0x3EFEB852, kBottom = 0x3F00A3D7;  // 0.498f height, 0.502f top
constexpr std::array<Split, 4> kSplits{{
    {0x004916D8, {0x40000000, 0x402AAAAB, 0, 0, 0x3F800000, kTop, 0}},
    {0x004916F4, {0x40000000, 0x402AAAAB, 0, kBottom, 0x3F800000, kTop, 1}},
    {0x004915F8, {0x3FB33333, 0x402AAAAB, 0, 0, 0x3F800000, kTop, 0}},
    {0x00491614, {0x3FB33333, 0x402AAAAB, 0, kBottom, 0x3F800000, kTop, 1}},
}};
constexpr uint32_t kSinglePlayer = 0x00491668;
// The single-player entry's scale, 4:3 aspect and full rectangle.
constexpr Entry Fullscreen(uint32_t player) {return {0x3F800000, 0x3FAAAAAB, 0, 0, 0x3F800000, 0x3F800000, player};}

bool Committed(uint32_t address, uint32_t size) {
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < uint64_t(address) + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
bool Matches(const uint8_t* base, uint32_t address, const Entry& entry) {
    return Committed(address, sizeof(Entry)) && !std::memcmp(base + address, entry.data(), sizeof(Entry));
}
std::atomic<bool> g_fullscreen{false};

// RenderWare raster calls the cameras already use (216A09): cdecl, result in eax.
extern "C" void sub_001222C0(X86Context& ctx, uint8_t* base);  // RwRasterCreate(width, height, depth, type)
extern "C" void sub_00122260(X86Context& ctx, uint8_t* base);  // RwRasterSubRaster(sub, parent, rect)
extern "C" void sub_00122160(X86Context& ctx, uint8_t* base);  // RwRasterDestroy(raster)
constexpr uint32_t kCameraVtable = 0x0043F97C;
// Camera begin-update (1289C0) renders a type 2 (camera) raster into the surface its parent's
// driver extension holds, which for the display is the back buffer; a type 5 (camera
// texture) raster renders into its own texture. The guest's view needs the latter.
constexpr uint32_t kRasterCameraTexture = 5, kRasterZBuffer = 1;
constexpr uint32_t kRasterExtensionOffset = 0x004DF098;  // RW Xbox driver's per-raster data

uint32_t Read(const uint8_t* base, uint32_t address) {uint32_t v; std::memcpy(&v, base + address, 4); return v;}
void Write(uint8_t* base, uint32_t address, uint32_t value) {std::memcpy(base + address, &value, 4);}

// Calls a guest function on scratch stack below the hook's esp, which the guest
// treats as free; the hook's own registers and stack are untouched.
uint32_t Call(const X86Context& ctx, uint8_t* base, void (*fn)(X86Context&, uint8_t*),
              std::initializer_list<uint32_t> args, uint32_t resume) {
    X86Context call = ctx;
    call.esp = ctx.esp - 0x100 - 4 * uint32_t(args.size() + 1);
    Write(base, call.esp, resume);
    uint32_t slot = call.esp + 4;
    for (uint32_t arg : args) {Write(base, slot, arg); slot += 4;}
    fn(call, base);
    return call.eax;
}

// The guest's full-size targets. They live for the process, so cameras of any level
// can take sub-rasters of them and the original destructor frees only those.
struct Target {uint32_t frame = 0, depth = 0, width = 0, height = 0;};
Target g_target;
std::atomic<uint32_t> g_guest_camera{0};
thread_local uint32_t t_hud_player_camera = 0;

// The co-op profile page numbers players (and so views) in the order they confirm. View 1
// is redirected at creation; F7 on the host swaps the views when the guest confirmed first.
// Game thread only; reset when view 0 of a level is laid out.
struct Level {
    uint32_t view[2]{}, hud_player[4]{}, hud[4]{};
    bool world_tried = false, hud_tried[4]{};
    int32_t guest_view = -1;  // -1 until a bound actor reveals a port
};
Level g_level;
bool GuestView(uint32_t player) {return g_level.guest_view >= 0 ? int32_t(player) == g_level.guest_view : player == 1;}

bool Raster(uint32_t raster) {return raster && Committed(raster, 0x24);}
bool Camera(const uint8_t* base, uint32_t camera) {
    return camera && Committed(camera, 0x68) && Read(base, camera) == kCameraVtable &&
           Raster(Read(base, camera + 0x2C)) && Raster(Read(base, camera + 0x30)) &&
           Read(base, camera + 0x34) && Committed(Read(base, camera + 0x34), 0x68);
}

// Replaces a camera's frame/Z sub-rasters of the shared buffers with sub-rasters of
// the guest's targets. On any failure the camera keeps its original rasters.
bool Redirect(const X86Context& ctx, uint8_t* base, uint32_t camera, uint32_t resume) {
    if (!Camera(base, camera)) return false;
    const uint32_t old_frame = Read(base, camera + 0x2C), old_depth = Read(base, camera + 0x30);
    const uint32_t frame_parent = Read(base, old_frame), depth_parent = Read(base, old_depth);
    if (!Raster(frame_parent) || !Raster(depth_parent)) return false;
    const uint32_t width = Read(base, frame_parent + 0x0C), height = Read(base, frame_parent + 0x10);
    const uint32_t frame_bits = Read(base, frame_parent + 0x14), depth_bits = Read(base, depth_parent + 0x14);
    if (!width || !height || width > 4096 || height > 4096) return false;
    if (g_target.width != width || g_target.height != height) {
        // A different frame buffer size retires the old pair; it is small and stays allocated.
        const uint32_t frame = Call(ctx, base, sub_001222C0, {width, height, frame_bits, kRasterCameraTexture}, resume);
        const uint32_t depth = frame ? Call(ctx, base, sub_001222C0, {width, height, depth_bits, kRasterZBuffer}, resume) : 0;
        if (!frame || !depth) {
            if (frame) Call(ctx, base, sub_00122160, {frame}, resume);
            LOG_FIRST(2, "coop: guest target %ux%u could not be created", width, height);
            return false;
        }
        g_target = {frame, depth, width, height};
        // The first driver word is the D3D surface (display) or texture (camera texture).
        const uint32_t ext = Committed(kRasterExtensionOffset, 4) ? Read(base, kRasterExtensionOffset) : 0;
        LOGR("coop: guest target %ux%u frame %08X (D3D %08X) depth %08X; display frame %08X (D3D %08X)",
             width, height, frame, ext ? Read(base, frame + ext) : 0, depth, frame_parent,
             ext ? Read(base, frame_parent + ext) : 0);
    }
    const uint32_t rect = ctx.esp - 0x40;  // RwRect {x, y, w, h}, below the call frames
    for (uint32_t i = 0; i < 4; ++i) Write(base, rect + 4 * i, i < 2 ? 0 : i == 2 ? width : height);
    uint32_t frame = Call(ctx, base, sub_001222C0, {0, 0, frame_bits, kRasterCameraTexture}, resume);
    if (frame) frame = Call(ctx, base, sub_00122260, {frame, g_target.frame, rect}, resume);
    uint32_t depth = frame ? Call(ctx, base, sub_001222C0, {0, 0, depth_bits, kRasterZBuffer}, resume) : 0;
    if (depth) depth = Call(ctx, base, sub_00122260, {depth, g_target.depth, rect}, resume);
    if (!frame || !depth) {
        if (frame) Call(ctx, base, sub_00122160, {frame}, resume);
        LOG_FIRST(2, "coop: guest sub-rasters could not be created");
        return false;
    }
    const uint32_t rw_camera = Read(base, camera + 0x34);
    Write(base, camera + 0x2C, frame); Write(base, rw_camera + 0x60, frame);
    Write(base, camera + 0x30, depth); Write(base, rw_camera + 0x64, depth);
    Call(ctx, base, sub_00122160, {old_frame}, resume);
    Call(ctx, base, sub_00122160, {old_depth}, resume);
    return true;
}

// Exchanges two cameras' frame/Z rasters, including their RwCamera copies.
bool SwapRasters(uint8_t* base, uint32_t a, uint32_t b) {
    if (!Camera(base, a) || !Camera(base, b)) return false;
    for (uint32_t field : {0x2Cu, 0x30u}) {
        const uint32_t ra = Read(base, a + field), rb = Read(base, b + field);
        Write(base, a + field, rb); Write(base, b + field, ra);
    }
    for (uint32_t camera : {a, b}) {
        const uint32_t rw = Read(base, camera + 0x34);
        Write(base, rw + 0x60, Read(base, camera + 0x2C)); Write(base, rw + 0x64, Read(base, camera + 0x30));
    }
    return true;
}

// Redirects the guest's world camera, then every HUD camera drawn for it, once each.
void Apply(const X86Context& ctx, uint8_t* base, uint32_t resume) {
    if (g_level.guest_view < 0 || !g_level.view[g_level.guest_view]) return;
    const uint32_t camera = g_level.view[g_level.guest_view];
    if (!g_level.world_tried) {
        g_level.world_tried = true;
        if (Redirect(ctx, base, camera, resume)) {
            g_guest_camera = camera;
            LOGR("coop: guest camera %08X (view %d) draws off screen", camera, g_level.guest_view);
        }
    }
    if (g_guest_camera.load() != camera) return;
    for (uint32_t i = 0; i < 4; ++i) {
        if (!g_level.hud[i] || g_level.hud_player[i] != camera || g_level.hud_tried[i]) continue;
        g_level.hud_tried[i] = true;
        if (Redirect(ctx, base, g_level.hud[i], resume)) LOGR("coop: guest HUD camera %08X draws off screen", g_level.hud[i]);
    }
}
} // namespace

void DarkwatchCoopViewLayout(X86Context& ctx, uint8_t* base) {
    bool split = false;
    for (const auto& s : kSplits) split |= ctx.edi == s.address;
    if (!split) return;
    // Every entry must hold either its original or its full-screen bytes; anything else
    // means a different executable or another writer, so the layout stays untouched.
    for (const auto& s : kSplits)
        if (!Matches(base, s.address, s.original) && !Matches(base, s.address, Fullscreen(s.original[6]))) {
            LOG_FIRST(1, "coop: unexpected view layout at %08X; split screen kept", s.address);
            return;
        }
    if (ctx.edi == kSplits[0].address || ctx.edi == kSplits[2].address) {g_level = {}; g_guest_camera = 0;}  // view 0 starts a level
    const bool fullscreen = darkwatch::coop::GuestActive();
    for (const auto& s : kSplits) {
        const Entry entry = fullscreen ? Fullscreen(s.original[6]) : s.original;
        std::memcpy(base + s.address, entry.data(), sizeof(entry));
    }
    if (g_fullscreen.exchange(fullscreen) != fullscreen)
        LOGR("coop: two-player views %s", fullscreen ? "full screen for the network guest" : "split screen");
}

void DarkwatchCoopViewCreated(X86Context& ctx, uint8_t* base) {
    // F9B52 returned the view in eax; esi is still the layout entry, view+0C its camera.
    uint32_t player = 0;
    if (!ctx.eax || !darkwatch::coop::FullscreenLayout(base, ctx.esi, player) || player > 1 ||
        !Committed(ctx.eax, 0x14)) return;
    g_level.view[player] = Read(base, ctx.eax + 0x0C);
    if (player == 1) g_level.guest_view = 1;  // F7 on the host swaps it
    Apply(ctx, base, 0x000F9B57);
}

// Gives the other view the off-screen rasters, world and HUD cameras alike.
bool SwapViews(uint8_t* base) {
    const uint32_t redirected = g_guest_camera.load();
    const uint32_t other = redirected == g_level.view[0] ? g_level.view[1] : g_level.view[0];
    if (!redirected || !other || !SwapRasters(base, other, redirected)) return false;
    uint32_t old_hud = 0, new_hud = 0;
    for (uint32_t i = 0; i < 4; ++i) {
        if (g_level.hud_player[i] == redirected) old_hud = g_level.hud[i];
        if (g_level.hud_player[i] == other) new_hud = g_level.hud[i];
    }
    if (old_hud && new_hud) SwapRasters(base, new_hud, old_hud);
    g_guest_camera = other;
    g_level.guest_view = other == g_level.view[0] ? 0 : 1;
    return true;
}

void DarkwatchCoopViewFrame(X86Context&, uint8_t* base) {
    // 21606D runs on the game thread for each player camera every frame. The co-op
    // profile page numbers players in confirmation order, and the controller binding is
    // not yet found automatically, so F7 on the host swaps which view is off screen.
    static bool held = false;
    const bool focused = GetForegroundWindow() == static_cast<HWND>(app::Window());
    const bool down = focused && (GetAsyncKeyState(VK_F7) & 0x8000);
    const bool pressed = down && !held;
    held = down;
    if (!pressed || !g_fullscreen.load() || !g_guest_camera.load()) return;
    if (SwapViews(base)) LOGR("coop: F7 swapped views; view %d draws off screen", g_level.guest_view);
}

void DarkwatchCoopHudOwner(X86Context& ctx, uint8_t*) {
    t_hud_player_camera = ctx.eax;  // D8365 returned the HUD player's camera
}

void DarkwatchCoopHudCreated(X86Context& ctx, uint8_t* base) {
    // D83DC: eax is the new HUD camera (or 0) for the player D836A recorded.
    const uint32_t player = std::exchange(t_hud_player_camera, 0);
    if (!g_fullscreen.load() || !ctx.eax || !player) return;
    for (uint32_t i = 0; i < 4; ++i)
        if (!g_level.hud[i]) {g_level.hud[i] = ctx.eax; g_level.hud_player[i] = player; break;}
    Apply(ctx, base, 0x000D83DC);
}

namespace darkwatch::coop {
uint32_t GuestFrameRaster() {return g_guest_camera.load() ? g_target.frame : 0;}
bool CreatingGuestView(bool coop, uint32_t player) {return coop && GuestView(player);}

bool FullscreenLayout(const uint8_t* base, uint32_t entry, uint32_t& player) {
    if (entry == kSinglePlayer) {player = 0; return false;}
    for (const auto& s : kSplits)
        if (entry == s.address && Matches(base, entry, Fullscreen(s.original[6]))) {player = s.original[6]; return true;}
    return false;
}
} // namespace darkwatch::coop
