#include "app/app.h"
#include "core/input.h"
#include "common/graphics.h"
#include "common/graphics_view.h"
#include "common/controls.h"
#include "common/coop.h"
#include "common/coop_view.h"
#include "common/menu_cursor.h"
#include "common/native_menu.h"
#include "common/hd_ui.h"
#include "common/settings_skin.h"
#include "common/shader_preparation.h"

namespace {
void InitDirectMouse();
void LoadFrontendAssets() { darkwatch::InitializeMenuCursor(); darkwatch::skin::Finalize(); darkwatch::InitializeHdUi(); }
void DrawUi(double fps) { DarkwatchGraphicsUi(fps); DarkwatchMenuUi(fps); }
}

const app::GameInfo app::kGame = {
    .title = L"Darkwatch",
    .short_title = L"Darkwatch",
    .name = L"DarkwatchXBERecomp",
    .log = "darkwatch_xbe",
    .settings = "darkwatch_xbe_settings.toml",
    .splash = L"splash",
    .missing = L"Darkwatch's original default.xbe and game files were not found in assets.",
    .images = {{"default.xbe", "darkwatch_xbe"}},
    .load = [](const void* table) {darkwatch::ControlsLoad(table); darkwatch::view::Load(table); darkwatch::coop::Load(table);},
    .save = [](void* table) {darkwatch::ControlsSave(table); darkwatch::view::Save(table); darkwatch::coop::Save(table);},
    .init = [] {InitDirectMouse(); darkwatch::coop::Start();},
    .loaded = LoadFrontendAssets,
    .window = DarkwatchGraphicsWindow,
    .message = darkwatch::ControlsMessage,
    .ui = DrawUi,
    // A network guest becomes port 1 before menu gating sees the pad.
    .pad = [](int port, input::Pad& pad) {
        darkwatch::coop::Pad(port, pad);
        // Direct mouse aims the guest's player like the host's; without it the guest's mouse is a stick.
        if (port == darkwatch::coop::kGuestPort && !darkwatch::ControlsSnapshot().direct_mouse)
            darkwatch::coop::GuestMouseStick(pad);
        DarkwatchGraphicsPad(port, pad);
    },
    .rumble = darkwatch::coop::Rumble,
    .prepare = darkwatch::PrepareShaders,
};

#include <array>
#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
#include <mutex>
#include "core/diag.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"
#include "gpu/backend.h"
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

namespace {
void InitDirectMouse() {
    DarkwatchGraphicsInit();
    input::SetMouseToStick(!darkwatch::ControlsSnapshot().direct_mouse);
}

// Every derived address is checked before accessing guest memory.
template<class T> bool AimRead(const uint8_t* base, uint64_t address, T& value) {
    uint64_t end = address + sizeof(T);
    if (!base || !address || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    std::memcpy(&value, base + address, sizeof(T));
    return true;
}
template<class T> bool AimField(const uint8_t* base, uint32_t object, uint32_t offset, T& value) {
    return object && AimRead(base, uint64_t(object) + offset, value);
}

struct MouseTarget {
    uint32_t state = 0, owner = 0, vtable = 0, caller = 0, parent = 0;
    float dt = 0, lower = 0, upper = 0;
    uint8_t inversion = 0;
    bool local = false;
    unsigned port = 0;  // the controller port whose mouse aims this player
};

// The host's mouse aims port 0's player; a network co-op guest's mouse aims port 1's.
constexpr unsigned kMousePorts = 2;

// The port whose input-manager controller (manager+D4+port*10) is linked to `map`, the
// actor's +30; without a network guest only port 0 has a mouse.
bool MousePort(const uint8_t* base, uint32_t map, unsigned& port, uint32_t& manager) {
    if (!AimRead(base, 0x4AC174, manager)) return false;
    darkwatch::coop::Session::Mouse guest;
    const unsigned ports = darkwatch::coop::GuestMouse(guest) ? kMousePorts : 1;
    for (port = 0; port < ports; ++port) {
        uint32_t controller = 0, self = 0, reference = 0;
        if (AimField(base, manager, 0xD4 + port * 0x10, controller) && AimField(base, controller, 8, self) &&
            AimField(base, controller, 0x10, reference) && self == controller &&
            uint64_t(controller) + 0xC == reference && reference == map) return true;
    }
    return false;
}

input::MouseSnapshot PortMouse(unsigned port) {
    if (!port) return input::GetMouseSnapshot();
    input::MouseSnapshot s;
    darkwatch::coop::Session::Mouse guest;
    if (!darkwatch::coop::GuestMouse(guest)) return s;
    s.generation = guest.generation;
    s.active_epoch = guest.epoch;
    s.published_us = guest.published_ms * 1000;
    s.accumulated_x = guest.x;
    s.accumulated_y = guest.y;
    s.active = guest.active;
    return s;
}

bool AimComponent(const uint8_t* base, uint32_t actor, uint32_t vtable, uint32_t& result) {
    uint16_t count = 0;
    uint32_t list = 0;
    if (!AimField(base, actor, 0x60, count) || !count || count > 128 ||
        !AimField(base, actor, 0x64, list) || !list) return false;
    result = 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component = 0, type = 0, owner = 0;
        // Actor entries are {type descriptor, component}, eight bytes each (216560).
        if (!AimRead(base, uint64_t(list) + i * 8 + 4, component) ||
            !AimField(base, component, 0, type)) return false;
        if (type != vtable) continue;
        if (result || !AimField(base, component, 0xC, owner) || owner != actor) return false;
        result = component;
    }
    return result != 0;
}

bool ActiveHorseCamera(const uint8_t* base, uint32_t rider, uint32_t& camera) {
    uint32_t component = 0, stack = 0, list = 0, type = 0, linked_rider = 0, horse = 0;
    uint16_t count = 0;
    // Original CameraComponent's event CD pushes the mounted camera. Its manager
    // updates only the final stack entry (216040), not every retained camera.
    if (!AimComponent(base, rider, 0x416444, component) ||
        !AimField(base, component, 0x80, stack) || !AimField(base, stack, 4, count) ||
        !count || count > 64 || !AimField(base, stack, 8, list) || !list ||
        !AimRead(base, uint64_t(list) + uint64_t(count - 1) * 4, camera) ||
        !AimField(base, camera, 0, type) || type != 0x423B30 ||
        !AimField(base, camera, 0x74, linked_rider) || linked_rider != rider ||
        !AimField(base, camera, 0x64, horse) || !AimComponent(base, horse, 0x41DA58, component)) return false;
    uint32_t linked_camera = 0;
    // HorseComponent creates this camera at 76BCC and releases it at 76C47.
    return AimField(base, component, 0xE8, linked_camera) && linked_camera == camera &&
           AimField(base, component, 0x3C, linked_rider) && linked_rider == rider;
}

const char* ReadMouseTarget(const X86Context& ctx, const uint8_t* base, unsigned axis, MouseTarget& t) {
    t.state = axis ? ctx.esi : ctx.ebx;
    uint32_t map = 0, manager = 0;
    if (!AimField(base, t.state, 0, t.vtable) || !AimField(base, t.state, 0x40, t.owner) ||
        !AimField(base, t.owner, 0x30, map) || !AimRead(base, 0x4AC174, manager)) return "unreadable-owner";
    if (!MousePort(base, map, t.port, manager)) return "nonlocal";
    t.local = true;
    uint32_t rider = 0, mounted_camera = 0, camera_component = 0, camera_stack = 0;
    // Network co-op matches each port's player to its view: the rider's CameraComponent +80
    // points at that player's view object (F9B1D's).
    if (AimField(base, t.owner, 0xC, rider) && AimComponent(base, rider, 0x416444, camera_component) &&
        AimField(base, camera_component, 0x80, camera_stack)) darkwatch::coop::NoteCameraStack(t.port, camera_stack);
    if (rider && ActiveHorseCamera(base, rider, mounted_camera))
        return "mounted-camera";
    if (!AimField(base, ctx.ebp, 4, t.caller) || !AimField(base, ctx.ebp, 0, t.parent)) return "stack";
    // StateVampireJump delegates to StateJump's look update (A9531 -> A1AC5).
    bool jump = t.vtable == 0x420E50 || t.vtable == 0x4223A8;
    bool route = (t.vtable == 0x421FE0 && t.caller == (axis ? 0xA84B0u : 0xA84A1u)) ||
                 (jump && t.caller == (axis ? 0xA1B37u : 0xA1B28u));
    if (!route) return "unobserved-route";
    uint8_t enabled = 0, inhibited = 0;
    if (!AimField(base, manager, 0x120, enabled) || !AimField(base, manager, 0x121 + t.port, inhibited) ||
        !enabled || inhibited) return "controller-disabled";
    uint32_t gate_reference = 0, gate_object = 0, gate = 0;
    // Original 83903 dereferences the reference before reading the object's gate.
    if (!AimField(base, t.owner, 0xF4, gate_reference) || !AimField(base, gate_reference, 0, gate_object) ||
        !AimField(base, gate_object, 0xA4, gate) || !gate)
        return "original-gate";
    if (jump) {
        // This caller obtains the input owner from +7C and skips look on 211B78 != 0.
        uint32_t caller_owner = 0, mode_object = 0;
        uint8_t mode = 0;
        if (!AimField(base, t.state, 0x7C, caller_owner) || caller_owner != t.owner ||
            !AimField(base, t.owner, 0x20, mode_object) || !AimField(base, mode_object, 0xC, mode) || mode)
            return "original-caller-gate";
    }
    // A2A4A overwrites the pitch argument; the verified parent retains the original dt.
    if (!AimField(base, axis ? t.parent : ctx.ebp, 8, t.dt) || !std::isfinite(t.dt) ||
        t.dt <= 0 || t.dt > 0.25f) return "dt";
    if (!AimField(base, t.owner, 0x139, t.inversion) || !AimField(base, t.owner, 0x5C, t.lower) ||
        !AimField(base, t.owner, 0x60, t.upper) || !std::isfinite(t.lower) ||
        !std::isfinite(t.upper) || t.lower > t.upper) return "bounds";
    return nullptr;
}

struct MousePair {
    input::MouseSnapshot sample;
    uint64_t consumed_x = 0, consumed_y = 0;
    int64_t dx = 0, dy = 0;
    uint32_t owner = 0, state = 0, parent = 0;
    float dt = 0;
    unsigned used = 3;
    bool pitch_active = false;
    uint32_t millidegrees = 50;
};
MousePair g_mouse_pairs[kMousePorts];
MousePair g_horse_mouse_pairs[kMousePorts];
unsigned g_horse_mouse_logs = 0;
uint64_t g_horse_mouse_log_us = 0;
std::mutex g_mouse_aim_lock;
unsigned g_mouse_logs = 0;
uint64_t g_mouse_log_us = 0;

void TraceMouse(const input::MouseSnapshot& s, const MouseTarget& t, unsigned axis, const char* reason) {
    if (!diag::Perf() || g_mouse_logs >= 256) return;
    if (g_mouse_logs >= 32 && s.published_us >= g_mouse_log_us && s.published_us - g_mouse_log_us < 2000000) return;
    g_mouse_log_us = s.published_us; ++g_mouse_logs;
    LOGR("direct mouse: axis=%s generation=%llu pair_generation=%llu epoch=%llu us=%llu counts=%d/%d pair_counts=%lld/%lld mask=%u active=%u owner=%08X state=%08X vtable=%08X caller=%08X dt=%g reason=%s",
         axis ? "pitch" : "yaw", static_cast<unsigned long long>(s.generation),
         static_cast<unsigned long long>(g_mouse_pairs[t.port].sample.generation),
         static_cast<unsigned long long>(s.active_epoch), static_cast<unsigned long long>(s.published_us),
         s.dx, s.dy, static_cast<long long>(g_mouse_pairs[t.port].dx), static_cast<long long>(g_mouse_pairs[t.port].dy),
         g_mouse_pairs[t.port].used, unsigned(s.active),
         t.owner, t.state, t.vtable, t.caller, double(t.dt), reason);
}

void DiscardMouse(const input::MouseSnapshot& s, const MouseTarget& t) {
    auto& p = g_mouse_pairs[t.port];
    p = {};
    p.sample = s;
    p.consumed_x = s.accumulated_x; p.consumed_y = s.accumulated_y;
    p.owner = t.owner; p.state = t.state; p.parent = t.parent;
    p.dt = t.dt;
}

double MouseDegrees(const MousePair& p, const MouseTarget& t, unsigned axis) {
    double degrees = double(axis ? p.dy : p.dx) * double(p.millidegrees) / 1000.0;
    return !axis || t.inversion ? -degrees : degrees;
}

// The target decides whose mouse applies, so it is read before the snapshot `s`.
bool MouseEligible(const X86Context& ctx, uint8_t* base, unsigned axis,
                   input::MouseSnapshot& s, MouseTarget& t) {
    const char* reason = ReadMouseTarget(ctx, base, axis, t);
    s = PortMouse(t.port);
    if (reason) {
        // Other actors invoke these same routines. They must not consume local motion.
        if (t.local) DiscardMouse(s, t);
        TraceMouse(s, t, axis, reason); return false;
    }
    if (!s.active) {
        DiscardMouse(s, t); TraceMouse(s, t, axis, "inactive"); return false;
    }
    const auto& p = g_mouse_pairs[t.port];
    bool changed = p.owner != t.owner || p.state != t.state || p.sample.active_epoch != s.active_epoch;
    bool gap = s.published_us < p.sample.published_us || s.published_us - p.sample.published_us > 250000;
    if (changed || gap) {
        DiscardMouse(s, t); TraceMouse(s, t, axis, changed ? "transition-reset" : "gap-reset"); return false;
    }
    return true;
}

bool MousePitchActive(X86Context& ctx, uint8_t* base, bool direct_mouse) {
    if (!direct_mouse) return false;
    input::MouseSnapshot s;
    std::lock_guard lock(g_mouse_aim_lock);
    MouseTarget t;
    if (!MouseEligible(ctx, base, 1, s, t)) return false;
    float original_rate = 0;
    if (ctx.top >= 8 || !AimField(base, ctx.ebp, 0xC, original_rate) || !std::isfinite(original_rate)) {
        TraceMouse(s, t, 1, "arithmetic-state"); return false;
    }
    auto& p = g_mouse_pairs[t.port];
    double rate = double(original_rate) + MouseDegrees(p, t, 1) / double(t.dt);
    bool active = p.parent == t.parent && p.dt == t.dt && (p.used & 1) && !(p.used & 2) && p.dy != 0 &&
                  std::isfinite(rate) && std::abs(rate) <= double(std::numeric_limits<float>::max());
    if (active) p.pitch_active = true;
    TraceMouse(s, t, 1, active ? "manual-center-branch" : "no-pending-y");
    return active;
}

void ApplyMouseAim(X86Context& ctx, uint8_t* base, unsigned axis) {
    const auto controls = darkwatch::ControlsSnapshot();
    if (!controls.direct_mouse) return;
    input::MouseSnapshot s;
    std::lock_guard lock(g_mouse_aim_lock);
    MouseTarget t;
    if (!MouseEligible(ctx, base, axis, s, t)) return;
    g_horse_mouse_pairs[t.port] = {}; // Returning to on-foot look cannot replay mounted motion.
    auto& p = g_mouse_pairs[t.port];
    if (!axis && p.sample.generation != s.generation) {
        p.sample = s;
        // A consumption interval is bounded to 250ms. Modulo subtraction also
        // handles negative counts and counter wrap without signed overflow.
        p.dx = std::bit_cast<int64_t>(s.accumulated_x - p.consumed_x);
        p.dy = std::bit_cast<int64_t>(s.accumulated_y - p.consumed_y);
        p.parent = t.parent; p.dt = t.dt; p.used = 0; p.pitch_active = false;
        p.millidegrees = controls.mouse_millidegrees;
    }
    unsigned bit = 1u << axis;
    if ((p.used & bit) || p.parent != t.parent || p.dt != t.dt || (axis && !(p.used & 1))) {
        TraceMouse(s, t, axis, "already-used-or-unpaired"); return;
    }
    p.used |= bit;
    if (axis) p.consumed_y = p.sample.accumulated_y;
    else p.consumed_x = p.sample.accumulated_x;
    double degrees = MouseDegrees(p, t, axis);
    if (axis && degrees && !p.pitch_active) { TraceMouse(s, t, axis, "missing-center-branch"); return; }
    if (!degrees) { TraceMouse(s, t, axis, "zero-counts"); return; }
    float pitch_rate = 0;
    if (ctx.top >= 8 || (axis && !AimField(base, ctx.ebp, 0xC, pitch_rate))) {
        TraceMouse(s, t, axis, "arithmetic-state"); return;
    }
    double angle = ctx.st[ctx.top] + degrees;
    double rate = (axis ? double(pitch_rate) : ctx.st[(ctx.top + 1) & 7]) + degrees / double(t.dt);
    if (!std::isfinite(angle) || !std::isfinite(rate) || std::abs(rate) > double(std::numeric_limits<float>::max())) {
        TraceMouse(s, t, axis, "nonfinite-result"); return;
    }
    if (!axis) {
        angle = std::fmod(angle, 360.0);
        if (angle > 180.0) angle -= 360.0;
        if (angle < -180.0) angle += 360.0;
        ctx.st[(ctx.top + 1) & 7] = rate;
    } else {
        // The checked read above validates the exact four-byte rate slot before writing.
        pitch_rate = float(rate);
        std::memcpy(base + uint64_t(ctx.ebp) + 0xC, &pitch_rate, sizeof(pitch_rate));
    }
    ctx.st[ctx.top] = angle;
    TraceMouse(s, t, axis, "applied");
}

const char* ReadHorseMouseTarget(const X86Context& ctx, const uint8_t* base, MouseTarget& t) {
    t.state = ctx.ebx;
    uint32_t map = 0, manager = 0, active_camera = 0;
    if (!AimField(base, t.state, 0, t.vtable) || t.vtable != 0x423B30 ||
        !AimField(base, ctx.ebp, 4, t.caller) || t.caller != 0xBE55F ||
        !AimField(base, ctx.ebp, 0, t.parent) ||
        !AimField(base, t.state, 0x74, t.owner) || !AimField(base, t.state, 0xF0, map) ||
        !AimRead(base, 0x4AC174, manager)) return "route";
    if (!MousePort(base, map, t.port, manager)) return "nonlocal";
    t.local = true;
    uint8_t enabled = 0, inhibited = 0;
    if (!AimField(base, manager, 0x120, enabled) || !AimField(base, manager, 0x121 + t.port, inhibited) ||
        !enabled || inhibited) return "controller-disabled";
    if (!ActiveHorseCamera(base, t.owner, active_camera) || active_camera != t.state) return "attachment";
    if (!AimField(base, ctx.ebp, 8, t.dt) || !std::isfinite(t.dt) || t.dt <= 0 || t.dt > .25f ||
        !AimField(base, t.state, 0x124, t.inversion) || t.inversion > 1 ||
        !AimField(base, t.state, 0x114, t.lower) || !AimField(base, t.state, 0x118, t.upper) ||
        !std::isfinite(t.lower) || !std::isfinite(t.upper) || t.lower > t.upper) return "arithmetic-state";
    return nullptr;
}

void ApplyHorseMouse(X86Context& ctx, uint8_t* base, unsigned axis) {
    const auto controls = darkwatch::ControlsSnapshot();
    std::lock_guard lock(g_mouse_aim_lock);
    MouseTarget t;
    const char* reason = ReadHorseMouseTarget(ctx, base, t);
    auto sample = PortMouse(t.port);
    auto& p = g_horse_mouse_pairs[t.port];
    auto trace = [&](const char* reason, double delta = 0, double result = 0) {
        if (!diag::Perf() || g_horse_mouse_logs >= 128 ||
            (g_horse_mouse_logs >= 4 && sample.published_us >= g_horse_mouse_log_us &&
             sample.published_us - g_horse_mouse_log_us < 2000000)) return;
        ++g_horse_mouse_logs; g_horse_mouse_log_us = sample.published_us;
        LOGR("horse mouse: axis=%s camera=%08X rider=%08X local=%u caller=%08X dt=%g generation=%llu counts=%lld/%lld added=%g result=%g units=%s reason=%s",
             axis ? "pitch" : "yaw", t.state, t.owner, unsigned(t.local), t.caller, double(t.dt),
             static_cast<unsigned long long>(p.sample.generation), static_cast<long long>(p.dx),
             static_cast<long long>(p.dy), delta, result, axis ? "degrees" : "radians", reason);
    };
    auto reset = [&] {
        p = {}; p.sample = sample; p.consumed_x = sample.accumulated_x; p.consumed_y = sample.accumulated_y;
        p.owner = t.owner; p.state = t.state; p.parent = t.parent; p.dt = t.dt;
    };
    if (reason) { if (t.local) reset(); trace(reason); return; }
    if (!controls.direct_mouse || !sample.active) { reset(); return; }
    g_mouse_pairs[t.port] = {}; // The mounted camera owns its rider's raw look while it is active.
    bool changed = p.owner != t.owner || p.state != t.state || p.sample.active_epoch != sample.active_epoch;
    bool gap = sample.published_us < p.sample.published_us || sample.published_us - p.sample.published_us > 250000;
    if (changed || gap) { reset(); trace(changed ? "transition-reset" : "gap-reset"); return; }
    if (!axis && p.sample.generation != sample.generation) {
        p.sample = sample;
        p.dx = std::bit_cast<int64_t>(sample.accumulated_x - p.consumed_x);
        p.dy = std::bit_cast<int64_t>(sample.accumulated_y - p.consumed_y);
        p.parent = t.parent; p.dt = t.dt; p.used = 0; p.millidegrees = controls.mouse_millidegrees;
    }
    unsigned bit = 1u << axis;
    if ((p.used & bit) || p.parent != t.parent || p.dt != t.dt || (axis && !(p.used & 1))) return;
    p.used |= bit;
    if (axis) p.consumed_y = p.sample.accumulated_y; else p.consumed_x = p.sample.accumulated_x;
    double degrees = MouseDegrees(p, t, axis);
    if (axis) degrees = -degrees; // Mounted pitch has the opposite sign from on-foot pitch.
    // BE19B stores yaw radians; BE1DE starts the original degree-based pitch clamp.
    constexpr double radians_per_degree = 0.017453292519943295;
    double delta = axis ? degrees : std::remainder(degrees, 360.0) * radians_per_degree;
    uint64_t slot = uint64_t(ctx.esp) + (axis ? 0xCu : 0u);
    float original = 0;
    if (!AimRead(base, slot, original) || !std::isfinite(original)) return;
    double combined = double(original) + delta;
    if (!std::isfinite(combined) || std::abs(combined) > double(std::numeric_limits<float>::max())) return;
    float result = float(combined);
    std::memcpy(base + slot, &result, sizeof(result));
    trace("applied", delta, result);
}

bool LocalAimControl(const X86Context& ctx, const uint8_t* base, unsigned axis) {
    // These are camera preferences, including when F1 releases PC input for a controller.
    MouseTarget target;
    return !ReadMouseTarget(ctx, base, axis, target);
}
struct AimTraceState {
    uint64_t calls = 0, probe_ms = 0, log_ms = 0;
    unsigned logs = 0;
    bool probed = false, seen = false;
    std::array<uint32_t, 19> key = {};
};
std::array<AimTraceState, 2> g_aim_trace;
std::mutex g_aim_trace_lock;
uint32_t g_aim_capture_owner = 0, g_aim_capture_calls = 0;
bool g_aim_capture_requested = false;

void TraceAim(const X86Context& ctx, uint8_t* base, unsigned axis, uint64_t now_ms, bool foreground) {
    if (!diag::Perf()) return;
    std::lock_guard<std::mutex> lock(g_aim_trace_lock);
    auto& trace = g_aim_trace[axis];
    ++trace.calls;
    bool probe_due = trace.logs < 512 && (!trace.probed || now_ms - trace.probe_ms >= 100);
    bool capture_pending = !axis && !g_aim_capture_requested && !diag::CaptureDir().empty();
    if (!probe_due && !capture_pending) return;
    if (probe_due) { trace.probed = true; trace.probe_ms = now_ms; }
    uint32_t caller = 0, parent = 0, dt = 0, dt_source = 0, valid = 0;
    bool stack_ok = AimField(base, ctx.ebp, 4, caller);
    stack_ok &= AimField(base, ctx.ebp, 0, parent);
    if (stack_ok) valid |= 1;
    if (!axis) {
        if (AimField(base, ctx.ebp, 8, dt)) dt_source = 1;
    } else if (caller == 0xA10A2 || caller == 0xA1B37 || caller == 0xA84B0) {
        // Pitch has replaced its dt stack argument with the upper pitch bound at A2A4A.
        if (AimField(base, parent, 8, dt)) dt_source = 2;
    }
    if (dt_source) valid |= 2;
    uint32_t state = axis ? ctx.esi : ctx.ebx, vtable = 0, owner = 0, state7c = 0;
    uint8_t autocenter = 0;
    bool state_ok = AimField(base, state, 0, vtable);
    state_ok &= AimField(base, state, 0x40, owner);
    state_ok &= AimField(base, state, 0x7C, state7c);
    state_ok &= AimField(base, state, 0x74, autocenter);
    if (state_ok) valid |= 4;
    uint32_t owner_vtable = 0, map = 0, yaw = 0, pitch = 0, yaw_rate = 0, pitch_rate = 0;
    uint32_t lower = 0, upper = 0, gate_reference = 0, gate_object = 0, mode_object = 0, gate = 0;
    uint8_t inversion = 0, mode = 0;
    bool owner_ok = AimField(base, owner, 0, owner_vtable);
    owner_ok &= AimField(base, owner, 0x30, map);
    owner_ok &= AimField(base, owner, 0x139, inversion);
    owner_ok &= AimField(base, owner, 0x144, pitch);
    owner_ok &= AimField(base, owner, 0x148, yaw);
    owner_ok &= AimField(base, owner, 0x1A0, yaw_rate);
    owner_ok &= AimField(base, owner, 0x1A4, pitch_rate);
    owner_ok &= AimField(base, owner, 0x5C, lower);
    owner_ok &= AimField(base, owner, 0x60, upper);
    if (owner_ok) valid |= 8;
    if (AimField(base, owner, 0xF4, gate_reference) && AimField(base, gate_reference, 0, gate_object) &&
        AimField(base, gate_object, 0xA4, gate)) valid |= 16;
    if (AimField(base, owner, 0x20, mode_object) && AimField(base, mode_object, 0xC, mode)) valid |= 32;
    uint32_t manager = 0, ports[4] = {}, links = 0, match = 0, inhibited = 0;
    uint8_t enabled = 0;
    bool manager_ok = AimRead(base, 0x4AC174, manager);
    manager_ok &= AimField(base, manager, 0x120, enabled);
    for (uint32_t port = 0; port < 4; ++port) {
        uint8_t block = 0;
        bool port_ok = AimField(base, manager, 0xD4 + port * 0x10, ports[port]);
        port_ok &= AimField(base, manager, 0x121 + port, block);
        manager_ok &= port_ok;
        if (block) inhibited |= 1u << port;
        uint32_t self = 0, reference = 0;
        bool linked = port_ok && AimField(base, ports[port], 8, self) &&
                      AimField(base, ports[port], 0x10, reference) && self == ports[port] &&
                      uint64_t(ports[port]) + 0xC == reference;
        if (linked) links |= 1u << port;
        if (owner_ok && linked && reference == map) match |= 1u << port;
    }
    if (manager_ok) valid |= 64;
    if (capture_pending) {
        float seconds = std::bit_cast<float>(dt);
        bool eligible = state_ok && owner_ok && manager_ok && dt_source && std::isfinite(seconds) &&
                        seconds > 0 && foreground && enabled && (match & 1) && !(inhibited & 1);
        if (!eligible || g_aim_capture_owner != owner) g_aim_capture_calls = 0;
        g_aim_capture_owner = eligible ? owner : 0;
        if (eligible && ++g_aim_capture_calls == 120) {
            g_aim_capture_requested = true;
            gpu::g_capture.store(true);
            LOGR("aim observation: requesting one capture after 120 consecutive positive-dt yaw calls matching enabled port0 owner=%08X; scene identity remains unverified", owner);
        }
    }
    if (!probe_due) return;
    uint32_t current_rate = 0;
    bool rate_ok = !axis || AimField(base, ctx.ebp, 0xC, current_rate);
    if (rate_ok && ctx.top < 8) valid |= 128;
    std::array<uint32_t, 19> key = {valid, caller, state, vtable, owner, owner_vtable, state7c, map, manager,
                                  links, match, enabled, inhibited, inversion, autocenter, gate, mode,
                                  uint32_t(foreground), ctx.thread_handle};
    bool changed = !trace.seen || key != trace.key;
    if (trace.seen && (now_ms - trace.log_ms < 250 || (!changed && now_ms - trace.log_ms < 2000))) return;
    trace.seen = true;
    trace.key = key;
    trace.log_ms = now_ms;
    ++trace.logs;
    double integrated = ctx.top < 8 ? ctx.st[ctx.top] : std::numeric_limits<double>::quiet_NaN();
    double rate = axis ? double(std::bit_cast<float>(current_rate)) :
                         ctx.top < 8 ? ctx.st[(ctx.top + 1) & 7] : std::numeric_limits<double>::quiet_NaN();
    LOGR("aim observation: axis=%s calls=%llu sample=%u ms=%llu thread=%08X ret=%08X valid=%02X state=%08X vtable=%08X owner=%08X owner_vtable=%08X state7C=%08X map=%08X manager=%08X ports=%08X/%08X/%08X/%08X links=%X match=%X enabled=%u inhibit=%X foreground=%u dt=%g dt_bits=%08X dt_source=%u top=%u integrated=%g rate=%g yaw=%g pitch=%g prior_rates=%g/%g bounds=%g/%g inversion=%u autocenter=%u gate=%08X mode=%u",
         axis ? "pitch" : "yaw", static_cast<unsigned long long>(trace.calls), trace.logs,
         static_cast<unsigned long long>(now_ms), ctx.thread_handle, caller, valid, state, vtable, owner,
         owner_vtable, state7c, map, manager, ports[0], ports[1], ports[2], ports[3], links, match, enabled, inhibited,
         unsigned(foreground), double(std::bit_cast<float>(dt)), dt, dt_source, ctx.top, integrated, rate,
         double(std::bit_cast<float>(yaw)), double(std::bit_cast<float>(pitch)),
         double(std::bit_cast<float>(yaw_rate)), double(std::bit_cast<float>(pitch_rate)),
         double(std::bit_cast<float>(lower)), double(std::bit_cast<float>(upper)), unsigned(inversion),
         unsigned(autocenter), gate, unsigned(mode));
}
void ObserveAim(const X86Context& ctx, uint8_t* base, unsigned axis) {
    if (!diag::Perf()) return;
    bool foreground = false;
#ifdef _WIN32
    auto window = static_cast<HWND>(app::Window());
    foreground = window && GetForegroundWindow() == window;
#endif
    uint64_t now = uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
    TraceAim(ctx, base, axis, now, foreground);
}
}  // namespace

void DarkwatchObserveYaw(X86Context& ctx, uint8_t* base) { ObserveAim(ctx, base, 0); ApplyMouseAim(ctx, base, 0); }
void DarkwatchObservePitch(X86Context& ctx, uint8_t* base) { ObserveAim(ctx, base, 1); ApplyMouseAim(ctx, base, 1); }
void DarkwatchHorseMouseYaw(X86Context& ctx, uint8_t* base) { ApplyHorseMouse(ctx, base, 0); }
void DarkwatchHorseMousePitch(X86Context& ctx, uint8_t* base) { ApplyHorseMouse(ctx, base, 1); }
bool DarkwatchMousePitchActive(X86Context& ctx, uint8_t* base) {
    // Pending mouse Y must still mark its pair before the original manual branch.
    const auto controls = darkwatch::ControlsSnapshot();
    const bool mouse = MousePitchActive(ctx, base, controls.direct_mouse);
    return mouse || (!controls.aim_centering && LocalAimControl(ctx, base, 1));
}
bool DarkwatchSkipYawAssistance(X86Context& ctx, uint8_t* base) {
    return !darkwatch::ControlsSnapshot().aim_assistance && LocalAimControl(ctx, base, 0);
}
bool DarkwatchSkipPitchAssistance(X86Context& ctx, uint8_t* base) {
    return !darkwatch::ControlsSnapshot().aim_assistance && LocalAimControl(ctx, base, 1);
}

