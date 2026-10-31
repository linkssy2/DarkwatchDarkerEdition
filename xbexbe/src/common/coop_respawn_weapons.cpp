#include "coop_respawn_weapons.h"
#include "controls.h"
#include "core/log.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cstring>
#include <string>
#include <vector>

// The original cooperative respawner destroys the old player and creates a
// default-equipped one. Preserve only on-foot guns for Carry All, using the
// original format-3 weapon serializer; clothes, runes and scripted loadouts keep
// their normal spawn/restore paths. No guest actor references survive in bytes.
X86_EXTERN_FUNC(__imp__sub_000C32AD);
X86_EXTERN_FUNC(__imp__sub_000CBD66);
X86_EXTERN_FUNC(__imp__sub_000967C6);
X86_EXTERN_FUNC(__imp__sub_000C29BF);
X86_EXTERN_FUNC(__imp__sub_000FA277);

namespace {
constexpr uint32_t capacity = 0x10000;
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
    for (unsigned i = 0; i < 64; ++i) {
        char c = 0; if (!Read(base, uint64_t(p) + 2 + i, c)) return false;
        if (!c) return true; value += c;
    }
    return false;
}
unsigned Identity(const std::string& name) {
    constexpr const char* names[]{"BasicPistol", "Revolver", "DoublePistol", "Crossbow",
        "RocketLauncher", "Rifle", "Shotgun", "SniperRifle"};
    for (unsigned i = 0; i < std::size(names); ++i) if (name == names[i]) return i + 1;
    return 0;
}
bool Component(const uint8_t* base, uint32_t actor, uint32_t type, uint32_t& out) {
    uint16_t n = 0; uint32_t list = 0; out = 0;
    if (!Read(base, uint64_t(actor) + 0x60, n) || !n || n > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, n * 8)) return false;
    for (unsigned i = 0; i < n; ++i) {
        uint32_t c = 0, v = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, c) || !Read(base, c, v)) return false;
        if (v != type) continue;
        if (out || !Read(base, uint64_t(c) + 0xC, owner) || owner != actor) return false;
        out = c;
    }
    return out != 0;
}
struct Player { uint32_t game = 0, record = 0, actor = 0, inventory = 0, slots = 0; uint16_t count = 0; unsigned ordinal = 2; };
bool Resolve(const uint8_t* base, unsigned ordinal, Player& p) {
    uint32_t players = 0, local = 0, mode = 1, records = 0, pc = 0; uint16_t n = 0;
    if (ordinal > 1 || !Read(base, 0x4AC9A0, p.game) || !p.game ||
        !Read(base, uint64_t(p.game) + 0x44, players) || players != 2 ||
        !Read(base, uint64_t(p.game) + 0x4C, local) || local != 2 ||
        !Read(base, uint64_t(p.game) + 0xEC, mode) || mode ||
        !Read(base, uint64_t(p.game) + 0x50, n) || n < 2 || n > 64 ||
        !Read(base, uint64_t(p.game) + 0x54, records) || !Span(base, records, n * 0x130)) return false;
    unsigned seen = 0;
    for (unsigned i = 0; i < n; ++i) {
        const auto r = records + i * 0x130; uint32_t index = 2;
        Read(base, r + 0x10C, index); if (index > 1) continue;
        if (seen & (1u << index)) return false;
        seen |= 1u << index; if (index == ordinal) p.record = r;
    }
    p.ordinal = ordinal;
    return seen == 3 && p.record && Read(base, p.record + 0x118, p.actor) && p.actor &&
        Component(base, p.actor, 0x4227A4, pc) && Component(base, p.actor, 0x41F29C, p.inventory) &&
        Read(base, uint64_t(p.inventory) + 0x88, p.count) && p.count && p.count <= 64 &&
        Read(base, uint64_t(p.inventory) + 0x8C, p.slots) && Span(base, p.slots, p.count * 4);
}
struct Weapon { uint32_t actor = 0, slot_type = 0; unsigned slot_index = 0, identity = 0; std::string slot_name; };
bool Weapons(const uint8_t* base, const Player& p, std::vector<Weapon>& out) {
    unsigned identities = 0;
    for (unsigned i = 0; i < p.count; ++i) {
        uint32_t slot = 0, type = 0, owner = 0; std::string name;
        if (!Read(base, uint64_t(p.slots) + i * 4, slot) || !Read(base, slot, type)) return false;
        if (type != 0x41F570 && type != 0x41F308 && type != 0x41F178) continue;
        if (!Read(base, uint64_t(slot) + 8, owner) || owner != p.inventory) return false;
        if (!Text(base, uint64_t(slot) + 4, name)) return false;
        uint16_t n = 1; uint32_t entries = slot + 0xC;
        if (type == 0x41F178 && (!Read(base, uint64_t(slot) + 0xC, n) || n > 64 ||
            !Read(base, uint64_t(slot) + 0x10, entries) || (n && !Span(base, entries, n * 16)))) return false;
        for (unsigned j = 0; j < n; ++j) {
            uint32_t actor = 0; std::string weapon;
            if (!Read(base, uint64_t(entries) + j * 16, actor)) return false;
            if (!actor) continue;
            if (!Text(base, uint64_t(actor) + 0x50, weapon)) return false;
            // Native mounted and scripted stash inventories must retain their own rules.
            if (weapon == "HorseRevolver" || (Identity(weapon) && name == "stash")) return false;
            const auto identity = Identity(weapon); if (!identity) continue;
            uint32_t item = 0, owner = 0;
            for (const auto v : {0x418390u, 0x417E90u, 0x417F78u, 0x418098u, 0x418150u, 0x418208u}) {
                uint32_t candidate = 0; if (Component(base, actor, v, candidate)) { if (item) return false; item = candidate; }
            }
            std::string item_name;
            if (!item || !Read(base, uint64_t(item) + 0x58, owner) || owner != p.actor ||
                !Text(base, uint64_t(item) + 0x24, item_name) || item_name != weapon ||
                (identities & (1u << identity))) return false;
            identities |= 1u << identity; out.push_back({actor, type, i, identity, name});
        }
    }
    return !out.empty() && out.size() <= 8;
}
struct Snapshot { const uint8_t* base = nullptr; Player player; uint32_t respawner = 0; std::vector<Weapon> weapons; std::vector<uint8_t> bytes; };
std::array<Snapshot, 2> pending;
thread_local Snapshot* collecting = nullptr;
thread_local Snapshot* restoring = nullptr;
bool Stack(const X86Context& ctx, const uint8_t* base) {
    return base == kernel::g_base && ctx.esp >= 0x8000 && Span(base, uint64_t(ctx.esp) - 0x8000, 0x8018);
}
struct Scratch {
    X86Context call; uint8_t* base; uint32_t at; std::array<uint8_t, 0x100> saved;
    Scratch(const X86Context& ctx, uint8_t* b) : call(ctx), base(b), at(ctx.esp - 0x200) {
        std::memcpy(saved.data(), base + at, saved.size()); std::memset(base + at, 0, saved.size()); call.esp = at - 0x20;
    }
    ~Scratch() { std::memcpy(base + at, saved.data(), saved.size()); }
    uint32_t Invoke(uint32_t fn, uint32_t object, std::initializer_list<uint32_t> args = {}) {
        call.ecx = object; return kernel::CallGuest(call, fn, args);
    }
};
bool Stream(Scratch& s, bool writing, const std::vector<uint8_t>& input, uint32_t& buffer, uint32_t& data) {
    s.Invoke(0xFB89D, 0, {s.at, capacity}); uint32_t type = 0, allocated = 0;
    Read(s.base, s.at, buffer);
    if (!buffer) return false;
    if (!Read(s.base, buffer, type) || type != 0x42C860 || !Read(s.base, uint64_t(buffer) + 8, allocated) || allocated != capacity ||
        !Read(s.base, uint64_t(buffer) + 0x10, data) || !Span(s.base, data, capacity)) {
        s.Invoke(0x2172F1, buffer); return false;
    }
    if (!writing) { std::memcpy(s.base + data, input.data(), input.size()); Put(s.base, buffer + 0xC, uint32_t(input.size())); }
    // The native constructor consumes the buffer reference; its destructor releases it.
    s.Invoke(writing ? 0xFC3E9 : 0xFC3A6, s.at + 0x20, {buffer});
    s.base[s.at + 0x34] = 1;
    return true;
}
bool Capture(X86Context& ctx, uint8_t* base, Snapshot& snap) {
    if (!Weapons(base, snap.player, snap.weapons)) return false;
    Scratch s(ctx, base); uint32_t buffer = 0, data = 0;
    if (!Stream(s, true, {}, buffer, data)) return false;
    bool ok = true;
    for (const auto& weapon : snap.weapons) if (!(s.Invoke(0x98DE7, 0, {s.at + 0x20, weapon.actor}) & 0xFF)) { ok = false; break; }
    uint32_t size = 0, position = 0;
    ok = ok && base[s.at + 0x34] && Read(base, uint64_t(buffer) + 0xC, size) && size && size <= capacity &&
        Read(base, s.at + 0x2C, position) && position == size;
    if (ok) snap.bytes.assign(base + data, base + data + size);
    s.Invoke(0xC2148, s.at + 0x20); return ok;
}
bool Restore(X86Context& ctx, uint8_t* base, Snapshot& snap, const Player& player) {
    if (snap.bytes.empty() || snap.bytes.size() > capacity || snap.weapons.empty() || snap.weapons.size() > 8) return false;
    std::array<uint32_t, 8> slots{}, actors{}, items{};
    for (unsigned i = 0; i < snap.weapons.size(); ++i) {
        const auto& old = snap.weapons[i]; uint32_t type = 0, owner = 0; std::string name;
        if (old.slot_index >= player.count || !Read(base, uint64_t(player.slots) + old.slot_index * 4, slots[i]) ||
            !Read(base, slots[i], type) || type != old.slot_type ||
            !Read(base, uint64_t(slots[i]) + 8, owner) || owner != player.inventory ||
            !Text(base, uint64_t(slots[i]) + 4, name) || name != old.slot_name) return false;
    }
    std::vector<Weapon> defaults;
    if (!Weapons(base, player, defaults)) return false;
    Scratch s(ctx, base); uint32_t buffer = 0, data = 0;
    if (!Stream(s, false, snap.bytes, buffer, data)) return false;
    bool ok = true;
    for (unsigned i = 0; i < snap.weapons.size(); ++i) {
        actors[i] = s.Invoke(0x98C33, 0, {player.actor, s.at + 0x20});
        std::string name; uint32_t v = 0;
        if (!actors[i] || !Text(base, uint64_t(actors[i]) + 0x50, name) || Identity(name) != snap.weapons[i].identity) { ok = false; break; }
        for (const auto type : {0x418390u, 0x417E90u, 0x417F78u, 0x418098u, 0x418150u, 0x418208u}) {
            uint32_t item = 0; if (Component(base, actors[i], type, item)) { if (items[i]) { ok = false; break; } items[i] = item; }
        }
        if (!ok || !items[i] || !Read(base, items[i], v) || !base[s.at + 0x34]) { ok = false; break; }
    }
    uint32_t consumed = 0;
    ok = ok && Read(base, s.at + 0x2C, consumed) && consumed == snap.bytes.size() && base[s.at + 0x34];
    s.Invoke(0xC2148, s.at + 0x20);
    if (!ok) {
        const auto manager = s.Invoke(0x12731, 0);
        for (auto actor : actors) if (actor) s.Invoke(0x215932, manager, {actor});
        return false;
    }
    // Validate/decode the complete native payload before removing any default gun.
    for (const auto& weapon : defaults) {
        uint32_t name = 0; Read(base, uint64_t(weapon.actor) + 0x50, name);
        Put(base, s.at + 0x60, 0x41E948); Put(base, s.at + 0x64, 0x192); Put(base, s.at + 0x68, name + 2);
        s.Invoke(0x96003, player.inventory, {s.at + 0x60});
    }
    for (unsigned i = 0; i < snap.weapons.size(); ++i) {
        s.Invoke(0x19726, s.at + 0x60, {items[i]}); Put(base, s.at + 0x6C, 0);
        s.Invoke(snap.weapons[i].slot_type == 0x41F178 ? 0x93F6F : 0x98B59, slots[i], {s.at + 0x60, actors[i]});
        s.Invoke(0x196B4, s.at + 0x60); s.Invoke(0x96EFC, player.inventory, {slots[i]});
    }
    s.Invoke(0x953B6, player.inventory); return true;
}
} // namespace

void DarkwatchResetRespawnWeapons() { pending = {}; }

X86_FUNC(sub_000C32AD) {
    Snapshot snapshot; uint32_t caller = 0, actor = 0;
    if (!collecting && darkwatch::GetCarryAllWeapons() && Stack(ctx, base) &&
        Read(base, ctx.esp, caller) && caller == 0xA93C2 && Read(base, uint64_t(ctx.esp) + 4, actor)) {
        for (unsigned i = 0; i < pending.size(); ++i) {
            Player p;
            if (!Resolve(base, i, p) || p.game != ctx.ecx || p.actor != actor) continue;
            pending[i] = {}; snapshot.base = base; snapshot.player = p;
            if (!Capture(ctx, base, snapshot)) snapshot = {};
            break;
        }
    }
    auto* previous = collecting; collecting = snapshot.bytes.empty() ? nullptr : &snapshot;
    __imp__sub_000C32AD(ctx, base); collecting = previous;
    if (snapshot.respawner) pending[snapshot.player.ordinal] = std::move(snapshot);
}
X86_FUNC(sub_000CBD66) {
    const uint32_t object = ctx.ecx; uint32_t caller = 0, ordinal = 2;
    const bool matched = collecting && Read(base, ctx.esp, caller) && caller == 0xCBF4F &&
        Read(base, uint64_t(ctx.esp) + 4, ordinal) && ordinal == collecting->player.ordinal;
    __imp__sub_000CBD66(ctx, base);
    uint32_t type = 0;
    if (matched && ctx.eax == object && Read(base, object, type) && type == 0x42576C) collecting->respawner = object;
}
X86_FUNC(sub_000967C6) {
    uint32_t caller = 0;
    if (collecting && collecting->respawner && collecting->base == base && ctx.ecx == collecting->player.inventory &&
        Read(base, ctx.esp, caller) && caller == 0xC3353) { ctx.esp += 4; return; }
    __imp__sub_000967C6(ctx, base);
}
X86_FUNC(sub_000C29BF) {
    uint32_t caller = 0, ordinal = 2, type = 0, native_ordinal = 2;
    Snapshot snapshot;
    if (!restoring && Stack(ctx, base) && Read(base, ctx.esp, caller) && caller == 0xCBCD5 &&
        Read(base, uint64_t(ctx.esp) + 4, ordinal) && ordinal < pending.size() &&
        Read(base, ctx.esi, type) && type == 0x42576C && Read(base, uint64_t(ctx.esi) + 8, native_ordinal) && native_ordinal == ordinal) {
        auto& saved = pending[ordinal];
        if (saved.base == base && saved.player.game == ctx.ecx && saved.respawner == ctx.esi)
            snapshot = std::move(saved);
        saved = {};
    }
    auto* previous = restoring; restoring = snapshot.bytes.empty() ? nullptr : &snapshot;
    __imp__sub_000C29BF(ctx, base); restoring = previous;
    // Failed native creation can be retried by the same native respawner only.
    if (!ctx.eax && !snapshot.bytes.empty()) pending[snapshot.player.ordinal] = std::move(snapshot);
}
X86_FUNC(sub_000FA277) {
    uint32_t caller = 0, ordinal = 2;
    const bool matched = restoring && Read(base, ctx.esp, caller) && caller == 0xC29DA &&
        Read(base, uint64_t(ctx.esp) + 4, ordinal) && ordinal == restoring->player.ordinal;
    __imp__sub_000FA277(ctx, base);
    if (!matched || !ctx.eax || !Stack(ctx, base)) return;
    Player player;
    if (!(Resolve(base, ordinal, player) && player.game == restoring->player.game && player.record == restoring->player.record &&
        player.actor == ctx.eax && Restore(ctx, base, *restoring, player)))
        LOGW("Co-op player %u weapon restore failed; retaining native respawn loadout", ordinal + 1);
    restoring->bytes.clear();
}
