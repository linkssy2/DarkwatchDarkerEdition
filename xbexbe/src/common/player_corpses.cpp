#include "graphics_view.h"
#include "core/log.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>

X86_EXTERN_FUNC(__imp__sub_000CBA27);
X86_EXTERN_FUNC(__imp__sub_0006C5A5);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(T)); return true;
}
void Put(uint8_t* base, uint32_t at, uint32_t value) { std::memcpy(base + at, &value, 4); }
bool Text(const uint8_t* base, uint64_t at, std::string& value) {
    uint32_t p = 0; value.clear();
    if (!Read(base, at, p) || !p) return false;
    for (unsigned i = 0; i < 128; ++i) {
        char c = 0; if (!Read(base, uint64_t(p) + 2 + i, c)) return false;
        if (!c) return true; value += c;
    }
    return false;
}
bool Playable(const std::string& name) {
    constexpr const char* names[]{"Chaz", "CoOpChaz", "CassidyPlayerTwo", "CassidySolo", "JerichoCoop",
        "CassidySpectralPlayerTwo", "CassidySpectralSolo", "CivilianJerichoSolo", "CivilianJerichoCoop",
        "TrooperSolo", "TrooperCoop", "BlueTrooperSolo", "BlueTrooperCoop", "RedTrooperSolo", "RedTrooperCoop",
        "TalaSolo", "TalaCoop", "VampireTalaSolo", "VampireTalaCoop", "BossTalaSolo", "BossTalaCoop"};
    for (auto candidate : names) if (name == candidate) return true;
    return false;
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t type) {
    uint16_t n = 0; uint32_t list = 0, found = 0;
    if (!Read(base, uint64_t(actor) + 0x60, n) || !n || n > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, n * 8)) return 0;
    for (unsigned i = 0; i < n; ++i) {
        uint32_t c = 0, v = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, c) || !Read(base, c, v)) return 0;
        if (v != type) continue;
        if (found || !Read(base, uint64_t(c) + 0xC, owner) || owner != actor) return 0;
        found = c;
    }
    return found;
}
bool Stack(const X86Context& ctx, const uint8_t* base) {
    return base == kernel::g_base && ctx.esp >= 0x10000 && Span(base, uint64_t(ctx.esp) - 0x10000, 0x10010);
}
struct Scratch {
    X86Context call; uint8_t* base; uint32_t at; std::array<uint8_t, 0x400> saved;
    Scratch(const X86Context& ctx, uint8_t* b) : call(ctx), base(b), at((ctx.esp - 0x500) & ~15u) {
        std::memcpy(saved.data(), base + at, saved.size()); std::memset(base + at, 0, saved.size()); call.esp = at - 0x20;
    }
    ~Scratch() { std::memcpy(base + at, saved.data(), saved.size()); }
    uint32_t Invoke(uint32_t fn, uint32_t object, std::initializer_list<uint32_t> args = {}) {
        call.ecx = object; return kernel::CallGuest(call, fn, args);
    }
};
struct Rig { uint32_t wrapper = 0, impl = 0, skeleton = 0, bodies = 0, count = 0; uint8_t active = 0; };
bool GetRig(const uint8_t* base, uint32_t actor, uint32_t animation, uint32_t offset, Rig& rig) {
    uint32_t v = 0, owner = 0, collection = 0, map = 0, maps = 0;
    return Read(base, uint64_t(animation) + offset, rig.wrapper) && Read(base, rig.wrapper, v) && v == 0x41D4AC &&
        Read(base, uint64_t(rig.wrapper) + 4, rig.impl) && Span(base, rig.impl, 0x1B0) &&
        Read(base, uint64_t(rig.impl) + 0x12C, owner) && owner == actor &&
        Read(base, rig.impl, rig.skeleton) && Span(base, rig.skeleton, 0x18) &&
        Read(base, uint64_t(rig.impl) + 4, collection) &&
        Read(base, uint64_t(collection) + 8, rig.bodies) &&
        Read(base, uint64_t(collection) + 0xC, rig.count) && rig.count && rig.count <= 64 &&
        Span(base, rig.bodies, rig.count * 4) && Read(base, uint64_t(rig.impl) + 0xC, map) &&
        Read(base, uint64_t(rig.impl) + 0x10, maps) && maps == rig.count && Span(base, map, maps * 4) &&
        Read(base, uint64_t(rig.impl) + 0xC1, rig.active);
}
struct BodyPose { std::array<float, 16> transform; std::array<float, 4> linear, angular; };
template<size_t N> bool Floats(const uint8_t* base, uint64_t at, std::array<float, N>& values) {
    if (!Read(base, at, values)) return false;
    for (auto value : values) if (!std::isfinite(value)) return false;
    return true;
}
bool Bodies(const uint8_t* base, const Rig& rig, std::vector<uint32_t>& bodies, std::vector<BodyPose>* poses = nullptr) {
    for (unsigned i = 0; i < rig.count; ++i) {
        uint32_t body = 0, motion = 0, vt = 0, transform = 0, linear = 0, angular = 0;
        if (!Read(base, uint64_t(rig.bodies) + i * 4, body) || !Read(base, uint64_t(body) + 0x3C, motion) ||
            !Read(base, motion, vt) || !Read(base, uint64_t(vt) + 0x4C, transform) ||
            !Read(base, uint64_t(vt) + 0x50, linear) || !Read(base, uint64_t(vt) + 0x54, angular) ||
            !transform || !linear || !angular) return false;
        bodies.push_back(body);
        if (poses) {
            BodyPose pose;
            if (!Floats(base, uint64_t(motion) + 0x80, pose.transform) ||
                !Floats(base, uint64_t(motion) + 0x40, pose.linear) ||
                !Floats(base, uint64_t(motion) + 0x50, pose.angular)) return false;
            poses->push_back(pose);
        }
    }
    return true;
}
uint32_t DeadPlayer(const uint8_t* base, uint32_t respawner) {
    uint32_t type = 0, state = 0, ordinal = 2, game = 0, players = 0, local = 0, mode = 1, records = 0, actor = 0;
    uint16_t count = 0;
    if (!Read(base, respawner, type) || type != 0x42576C ||
        !Read(base, uint64_t(respawner) + 0x34, state) || state != 1 ||
        !Read(base, uint64_t(respawner) + 8, ordinal) || ordinal > 1 ||
        !Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game) + 0x44, players) || players != 2 ||
        !Read(base, uint64_t(game) + 0x4C, local) || local != 2 ||
        !Read(base, uint64_t(game) + 0xEC, mode) || mode ||
        !Read(base, uint64_t(game) + 0x50, count) || count < 2 || count > 64 ||
        !Read(base, uint64_t(game) + 0x54, records) || !Span(base, records, count * 0x130)) return 0;
    unsigned seen = 0;
    for (unsigned i = 0; i < count; ++i) {
        const auto record = records + i * 0x130; uint32_t index = 2;
        Read(base, record + 0x10C, index); if (index > 1) continue;
        if (seen & (1u << index)) return 0;
        seen |= 1u << index; if (index == ordinal) Read(base, record + 0x118, actor);
    }
    uint32_t flags = 0;
    return seen == 3 && actor && Read(base, uint64_t(actor) + 0x90, flags) && (flags & 2) &&
        Component(base, actor, 0x4227A4) ? actor : 0;
}
bool Prop(const uint8_t* base, uint32_t actor, uint32_t component) {
    std::string name; uint16_t count = 0;
    return component && Read(base, uint64_t(actor) + 0x60, count) && count == 3 &&
        Text(base, uint64_t(actor) + 0x50, name) && name.starts_with("Corpse_") && Playable(name.substr(7)) &&
        Component(base, actor, 0x41D378) == component && !Component(base, actor, 0x4227A4) &&
        !Component(base, actor, 0x41F878) && !Component(base, actor, 0x41F29C);
}
void Remove(Scratch& s, uint32_t actor) { s.Invoke(0x215932, s.Invoke(0x12731, 0), {actor}); }
bool Clone(X86Context& ctx, uint8_t* base, uint32_t actor, uint32_t& corpse, unsigned& count, unsigned& stage) {
    stage = 1;
    std::string name, model; Rig old;
    const auto animation = Component(base, actor, 0x41D258);
    const auto render = Component(base, actor, 0x41E25C);
    uint32_t zone = 0, world = 0;
    std::array<float, 16> placement;
    if (!animation || !render || !Text(base, uint64_t(render) + 0x18, model) || model.empty() ||
        !Text(base, uint64_t(actor) + 0x50, name) || !Playable(name) ||
        !Read(base, uint64_t(actor) + 0x68, zone) || !Read(base, uint64_t(actor) + 0x6C, world) ||
        !Floats(base, uint64_t(actor) + 0x10, placement) || !GetRig(base, actor, animation, 0x90, old)) return false;
    std::vector<uint32_t> old_bodies; std::vector<BodyPose> poses;
    if (!Bodies(base, old, old_bodies, old.active ? &poses : nullptr)) return false;
    Scratch s(ctx, base);
    const auto bones = s.Invoke(0x21A531, old.skeleton);
    if (bones != 22 && bones != 51) return false;
    stage = 2;
    name = "Corpse_" + name;
    std::memcpy(base + s.at + 0x20, name.c_str(), name.size() + 1);
    s.Invoke(0x138FA, s.at, {s.at + 0x20});
    corpse = s.Invoke(0x2168A4, 0, {s.at, zone, world, 1, 1, s.at + 4, 1});
    s.Invoke(0x11C1A, s.at);
    if (!corpse) return false;
    stage = 3;
    const auto prop = Component(base, corpse, 0x41D378); Rig current;
    bool ok = Prop(base, corpse, prop) && GetRig(base, corpse, prop, 0x1C0, current) && !current.active &&
        current.skeleton == prop + 0x30 && current.skeleton != old.skeleton && current.count == old.count &&
        s.Invoke(0x21A531, current.skeleton) == bones;
    const auto new_render = Component(base, corpse, 0x41E3E0);
    uint32_t old_map = 0, new_map = 0; std::string old_file, new_file, new_model;
    ok = ok && new_render && Text(base, uint64_t(new_render) + 0x18, new_model) && model == new_model &&
        Text(base, old.impl + 0x128, old_file) && Text(base, current.impl + 0x128, new_file) && old_file == new_file &&
        Read(base, old.impl + 0xC, old_map) && Read(base, current.impl + 0xC, new_map) &&
        !std::memcmp(base + old_map, base + new_map, old.count * 4);
    std::vector<uint32_t> bodies;
    ok = ok && Bodies(base, current, bodies);
    if (!ok) { Remove(s, corpse); return false; }
    std::memcpy(base + s.at + 0x100, placement.data(), sizeof(placement));
    s.Invoke(0x216244, corpse, {s.at + 0x100});
    // Activation copies the old render pose into NEW owned body/matrix arrays.
    // Restore its own skeleton before native synchronization writes local poses.
    stage = 4;
    {
        struct PoseSource {
            uint8_t* base; uint32_t impl, own;
            ~PoseSource() { Put(base, impl, own); }
        } restore{base, current.impl, current.skeleton};
        Put(base, current.impl, old.skeleton);
        s.Invoke(0x6F86E, current.wrapper, {0});
    }
    uint8_t active = 0;
    if (!Read(base, current.impl + 0xC1, active) || !active) { Remove(s, corpse); return false; }
    for (unsigned i = 0; i < poses.size(); ++i) {
        uint32_t motion = 0, vt = 0, linear = 0, angular = 0;
        Read(base, uint64_t(bodies[i]) + 0x3C, motion); Read(base, motion, vt);
        Read(base, uint64_t(vt) + 0x50, linear); Read(base, uint64_t(vt) + 0x54, angular);
        std::memcpy(base + s.at + 0x100, poses[i].transform.data(), 64);
        std::memcpy(base + s.at + 0x140, poses[i].linear.data(), 16);
        std::memcpy(base + s.at + 0x150, poses[i].angular.data(), 16);
        s.Invoke(0x6CD18, bodies[i], {s.at + 0x100});
        s.Invoke(linear, motion, {s.at + 0x140}); s.Invoke(angular, motion, {s.at + 0x150});
    }
    s.Invoke(0x6DBDA, current.impl);
    count = current.count; stage = 0; return true;
}
} // namespace

// Exact timed co-op replacement only: remove all original player ownership as
// usual. The retained actor has native prop physics and no gameplay components.
X86_FUNC(sub_000CBA27) {
    uint32_t caller = 0;
    if (darkwatch::view::Snapshot().forever_ragdolls && Stack(ctx, base) &&
        Read(base, ctx.esp, caller) && caller == 0xCBCB1) {
        if (const auto actor = DeadPlayer(base, ctx.ecx)) {
            uint32_t corpse = 0; unsigned bodies = 0, stage = 0;
            const bool ok = Clone(ctx, base, actor, corpse, bodies, stage);
#ifndef NDEBUG
            std::string name; Text(base, uint64_t(actor) + 0x50, name);
            LOGI("Co-op corpse old=%08X new=%08X template=%s bodies=%u retained=%u stage=%u",
                 actor, corpse, name.c_str(), bodies, unsigned(ok), stage);
#else
            (void)ok;
#endif
        }
    }
    __imp__sub_000CBA27(ctx, base);
}

X86_FUNC(sub_0006C5A5) {
    const auto component = ctx.ecx;
    uint32_t actor = 0; Rig rig;
    if (!darkwatch::view::Snapshot().forever_ragdolls && Stack(ctx, base) &&
        Read(base, uint64_t(component) + 0xC, actor) && Prop(base, actor, component) &&
        GetRig(base, actor, component, 0x1C0, rig) && rig.active) {
        // Queue (do not drain) native removal before dispatch; never inspect a
        // component after its original update may have emitted removal events.
        Scratch s(ctx, base); s.Invoke(0x6EE59, rig.wrapper); Remove(s, actor);
    }
    __imp__sub_0006C5A5(ctx, base);
}
