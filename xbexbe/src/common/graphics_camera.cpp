#include "graphics_camera.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstring>
#include <mutex>
#include "graphics_view.h"
#include "graphics_viewport.h"
#include "third_person_visibility.h"
#include "third_person_body.h"
#include "app/app.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"

extern "C" void sub_00216B7C(X86Context& ctx, uint8_t* base);

namespace {
struct Configuration {uint32_t address; std::array<uint32_t, 7> words;};
// FA277 selects these original layouts by active player count and co-op mode.
// The final word is the viewport/player index; the two split layouts have
// different authored FOV scales; widescreen preserves their vertical framing.
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
    float aspect_scale = 1, authored_scale = 1, authored_aspect = 4.0f / 3.0f;
    std::array<uint32_t, 4> viewport{};
    uint64_t epoch = 0;
};
std::mutex g_camera_lock;
std::array<PlayerCamera, 2> g_player_cameras;
std::array<std::atomic<uint32_t>, 2> g_shoulder_left{};
uint64_t g_camera_epoch = 0;
struct ShoulderBlend {
    uint64_t epoch = 0;
    uint32_t personal = 0, actor = 0;
    float side = .7f;
};
std::array<ShoulderBlend, 2> g_shoulder_blends;
struct WeaponView {uint32_t frame = 0, renderer = 0, camera = 0, raster = 0; float scale = 1;};
thread_local WeaponView g_weapon_view;
struct PowerView {uint32_t frame = 0, node = 0, raster = 0; float scale = 1;};
thread_local PowerView g_power_view;
using Vector = std::array<float, 3>;
using Matrix = std::array<uint8_t, 64>;
struct ThirdPersonView {
    PlayerCamera player{};
    uint32_t personal = 0, frame = 0, invocation = 0;
    Matrix matrix{};
    float native_fov = 0;
};
thread_local ThirdPersonView g_third_person_view;
struct ReticleProjection {
    PlayerCamera player{};
    float x = 0, y = 0;
    bool valid = false;
};
thread_local std::array<ReticleProjection, 2> g_third_person_reticles;

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
template<class T> bool Field(const uint8_t* base, uint32_t object, uint32_t offset, T& value) {
    if (!object || !Span(base, uint64_t(object) + offset, sizeof(value))) return false;
    std::memcpy(&value, base + uint64_t(object) + offset, sizeof(value));
    return true;
}
uint32_t OwnedComponent(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    uint16_t count = 0;
    uint32_t list = 0, result = 0;
    if (!Field(base, actor, 0x60, count) || !count || count > 128 ||
        !Field(base, actor, 0x64, list) || !Span(base, list, count * 8)) return 0;
    for (uint32_t i = 0; i < count; ++i) {
        const uint32_t component = Read(base, list + i * 8 + 4);
        uint32_t type = 0, owner = 0;
        if (!Field(base, component, 0, type)) return 0;
        if (type != wanted) continue;
        if (result || !Field(base, component, 0xC, owner) || owner != actor) return 0;
        result = component;
    }
    return result;
}
bool Finite(const Vector& value) {
    return std::all_of(value.begin(), value.end(), [](float v) {return std::isfinite(v);});
}
float Dot(const Vector& a, const Vector& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
bool Unit(const Vector& value) {
    return Finite(value) && std::abs(Dot(value, value) - 1.0f) < 0.02f;
}
Vector Cross(const Vector& a, const Vector& b) {
    return {a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]};
}
bool Normalize(Vector& value) {
    const float length_squared = Dot(value, value);
    if (!std::isfinite(length_squared) || length_squared < .0001f) return false;
    const float scale = 1.f / std::sqrt(length_squared);
    for (float& v : value) v *= scale;
    return true;
}
// Native guest calls keep their usual stack convention; none of their CPU or
// scratch-stack changes may leak into the suspended render callback.
template<size_t Size> struct CameraCall {
    const X86Context& original;
    uint8_t* base;
    std::array<uint8_t, Size> saved;
    CameraCall(const X86Context& source, uint8_t* memory) : original(source), base(memory) {
        std::memcpy(saved.data(), base + original.esp - Size, Size);
    }
    ~CameraCall() {std::memcpy(base + original.esp - Size, saved.data(), Size);}
    uint32_t Argument() const {return original.esp - 16;}
    void Invoke(uint32_t address, uint32_t object) {
        X86Context call = original;
        call.ecx = object;
        call.esp -= 64;
        const uint32_t args[]{0x1E89D2, Argument()};
        std::memcpy(base + call.esp, args, sizeof(args));
        x86_icall(call, base, address);
    }
    void Transform(uint32_t camera, const Matrix& matrix) {
        static_assert(Size >= 1024);
        const uint32_t address = original.esp - 512;
        std::memcpy(base + address, matrix.data(), matrix.size());
        X86Context call = original;
        call.ecx = camera;
        call.esp -= 64;
        const uint32_t args[]{0x1E89D2, address};
        std::memcpy(base + call.esp, args, sizeof(args));
        x86_icall(call, base, 0x216D9A);
    }
    void FieldOfView(uint32_t camera, float fov) {
        static_assert(Size >= 1024);
        X86Context call = original;
        call.ecx = camera;
        call.esp -= 64;
        uint32_t bits = 0;
        std::memcpy(&bits, &fov, sizeof(bits));
        const uint32_t args[]{0x1E89D2, bits, 1};
        std::memcpy(base + call.esp, args, sizeof(args));
        sub_00216B7C(call, base);
    }
};

bool ActivePersonal(const uint8_t* base, const PlayerCamera& player, uint32_t personal) {
    uint16_t count = 0;
    uint32_t list = 0;
    return PlayerValid(base, player) && Field(base, player.owner, 4, count) && count && count <= 64 &&
        Field(base, player.owner, 8, list) && Span(base, list, count * 4) &&
        Read(base, list + (count - 1) * 4) == personal;
}
PlayerCamera ShoulderPlayer(const uint8_t* base, uint32_t actor) {
    if (darkwatch::view::Snapshot(0).camera_mode != darkwatch::view::CameraMode::Shoulder &&
        darkwatch::view::Snapshot(1).camera_mode != darkwatch::view::CameraMode::Shoulder) return {};
    const uint32_t component = OwnedComponent(base, actor, 0x416444);
    uint32_t owner = 0, personal = 0, linked_actor = 0, type = 0, flags = 0;
    if (!Field(base, component, 0x80, owner) || !Field(base, component, 0x70, personal) ||
        !Field(base, personal, 0, type) || type != 0x423990 ||
        !Field(base, actor, 0x90, flags) || (flags & 2) ||
        !Field(base, personal, 0x18C, linked_actor) || linked_actor != actor) return {};
    const PlayerCamera player = FindPlayer(owner, true);
    return ActivePersonal(base, player, personal) &&
        darkwatch::view::Snapshot(player.player).camera_mode == darkwatch::view::CameraMode::Shoulder ? player : PlayerCamera{};
}
float ShoulderTarget(uint32_t player) {
    return g_shoulder_left[player].load(std::memory_order_relaxed) ? -.7f : .7f;
}
bool ThirdPersonZoom(const uint8_t* base, const PlayerCamera& player, uint32_t personal, uint32_t actor);
void UpdateShoulderBlend(const X86Context& ctx, const uint8_t* base, const PlayerCamera& player) {
    uint16_t count = 0;
    uint32_t list = 0, personal = 0, actor = 0, type = 0;
    float dt = 0;
    bool eligible = darkwatch::view::Snapshot(player.player).camera_mode == darkwatch::view::CameraMode::Shoulder &&
        Field(base, player.owner, 4, count) && count && count <= 64 &&
        Field(base, player.owner, 8, list) && Span(base, list, count * 4);
    if (eligible) personal = Read(base, list + (count - 1) * 4);
    eligible = eligible && Field(base, personal, 0, type) && type == 0x423990 &&
        Span(base, personal, 0x1A0) && !base[personal + 0x188] &&
        Field(base, personal, 0x18C, actor) && ShoulderPlayer(base, actor).camera == player.camera &&
        OwnedComponent(base, actor, 0x4227A4) &&
        ThirdPersonZoom(base, player, personal, actor);
    Field(base, ctx.ebp, 8, dt);
    std::lock_guard lock(g_camera_lock);
    if (g_player_cameras[player.player].epoch != player.epoch) return;
    auto& blend = g_shoulder_blends[player.player];
    if (!eligible) {blend = {}; return;}
    const float target = ShoulderTarget(player.player);
    if (blend.epoch != player.epoch || blend.personal != personal || blend.actor != actor)
        blend = {player.epoch, personal, actor, target};
    // 216040 receives the game clock's delta in seconds. Never accumulate wall
    // time while paused/unfocused or integrate a suspended frame on return.
    else if (std::isfinite(dt) && dt > 0 && dt <= .25f)
        blend.side += (target - blend.side) * -std::expm1(-dt / .08f);
}
float ShoulderSide(const PlayerCamera& player, uint32_t personal, uint32_t actor) {
    std::lock_guard lock(g_camera_lock);
    const auto& blend = g_shoulder_blends[player.player];
    return blend.epoch == player.epoch && blend.personal == personal && blend.actor == actor ?
        blend.side : ShoulderTarget(player.player);
}
uint32_t AimedWeapon(const uint8_t* base, uint32_t actor, uint32_t& weapon) {
    const uint32_t inventory = OwnedComponent(base, actor, 0x41F29C);
    uint16_t categories_count = 0, slots_count = 0;
    uint32_t categories = 0, slots = 0, primary = 0, slot = 0, type = 0, owner = 0;
    // Native 951D4/951FA/98A64 resolve category zero to its equipped actor.
    if (!Field(base, inventory, 0x78, categories_count) || !categories_count || categories_count > 64 ||
        !Field(base, inventory, 0x7C, categories) || !Field(base, categories, 0, primary) ||
        !Field(base, inventory, 0x88, slots_count) || !slots_count || slots_count > 128 || primary >= slots_count ||
        !Field(base, inventory, 0x8C, slots) || !Field(base, slots, primary * 4, slot) ||
        !Field(base, slot, 0, type) || type != 0x41F570 ||
        !Field(base, slot, 8, owner) || owner != inventory || !Field(base, slot, 0xC, weapon)) return 0;
    for (const uint32_t vtable : {0x418390u, 0x417E90u, 0x417F78u, 0x418098u, 0x418150u, 0x418208u}) {
        const uint32_t component = OwnedComponent(base, weapon, vtable);
        // All six constructors derive from WeaponComponent (1FC8B). Handheld
        // ownership is InventoryItem+58, not the turret's unrelated +120/+178.
        if (component && Field(base, component, 0x58, owner) && owner == actor) return component;
    }
    return 0;
}
bool ThirdPersonZoom(const uint8_t* base, const PlayerCamera& player, uint32_t personal, uint32_t actor) {
    float normal = 0, current = 0;
    if (!Field(base, personal, 0x16C, normal) || !std::isfinite(normal) || normal <= 0 || normal >= 180 ||
        !Field(base, player.camera, 0x44, current) || !std::isfinite(current) || current <= 0 || current >= 180 ||
        current > normal + .01f) return false;
    if (std::abs(current - normal) <= .01f) return true;
    // Native OnSniperRifleZoom (9EDE7) checks the equipped WeaponComponent's
    // +1B9 flag before entering either scope state. Other handheld sight uses
    // VampireZoom. Keep that native FOV animation, including its zoom-out tail,
    // in third-person; scoped rifles retain the original first-person view.
    uint32_t weapon = 0;
    uint8_t scoped = 0;
    const uint32_t item = AimedWeapon(base, actor, weapon);
    return item && Field(base, item, 0x1B9, scoped) && !scoped;
}
bool AimPoint(const X86Context& ctx, uint8_t* base, uint32_t actor, uint32_t item,
              const Vector& origin, const Vector& forward, Vector& point, uint32_t* hit_actor = nullptr) {
    if (hit_actor) *hit_actor = 0;
    uint32_t weapon = 0, owner = 0;
    float range = 0;
    uint8_t unlimited = 0;
    if (!Finite(origin) || !Unit(forward) || !Field(base, item, 0xC, weapon) ||
        !Field(base, item, 0x58, owner) || owner != actor) return false;
    uint32_t manager = 0, world = 0, collision_world = 0;
    if (!item || !Field(base, item, 0x194, range) || !std::isfinite(range) ||
        !Field(base, item, 0xF5, unlimited) ||
        !Field(base, 0x4ACA3C, 0, manager) || !Field(base, manager, 0xC, world) ||
        !Field(base, world, 0xC4, collision_world) || !Span(base, collision_world, 4) ||
        !Span(base, uint64_t(actor) + 0x90, 8) || !Span(base, 0x49A254, 8) || !Span(base, 0x4ACA40, 4) ||
        !Span(base, 0x4B4A24, 4) || ctx.esp < 16384 || !Span(base, uint64_t(ctx.esp) - 16384, 16384)) return false;
    // The original handheld mask and actor exclusions apply to this camera
    // target query too; only the subsequent shot reply changes direction.
    CameraCall<16384> scratch(ctx, base);
    const uint32_t data = ctx.esp - 256, stack = ctx.esp - 512;
    Vector end{};
    range = unlimited ? 1000000.0f : std::max(range, 1.0f);
    for (unsigned i = 0; i < 3; ++i) end[i] = origin[i] + forward[i] * range;
    if (!Finite(end)) return false;
    point = end;
    std::memset(base + data, 0, 96);
    std::memcpy(base + data, origin.data(), sizeof(origin));
    std::memcpy(base + data + 16, end.data(), sizeof(end));
    const uint32_t exclusions[]{weapon, actor, 0};
    std::memcpy(base + data + 80, exclusions, sizeof(exclusions));
    X86Context call = ctx;
    call.esp = stack;
    const uint32_t mask_args[]{0x22957, actor};
    std::memcpy(base + stack, mask_args, sizeof(mask_args));
    x86_icall(call, base, 0x228EF);
    const uint32_t args[]{0x2299C, data, data + 16, data + 32, data + 48, data + 64, data + 68,
        data + 72, 0, data + 76, data + 80, 0, call.eax | 2u, 0, 0, 1};
    const uint32_t saved_hit = Read(base, 0x4B4A24);
    struct RestoreHit {
        uint8_t* base; uint32_t value;
        ~RestoreHit() {std::memcpy(base + 0x4B4A24, &value, 4);}
    } restore{base, saved_hit};
    call = ctx;
    call.esp = stack;
    std::memcpy(base + stack, args, sizeof(args));
    x86_icall(call, base, 0x1DF12B);
    // The native no-hit query leaves its point unwritten. Keep the end of this
    // camera ray on a miss; do not read a stale collision point.
    if ((call.eax & 0xFF) != 1) return true;
    Vector hit{}, delta{};
    std::memcpy(hit.data(), base + data + 32, sizeof(hit));
    if (!Finite(hit)) return false;
    for (unsigned i = 0; i < 3; ++i) delta[i] = hit[i] - origin[i];
    const float along = Dot(delta, forward);
    if (along >= 0 && along <= range + .01f && Dot(delta, delta) - along * along <= .01f) {
        if (hit_actor) *hit_actor = Read(base, data + 76);
        point = hit;
        return true;
    }
    return false;
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

void ConfigureCinematic(const X86Context& ctx, uint8_t* base, uint32_t owner, uint32_t resume) {
    if (!Span(base, 0x4B7A34, 0xE) || base[0x4B7A41] ||
        !owner || Read(base, 0x4B7A34) != owner || !Span(base, owner, 0x14)) return;
    const uint32_t camera = Read(base, owner + 0xC);
    constexpr std::array<uint32_t, 4> viewport{0, 0, 0x3F800000, 0x3F800000};
    if (!Span(base, camera, 0x68) ||
        !CameraValid(base, camera, Read(base, camera + 0x34)) ||
        std::memcmp(base + camera + 0x58, viewport.data(), sizeof(viewport))) return;
    float previous, scale;
    std::memcpy(&previous, base + camera + 0x40, 4);
    const float aspect = app::RenderAspect();
    const float desired_scale = std::max(1.0f, aspect / (16.0f / 9.0f));
    const bool authored = previous == 4.0f / 3.0f || previous == 16.0f / 9.0f;
    if (!std::isfinite(previous) || (!authored && previous < 4.0f / 3.0f) ||
        !ScaleValid(base, camera, scale) ||
        scale != (authored ? 1.0f : std::max(1.0f, previous / (16.0f / 9.0f))) ||
        (previous == aspect && scale == desired_scale) ||
        ctx.esp < 256 || !Span(base, uint64_t(ctx.esp) - 256, 256)) return;
    // Retain the published 16:9 shot vertically; wider displays reveal more at
    // the sides instead of cropping its top/bottom. Native zoom/culling remain active.
    std::memcpy(base + camera + 0x40, &aspect, 4);
    SetScale(ctx, base, camera, desired_scale, resume);
}
struct ThirdPersonPose {
    PlayerCamera player{};
    uint32_t personal = 0, actor = 0, follow = 0, frame = 0;
    Vector position{}, right{}, up{}, forward{}, desired{};
};
struct DeathView {
    ThirdPersonPose pose{};
    float fov = 0;
    uint32_t rig = 0, root_motion = 0;
    Vector root_origin{};
};
std::array<DeathView, 2> g_death_views;
enum class PoseUse { Living, DeathEntry, CoopBody };
bool ReadThirdPersonPose(const X86Context& ctx, uint8_t* base, uint32_t personal, ThirdPersonPose& pose,
                         PoseUse use = PoseUse::Living) {
    const bool death_entry = use == PoseUse::DeathEntry;
    if (!Span(base, personal, 0x1A0) || Read(base, personal) != 0x423990 ||
        (!death_entry && base[personal + 0x188])) return false;
    const uint32_t actor = Read(base, personal + 0x18C);
    const uint32_t component = OwnedComponent(base, actor, 0x416444);
    uint32_t owner = 0, linked_personal = 0, follow = 0, type = 0, linked_actor = 0, flags = 0;
    if (!OwnedComponent(base, actor, 0x4227A4) ||
        !Field(base, actor, 0x90, flags) || (!death_entry && (flags & 2)) ||
        !Field(base, component, 0x70, linked_personal) || linked_personal != personal ||
        !Field(base, component, 0x80, owner)) return false;
    const PlayerCamera player = FindPlayer(owner, true);
    if (!ActivePersonal(base, player, personal)) return false;
    if (!death_entry) {
        std::lock_guard lock(g_camera_lock);
        const auto& dying = g_death_views[player.player].pose;
        if (dying.actor == actor && dying.personal == personal && dying.player.base == base &&
            dying.player.epoch == player.epoch) return false;
    }
    const auto mode = darkwatch::view::Snapshot(player.player).camera_mode;
    const auto& viewport = player.viewport;
    const bool first_person_body = use == PoseUse::CoopBody &&
        mode == darkwatch::view::CameraMode::FirstPerson &&
        darkwatch::viewport::Identify(viewport[0], viewport[1], viewport[2], viewport[3]).Split();
    if (!first_person_body && mode != darkwatch::view::CameraMode::Centered &&
        mode != darkwatch::view::CameraMode::Shoulder) return false;
    // Horse, turret and authored cameras replace the top. Native player death
    // instead freezes this personal camera at +188 (A8E2C -> BCC0C). Death entry
    // and a co-op body seen by its partner do not require an external zoom view.
    if ((!death_entry && !first_person_body && !ThirdPersonZoom(base, player, personal, actor)) ||
        !Field(base, component, 0x4C, follow) || !Span(base, follow, 0xE0) ||
        !Field(base, follow, 0, type) || type != 0x423D64 ||
        !Field(base, follow, 0xDC, linked_actor) || linked_actor != actor) return false;
    uint32_t frame = 0;
    Vector right{}, up{}, forward{}, position{}, actor_up{};
    float window_x = 0, window_y = 0;
    if (!Field(base, player.raster, 4, frame) || !Span(base, frame, 0x70) ||
        !Field(base, player.raster, 0x68, window_x) || !std::isfinite(window_x) || window_x <= 0 ||
        !Field(base, player.raster, 0x6C, window_y) || !std::isfinite(window_y) || window_y <= 0) return false;
    // Native 1B0 and D3 both use ChazControl's current +170 direction; 1B0
    // supplies +1A8 as the eye. Firing can precede the personal-camera update,
    // so its previous RW matrix is not an authoritative input pose. Reuse D3's
    // actor-up construction for both this view and the shot target. First-person
    // camera bob stays in its original matrix, restored after the render scope.
    const uint32_t control = OwnedComponent(base, actor, 0x41F878);
    if (!Field(base, control, 0x170, forward) || !Unit(forward) ||
        !Field(base, control, 0x1A8, position) || !Finite(position) ||
        !Field(base, actor, 0x20, actor_up) || !Unit(actor_up)) return false;
    right = Cross(actor_up, forward);
    if (!Normalize(right)) return false;
    up = Cross(forward, right);
    if (!Normalize(up)) return false;
    const bool shoulder = mode == darkwatch::view::CameraMode::Shoulder;
    const float side = shoulder ? ShoulderSide(player, personal, actor) : 0.f;
    Vector desired{};
    for (unsigned i = 0; i < 3; ++i)
        desired[i] = position[i] - forward[i] * (shoulder ? 2.5f : 3.5f) +
            up[i] * (shoulder ? .2f : .35f) + right[i] * (shoulder ? side : 0.f);
    if (!Finite(desired) || ctx.esp < 8192 || !Span(base, uint64_t(ctx.esp) - 8192, 8192)) return false;
    pose = {player, personal, actor, follow, frame, position, right, up, forward, desired};
    return true;

}

bool SweepThirdPersonPose(const X86Context& ctx, uint8_t* base, const ThirdPersonPose& pose, Vector& clipped) {
    const auto follow = pose.follow;
    const auto& position = pose.position;
    const auto& desired = pose.desired;
    CameraCall<8192> call(ctx, base);
    std::array<uint8_t, 24> saved_follow;
    std::memcpy(saved_follow.data(), base + follow + 0xA8, saved_follow.size());
    struct RestoreFollow {
        uint8_t* target; const std::array<uint8_t, 24>& saved;
        ~RestoreFollow() {std::memcpy(target, saved.data(), saved.size());}
    } restore{base + follow + 0xA8, saved_follow};
    // Reuse the original follow-camera sphere sweep. This query restores its
    // anchor/desired scratch fields; the native camera stack remains personal.
    std::memcpy(base + follow + 0xA8, position.data(), sizeof(position));
    std::memcpy(base + follow + 0xB4, desired.data(), sizeof(desired));
    call.Invoke(0xBF198, follow);
    Vector delta{};
    std::memcpy(clipped.data(), base + call.Argument(), sizeof(clipped));
    if (!Finite(clipped)) return false;
    for (unsigned i = 0; i < 3; ++i) delta[i] = clipped[i] - position[i];
    const float distance_squared = Dot(delta, delta);
    // Keep the sphere-swept position even when the boom collapses at a wall.
    // A minimum boom or a first-person fallback would clip or change modes.
    if (distance_squared > 20.0f) return false;
    return true;
}

bool DeathRoot(const uint8_t* base, uint32_t actor, uint32_t& rig, uint32_t& motion, Vector& position) {
    const uint32_t animation = OwnedComponent(base, actor, 0x41D258);
    uint32_t wrapper = 0, type = 0, linked_actor = 0, collection = 0, bodies = 0, count = 0, maps = 0, root = 0, body = 0;
    uint8_t flags = 0, active = 0;
    if (!Field(base, animation, 0x84, flags) || !(flags & 8) ||
        !Field(base, animation, 0x90, wrapper) || !Field(base, wrapper, 0, type) || type != 0x41D4AC ||
        !Field(base, wrapper, 4, rig) || !Field(base, rig, 0x12C, linked_actor) || linked_actor != actor ||
        !Field(base, rig, 0xC1, active)) return false;
    // Inactive rig transforms are still local bind poses. Latch only after the
    // original death activation has transferred this actor's animated pose.
    motion = 0;
    if (!active) return true;
    // Native 6F23A selects the shallowest physical root at +30; 6D29E reads the
    // body's world translation through motion+B0. Do not assume body/bone zero.
    return Field(base, rig, 4, collection) && Field(base, collection, 8, bodies) &&
        Field(base, collection, 0xC, count) && count && count <= 64 && Span(base, bodies, count * 4) &&
        Field(base, rig, 0x10, maps) && maps == count && Field(base, rig, 0x30, root) && root < count &&
        Field(base, bodies, root * 4, body) && Field(base, body, 0x3C, motion) &&
        Field(base, motion, 0xB0, position) && Finite(position);
}

bool ReadDeathView(const uint8_t* base, uint32_t personal, ThirdPersonPose& pose, float& fov) {
    std::lock_guard lock(g_camera_lock);
    for (auto& death : g_death_views) {
        const auto& saved = death.pose;
        if (saved.personal != personal || saved.player.base != base) continue;
        const auto& current = g_player_cameras[saved.player.player];
        uint32_t actor = 0, frame = 0, linked_personal = 0, owner = 0, follow = 0, follow_type = 0, follow_actor = 0;
        const uint32_t component = OwnedComponent(base, saved.actor, 0x416444);
        if (current.epoch != saved.player.epoch || current.owner != saved.player.owner ||
            !ActivePersonal(base, saved.player, personal) || !Span(base, personal, 0x1A0) ||
            Read(base, personal) != 0x423990 || !Field(base, personal, 0x18C, actor) || actor != saved.actor ||
            !Field(base, component, 0x70, linked_personal) || linked_personal != personal ||
            !Field(base, component, 0x80, owner) || owner != saved.player.owner ||
            !Field(base, component, 0x4C, follow) || follow != saved.follow || !Span(base, follow, 0xE0) ||
            !Field(base, follow, 0, follow_type) || follow_type != 0x423D64 ||
            !Field(base, follow, 0xDC, follow_actor) || follow_actor != saved.actor ||
            !Field(base, saved.player.raster, 4, frame) || frame != saved.frame || !Span(base, frame, 0x70) ||
            darkwatch::view::Snapshot(saved.player.player).camera_mode == darkwatch::view::CameraMode::FirstPerson) {
            death = {};
            return false;
        }
        uint32_t rig = 0, motion = 0;
        Vector position{};
        if (!DeathRoot(base, saved.actor, rig, motion, position) ||
            (death.root_motion && (death.rig != rig || death.root_motion != motion))) {
            death = {};
            return false;
        }
        pose = saved;
        if (motion) {
            if (!death.root_motion) {
                death.rig = rig;
                death.root_motion = motion;
                death.root_origin = position;
            }
            // Follow physical translation directly, independently of render FPS;
            // retain the captured aim basis and eye/boom offset while it falls.
            for (unsigned i = 0; i < 3; ++i) {
                const float delta = position[i] - death.root_origin[i];
                pose.position[i] += delta;
                pose.desired[i] += delta;
            }
            if (!Finite(pose.position) || !Finite(pose.desired)) return false;
        }
        fov = death.fov;
        return true;
    }
    return false;
}

}  // namespace

bool DarkwatchBeginThirdPersonDeath(const X86Context& ctx, uint8_t* base, uint32_t actor) {
    DarkwatchEndThirdPersonDeath(base, actor);
    uint32_t personal = 0;
    const uint32_t component = OwnedComponent(base, actor, 0x416444);
    ThirdPersonPose pose;
    Vector clipped{};
    float fov = 0;
    if (!Field(base, component, 0x70, personal) ||
        !ReadThirdPersonPose(ctx, base, personal, pose, PoseUse::DeathEntry) || pose.actor != actor ||
        !Field(base, personal, 0x16C, fov) || !std::isfinite(fov) || fov <= 0 || fov >= 180 ||
        !SweepThirdPersonPose(ctx, base, pose, clipped)) return false;
    std::lock_guard lock(g_camera_lock);
    if (g_player_cameras[pose.player.player].epoch != pose.player.epoch) return false;
    g_death_views[pose.player.player] = {pose, fov};
    g_third_person_reticles[pose.player.player] = {};
    return true;
}

void DarkwatchEndThirdPersonDeath(uint8_t* base, uint32_t actor) {
    std::lock_guard lock(g_camera_lock);
    for (auto& death : g_death_views)
        if (death.pose.player.base == base && death.pose.actor == actor) death = {};
}

void DarkwatchConfigureCinematicCamera(X86Context& ctx, uint8_t* base) {
    ConfigureCinematic(ctx, base, ctx.eax, 0x21AF54);
}


void DarkwatchPreparePlayerViewport(X86Context& ctx, uint8_t* base) {
    // F9B52 passes the authored rectangle into the native camera constructor.
    // Change it before native color/depth subrasters and the HUD camera are made.
    if (!darkwatch::view::Snapshot().vertical_split) return;
    for (const auto& config : kConfigurations) {
        if (ctx.esi != config.address || config.address == 0x491668) continue;
        if (!Span(base, ctx.esi, sizeof(config.words)) ||
            std::memcmp(base + ctx.esi, config.words.data(), sizeof(config.words)) ||
            !Span(base, ctx.esp, 20) ||
            std::memcmp(base + ctx.esp, config.words.data() + 2, 20) ||
            !Span(base, ctx.ecx, 0x14)) return;
        const auto rectangle = darkwatch::viewport::Split(true, config.words[6]);
        std::memcpy(base + ctx.esp, rectangle.data(), sizeof(rectangle));
        return;
    }
}

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
        Read(base, ctx.ecx) != 0x0043F97C) return;

    const bool full = ctx.esi == 0x491668;
    const auto viewport = darkwatch::viewport::Identify(Read(base, ctx.ecx + 0x58),
        Read(base, ctx.ecx + 0x5C), Read(base, ctx.ecx + 0x60), Read(base, ctx.ecx + 0x64));
    if (viewport.player != configuration->words[6] ||
        (full ? viewport.kind != darkwatch::viewport::Kind::Full : !viewport.Split())) return;
    float aspect, aspect_scale;
    std::memcpy(&aspect, base + ctx.esi + 4, 4);
    std::memcpy(&aspect_scale, base + ctx.esi, 4);
    // Side-by-side has one half-width full-height view. Keep the same authored
    // vertical field of view while matching its actual pixel aspect.
    if (viewport.kind == darkwatch::viewport::Kind::Vertical) {
        aspect *= .4975f / 2.f;
        aspect_scale *= .4975f / 2.f;
    }
    const float authored_aspect = aspect, authored_scale = aspect_scale;
    const float output_aspect = app::RenderAspect();
    const float ratio = output_aspect / (4.0f / 3.0f);
    aspect = full ? output_aspect : aspect * ratio;
    aspect_scale *= ratio;
    const uint32_t index = configuration->words[6];
    const float scale = aspect_scale * (float(darkwatch::view::Snapshot(index).fov_percent) / 100.0f);
    if (ratio != 1 || viewport.kind == darkwatch::viewport::Kind::Vertical || scale != aspect_scale) {
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
        player = {base, ctx.edi, ctx.ecx, Read(base, ctx.ecx + 0x34), index,
                  aspect_scale, authored_scale, authored_aspect, {}, ++g_camera_epoch};
        std::memcpy(player.viewport.data(), base + ctx.ecx + 0x58, 16);
    }
    LOG_FIRST(4, "Player %u camera %08X: aspect %.4f (authored zoom retained)", index + 1, ctx.ecx, aspect);
}

void DarkwatchUpdateCameraView(X86Context& ctx, uint8_t* base) {
    ConfigureCinematic(ctx, base, ctx.esi, 0x21606D);
    const PlayerCamera player = FindPlayer(ctx.esi, true);
    // At 21606D the original active-camera update has finished; ESI is its owning
    // component. Never apply this preference to a separate weapon/render camera.
    if (!PlayerValid(base, player)) return;
    g_third_person_reticles[player.player] = {};
    UpdateShoulderBlend(ctx, base, player);
    uint16_t count = 0;
    uint32_t list = 0, personal = 0, actor = 0;
    const auto& viewport = player.viewport;
    if ((darkwatch::view::Snapshot(player.player).camera_mode != darkwatch::view::CameraMode::FirstPerson ||
         darkwatch::viewport::Identify(viewport[0], viewport[1], viewport[2], viewport[3]).Split()) &&
        Field(base, player.owner, 4, count) && count && count <= 64 &&
        Field(base, player.owner, 8, list) && Span(base, list, count * 4))
        personal = Read(base, list + (count - 1) * 4);
    if (Span(base, personal, 4) && Read(base, personal) == 0x423990 &&
        Field(base, personal, 0x18C, actor))
        DarkwatchThirdPersonBodyAim(ctx, base, actor);
    const float ratio = app::RenderAspect() / (4.0f / 3.0f);
    const float aspect = player.authored_aspect * ratio;
    const float aspect_scale = player.authored_scale * ratio;
    const float scale = aspect_scale * (float(darkwatch::view::Snapshot(player.player).fov_percent) / 100.0f);
    float previous, nominal, previous_aspect;
    std::memcpy(&previous_aspect, base + player.camera + 0x40, 4);
    std::memcpy(&previous, base + player.camera + 0x48, 4);
    std::memcpy(&nominal, base + player.camera + 0x44, 4);
    if ((previous == scale && previous_aspect == aspect) || !std::isfinite(previous) || previous <= 0 ||
        !std::isfinite(previous_aspect) || previous_aspect <= 0 ||
        !std::isfinite(nominal) || nominal <= 0 || nominal >= 180 ||
        ctx.esp < 256 || !Span(base, uint64_t(ctx.esp) - 256, 256)) return;

    // Preserve the authored nominal angle/zoom. Only the original view-window
    // scale changes, and the original setter updates projection and dirty state.
    std::memcpy(base + player.camera + 0x40, &aspect, 4);
    SetScale(ctx, base, player.camera, scale, 0x21606D);
    std::lock_guard lock(g_camera_lock);
    for (auto& current : g_player_cameras)
        if (current.base == player.base && current.owner == player.owner && current.camera == player.camera)
            current.aspect_scale = aspect_scale;
}

bool DarkwatchBeginThirdPersonRender(X86Context& ctx, uint8_t* base, uint32_t personal) {
    if (darkwatch::view::Snapshot(0).camera_mode == darkwatch::view::CameraMode::FirstPerson &&
        darkwatch::view::Snapshot(1).camera_mode == darkwatch::view::CameraMode::FirstPerson) return false;
    if (g_third_person_view.personal || !Span(base, ctx.esp, 4) || Read(base, ctx.esp) != 0x1E89D2 ||
        !Span(base, ctx.ebp, 4)) return false;
    ThirdPersonPose pose;
    Vector clipped{};
    float death_fov = 0, native_fov = 0;
    const bool death = ReadDeathView(base, personal, pose, death_fov);
    if (!death && !ReadThirdPersonPose(ctx, base, personal, pose)) return false;
    g_third_person_reticles[pose.player.player] = {};
    if (!death) {
        DarkwatchPrepareThirdPersonHands(ctx, base, personal);
        if (!ReadThirdPersonPose(ctx, base, personal, pose) ||
            !SweepThirdPersonPose(ctx, base, pose, clipped)) return false;
    } else if (ctx.esp < 8192 || !Span(base, uint64_t(ctx.esp) - 8192, 8192) ||
               !SweepThirdPersonPose(ctx, base, pose, clipped)) return false;
    if (death) {
        float scale = 0, aspect = 0;
        if (!ScaleValid(base, pose.player.camera, scale) ||
            !Field(base, pose.player.camera, 0x40, aspect) || !std::isfinite(aspect) || aspect <= 0 ||
            !Field(base, pose.player.camera, 0x44, native_fov)) return false;
    }
    Matrix saved{}, matrix{};
    std::memcpy(saved.data(), base + pose.frame + 0x10, saved.size());
    matrix = saved;
    std::memcpy(matrix.data(), pose.right.data(), sizeof(pose.right));
    std::memcpy(matrix.data() + 16, pose.up.data(), sizeof(pose.up));
    std::memcpy(matrix.data() + 32, pose.forward.data(), sizeof(pose.forward));
    std::memcpy(matrix.data() + 48, clipped.data(), sizeof(clipped));
    // Native 10BB80 invalidates these matrix fast-path flags after a change.
    // The replacement setter copies all 64 bytes, including its flags.
    const uint32_t flags = Read(base, pose.frame + 0x1C) & 0xFFFDFFFCu;
    std::memcpy(matrix.data() + 12, &flags, sizeof(flags));
    CameraCall<1024> call(ctx, base);
    call.Transform(pose.player.camera, matrix);
    if (death) call.FieldOfView(pose.player.camera, death_fov);
    g_third_person_view = {pose.player, personal, pose.frame, ctx.ebp, saved, native_fov};
    // The shot reply converges on the center-camera target. Depth changes must
    // not slide the reticle across the screen when crossing foreground edges.
    if (!death) g_third_person_reticles[pose.player.player] = {pose.player, 0.f, 0.f, true};
    return true;
}

bool DarkwatchThirdPersonPlayer(const X86Context& ctx, uint8_t* base, uint32_t actor, uint32_t control) {
    const uint32_t component = OwnedComponent(base, actor, 0x416444);
    uint32_t personal = 0;
    ThirdPersonPose pose;
    return OwnedComponent(base, actor, 0x41F878) == control &&
        Field(base, component, 0x70, personal) &&
        ReadThirdPersonPose(ctx, base, personal, pose, PoseUse::CoopBody) && pose.actor == actor;
}

bool DarkwatchThirdPersonBodyAimTarget(const X86Context& ctx, uint8_t* base, uint32_t actor,
                                      std::array<float, 3>& target) {
    const uint32_t component = OwnedComponent(base, actor, 0x416444);
    uint32_t personal = 0;
    ThirdPersonPose pose;
    if (!Field(base, component, 0x70, personal) ||
        !ReadThirdPersonPose(ctx, base, personal, pose, PoseUse::CoopBody) || pose.actor != actor) return false;
    if (darkwatch::view::Snapshot(pose.player.player).camera_mode != darkwatch::view::CameraMode::FirstPerson)
        return DarkwatchThirdPersonAimTarget(ctx, base, actor, 0, target);
    // A teammate sees the body, but its first-person owner's native shot ray stays unchanged.
    for (unsigned i = 0; i < 3; ++i) target[i] = pose.position[i] + pose.forward[i] * 100.f;
    return Finite(target);
}

bool DarkwatchThirdPersonAimTarget(const X86Context& ctx, uint8_t* base, uint32_t actor,
                                  uint32_t weapon_component, std::array<float, 3>& target, uint32_t* target_actor) {
    if (target_actor) *target_actor = 0;
    if (darkwatch::view::Snapshot(0).camera_mode == darkwatch::view::CameraMode::FirstPerson &&
        darkwatch::view::Snapshot(1).camera_mode == darkwatch::view::CameraMode::FirstPerson) return false;
    uint32_t weapon = 0, owner = 0, type = 0;
    if (!weapon_component) weapon_component = AimedWeapon(base, actor, weapon);
    // Both main and offhand components use the original InventoryItem owner.
    // Do not require the firing component to be the category-zero primary slot.
    if (!Field(base, weapon_component, 0, type) ||
        (type != 0x418390 && type != 0x417E90 && type != 0x417F78 &&
         type != 0x418098 && type != 0x418150 && type != 0x418208) ||
        !Field(base, weapon_component, 0xC, weapon) ||
        !Field(base, weapon_component, 0x58, owner) || owner != actor ||
        OwnedComponent(base, weapon, type) != weapon_component) return false;
    const uint32_t component = OwnedComponent(base, actor, 0x416444);
    uint32_t personal = 0;
    ThirdPersonPose pose;
    if (!Field(base, component, 0x70, personal) || !ReadThirdPersonPose(ctx, base, personal, pose) ||
        pose.actor != actor) return false;
    Vector clipped{};
    if (!SweepThirdPersonPose(ctx, base, pose, clipped)) return false;
    return AimPoint(ctx, base, actor, weapon_component, clipped, pose.forward, target, target_actor);
}

void DarkwatchEndThirdPersonRender(X86Context& ctx, uint8_t* base, uint32_t personal) {
    const ThirdPersonView saved = g_third_person_view;
    if (!saved.personal || saved.personal != personal || saved.player.base != base || saved.invocation != ctx.ebp ||
        !Span(base, ctx.esp, 4) || Read(base, ctx.esp) != 0x1E8A0D) return;
    g_third_person_view = {};
    uint32_t frame = 0;
    if (!PlayerValid(base, saved.player) || !Field(base, saved.player.raster, 4, frame) || frame != saved.frame ||
        ctx.esp < 1024 || !Span(base, uint64_t(ctx.esp) - 1024, 1024)) return;
    CameraCall<1024> call(ctx, base);
    call.Transform(saved.player.camera, saved.matrix);
    if (saved.native_fov > 0) call.FieldOfView(saved.player.camera, saved.native_fov);
}

bool DarkwatchThirdPersonRenderActive(const uint8_t* base, uint32_t camera) {
    return g_third_person_view.personal && g_third_person_view.player.base == base &&
        g_third_person_view.player.camera == camera && PlayerValid(base, g_third_person_view.player);
}

bool DarkwatchSwapShoulder(const uint8_t* base, uint32_t actor) {
    const PlayerCamera player = ShoulderPlayer(base, actor);
    if (!player.base) return false;
    g_shoulder_left[player.player].fetch_xor(1u, std::memory_order_relaxed);
    return true;
}

bool DarkwatchShoulderAvailable(const uint8_t* base, uint32_t actor) {
    return ShoulderPlayer(base, actor).base != nullptr;
}

bool DarkwatchThirdPersonReticle(const uint8_t* base, uint32_t player, float& x, float& y) {
    if (player >= g_third_person_reticles.size()) return false;
    const auto& value = g_third_person_reticles[player];
    if (!value.valid || !PlayerValid(base, value.player) ||
        darkwatch::view::Snapshot(player).camera_mode == darkwatch::view::CameraMode::FirstPerson) return false;
    x = value.x; y = value.y;
    return true;
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
    // B851D binds rune overlays to their player's camera. Both authored resources
    // contain a fixed 2.1 x 1.1 rectangle; world FOV must not shrink it.
    // +50 is the original CRC32 of the resolved resource path, not the body aura.
    if (g_power_view.frame || !Span(base, ctx.ecx, 0x70)) return;
    const uint32_t resource = Read(base, ctx.ecx + 0x50);
    const bool blast = resource == 0x6DBE010D; // FX/MoEExplodeBlast
    if ((!blast && resource != 0x9EA613DE && resource != 0xC541E482) ||
        !base[ctx.ecx + 0x62] || Read(base, ctx.ecx + 0x54) != (blast ? 0u : 1u) ||
        !Span(base, ctx.ebp, 12) ||
        !Span(base, ctx.esi, 4) || Read(base, ctx.esi) != ctx.ecx) return;
    const PlayerCamera player = FindPlayer(Read(base, ctx.ebp + 8), false);
    const uint32_t binding = Read(base, ctx.ecx + 0x68);
    float scale;
    if (!PlayerValid(base, player) ||
        (binding != player.raster && (!blast || binding)) ||
        !ScaleValid(base, player.camera, scale) ||
        !std::isfinite(player.aspect_scale) || player.aspect_scale <= 0) return;
    const float user_scale = scale / player.aspect_scale;
    if (!std::isfinite(user_scale) || user_scale < 0.5f || user_scale > 2.0f) return;
    // MoEExplodeBlast is an untextured, camera-relative square in the actor pass,
    // separate from MoEExplode's world particles. Its original 2.0059 square at
    // depth 1.46814 covers 4:3 even when rotated; widescreen/split aspect scaling
    // also exposes its edges. Preserve that authored horizontal coverage in each
    // player's viewport, without changing zoom. Rune rectangles were authored
    // wide enough for solo 16:9; wider/split cameras also need that coverage,
    // otherwise their edges become visible even with the default world FOV.
    const float coverage = std::max(1.0f, player.aspect_scale / ((16.0f / 9.0f) / (4.0f / 3.0f)));
    const float factor = blast ? scale : user_scale * coverage;
    if (factor == 1) return;
    g_power_view = {ctx.ebp, ctx.esi, player.raster, factor};
}

void DarkwatchEndPowerView(X86Context& ctx, uint8_t*) {
    if (g_power_view.frame == ctx.ebp && g_power_view.node == ctx.esi) g_power_view = {};
}

bool DarkwatchWorldProjectionMatches(const uint8_t* base, uint32_t camera,
                                    const std::array<float, 16>& projection) {
    const PlayerCamera player = FindPlayer(camera, false);
    if (!PlayerValid(base, player) || !Span(base, player.raster, 0x88) ||
        Read(base, player.raster + 0x14) != 1) return false;
    std::array<float, 6> fields;
    std::memcpy(fields.data(), base + player.raster + 0x70, sizeof(fields));
    for (float value : fields) if (!std::isfinite(value)) return false;
    const auto [x, y, ox, oy, near_z, far_z] = fields;
    if (x <= 0 || y <= 0 || near_z <= 0 || far_z <= near_z) return false;
    // Original RW BeginUpdate (128AB0) sends this matrix through SetTransform(1).
    // Compare against that camera, but submit the untouched SDK matrix itself.
    const float z = far_z / (far_z - near_z);
    const std::array<float, 16> expected{x, 0, 0, 0, 0, y, 0, 0,
        ox*x, oy*y, z, 1, -ox*x, -oy*y, -near_z*z, 0};
    for (size_t i = 0; i < projection.size(); ++i)
        if (!std::isfinite(projection[i]) ||
            std::abs(projection[i] - expected[i]) > 0.00001f * std::max(1.f, std::abs(expected[i])))
            return false;
    return true;
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
