#include "carry_all_weapons.h"
#include "controls.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <chrono>
#include <cstring>
#include <mutex>

X86_EXTERN_FUNC(__imp__sub_00094E82);
X86_EXTERN_FUNC(__imp__sub_00093D7C);
X86_EXTERN_FUNC(__imp__sub_000973A2);
X86_EXTERN_FUNC(__imp__sub_000957A9);
X86_EXTERN_FUNC(__imp__sub_0009A801);
X86_EXTERN_FUNC(__imp__sub_00099625);
X86_EXTERN_FUNC(__imp__sub_00097941);
X86_EXTERN_FUNC(__imp__sub_00095F64);
X86_EXTERN_FUNC(__imp__sub_0009711D);
X86_EXTERN_FUNC(__imp__sub_00096003);
X86_EXTERN_FUNC(__imp__sub_000953B6);
X86_EXTERN_FUNC(__imp__sub_00012731);
X86_EXTERN_FUNC(__imp__sub_00215932);
X86_EXTERN_FUNC(__imp__sub_000195C7);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(value)); return true;
}
void Write(uint8_t* base, uint32_t at, uint32_t value) { std::memcpy(base + at, &value, 4); }
bool Name(const uint8_t* base, uint64_t at, const char* name) {
    uint32_t text = 0; const auto size = std::strlen(name) + 1;
    return Read(base, at, text) && text && Span(base, uint64_t(text) + 2, size) &&
        !std::memcmp(base + uint64_t(text) + 2, name, size);
}
unsigned Identity(const uint8_t* base, uint64_t at) {
    constexpr const char* names[]{"BasicPistol", "Revolver", "DoublePistol", "Crossbow",
        "RocketLauncher", "Rifle", "Shotgun", "SniperRifle", "Scepter"};
    for (unsigned i = 0; i < std::size(names); ++i) if (Name(base, at, names[i])) return i + 1;
    return 0;
}
bool Component(const uint8_t* base, uint32_t actor, uint32_t type, uint32_t& result) {
    uint16_t count = 0; uint32_t list = 0;
    if (!Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, count * 8)) return false;
    result = 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t item = 0, vtable = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, item) || !Read(base, item, vtable)) return false;
        if (vtable != type) continue;
        if (result || !Read(base, uint64_t(item) + 0xC, owner) || owner != actor) return false;
        result = item;
    }
    return result != 0;
}
struct Player { uint32_t actor = 0, inventory = 0, profile = 0, primary = 0, slots = 0, input_port = 0; uint16_t count = 0; };
uint32_t PlayerRecord(const uint8_t* base, unsigned ordinal) {
    uint32_t game = 0, players = 0, records = 0; uint16_t count = 0;
    if (ordinal >= 2 || !Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game) + 0x44, players) || !players || players > 2 || ordinal >= players ||
        !Read(base, uint64_t(game) + 0x50, count) || count < players || count > 64 ||
        !Read(base, uint64_t(game) + 0x54, records) || !Span(base, records, count * 0x130)) return 0;
    unsigned seen = 0; uint32_t found = 0;
    for (unsigned i = 0; i < count; ++i) {
        const uint32_t record = records + i * 0x130; uint32_t index = 0;
        Read(base, record + 0x10C, index); if (index >= players) continue;
        if (seen & (1u << index)) return 0;
        seen |= 1u << index; if (index == ordinal) found = record;
    }
    return seen == ((1u << players) - 1) ? found : 0;
}
bool Resolve(const uint8_t* base, unsigned ordinal, Player& out) {
    const auto found = PlayerRecord(base, ordinal);
    uint32_t pc = 0, categories = 0, category = 0, type = 0; uint16_t categories_count = 0;
    if (!found || !Read(base, found + 0x118, out.actor) || !out.actor ||
        !Component(base, out.actor, 0x4227A4, pc) || !Component(base, out.actor, 0x41F29C, out.inventory) ||
        !Read(base, uint64_t(out.inventory) + 0x88, out.count) || !out.count || out.count > 64 ||
        !Read(base, uint64_t(out.inventory) + 0x8C, out.slots) || !Span(base, out.slots, out.count * 4) ||
        !Read(base, uint64_t(out.inventory) + 0x78, categories_count) || !categories_count || categories_count > 4 ||
        !Read(base, uint64_t(out.inventory) + 0x7C, categories) || !Read(base, categories, category) || category >= out.count ||
        !Read(base, uint64_t(out.slots) + category * 4, out.primary) || !Read(base, out.primary, type) || type != 0x41F570 ||
        !Name(base, uint64_t(out.primary) + 4, "loc_RightHand")) return false;
    out.profile = found + 0x9C; return Read(base, found + 0x114, out.input_port);
}
int ResolveInput(const uint8_t* base, unsigned port, Player& out) {
    uint32_t game = 0, count = 0;
    if (port >= 2 || !Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game) + 0x44, count) || !count || count > 2) return -1;
    unsigned seen = 0; int ordinal = -1;
    for (unsigned i = 0; i < count; ++i) {
        const auto record = PlayerRecord(base, i);
        uint32_t input = 0, local_count = 0; uint8_t local = 0, online = 0;
        if (!record || !Read(base, record + 0x114, input) || !Read(base, record + 0x128, local)) return -1;
        // A remote player has no local device, including while their actor respawns.
        if (!local && input == ~0u && Read(base, game + 0xC, online) && online == 1 &&
            Read(base, game + 0x4C, local_count) && local_count == 1 && count == 2) continue;
        if (!local || input >= 2 || (seen & (1u << input))) return -1;
        seen |= 1u << input;
        if (input == port) ordinal = int(i);
    }
    return ordinal >= 0 && Resolve(base, unsigned(ordinal), out) ? ordinal : -1;
}
int Owner(const uint8_t* base, uint32_t inventory, Player& player) {
    for (unsigned i = 0; i < 2; ++i) { Player p; if (Resolve(base, i, p) && p.inventory == inventory) { player = p; return int(i); } }
    return -1;
}
bool Weapon(const uint8_t* base, uint32_t actor, const Player& player, uint32_t& item) {
    if (!actor || !Identity(base, uint64_t(actor) + 0x50)) return false;
    constexpr uint32_t types[]{0x418390, 0x417E90, 0x417F78, 0x418098, 0x418150, 0x418208};
    item = 0;
    for (const auto type : types) { uint32_t candidate = 0; if (Component(base, actor, type, candidate)) { if (item) return false; item = candidate; } }
    uint32_t owner = 0;
    return item && Read(base, uint64_t(item) + 0x58, owner) && owner == player.actor &&
        // Original inventory-name getter B3CDC returns component +24, not +70.
        Identity(base, uint64_t(item) + 0x24) == Identity(base, uint64_t(actor) + 0x50);
}
template<class F> bool Visit(const uint8_t* base, const Player& player, F visit) {
    for (unsigned i = 0; i < player.count; ++i) {
        uint32_t slot = 0, type = 0;
        if (!Read(base, uint64_t(player.slots) + i * 4, slot) || !Read(base, slot, type)) return false;
        // Native cycling excludes the dual pistol's child; only its master is a carried gun.
        if (Name(base, uint64_t(slot) + 4, "loc_LeftHandDualWield")) continue;
        if (type == 0x41F570 || type == 0x41F308) {
            uint32_t actor = 0; if (!Read(base, uint64_t(slot) + 0xC, actor) || !visit(slot, actor)) return false;
        } else if (type == 0x41F178) {
            uint16_t count = 0; uint32_t entries = 0;
            if (!Read(base, uint64_t(slot) + 0xC, count) || count > 64 ||
                !Read(base, uint64_t(slot) + 0x10, entries) || (count && !Span(base, entries, count * 16))) return false;
            for (unsigned j = 0; j < count; ++j) {
                uint32_t actor = 0; if (!Read(base, uint64_t(entries) + j * 16, actor) || !visit(slot, actor)) return false;
            }
        }
    }
    return true;
}
using Clock = std::chrono::steady_clock;
struct Request { const uint8_t* base = nullptr; uint32_t actor = 0; int direction = 0; Clock::time_point expires{}; unsigned input_port = 2; bool accepted = false; };
std::array<Request, 2> requests;
std::mutex request_mutex;
struct LimitedPair {
    const uint8_t* base = nullptr; uint32_t actor = 0, inventory = 0;
    std::array<unsigned, 2> identities{};
};
std::array<LimitedPair, 2> limited_pairs;
std::mutex pair_mutex;
thread_local uint32_t cycling_inventory = 0;
struct CycleScope {
    uint32_t previous = cycling_inventory;
    ~CycleScope() { cycling_inventory = previous; }
};
unsigned LimitedNormalWeapons(const uint8_t* base, unsigned ordinal, const Player& player,
                             bool carry_all, bool keep_starter) {
    std::lock_guard lock(pair_mutex);
    auto& saved = limited_pairs[ordinal];
    if (carry_all) { saved = {}; return 0; }
    const bool same_owner = saved.base == base && saved.actor == player.actor && saved.inventory == player.inventory;
    bool pocket_empty = false;
    unsigned present = 0; std::array<unsigned, 2> pair{};
    auto add = [&](unsigned id) {
        if (id < 2 || pair[0] == id || pair[1] == id) return;
        if (!pair[0]) pair[0] = id; else if (!pair[1]) pair[1] = id;
    };
    if (!Visit(base, player, [&](uint32_t slot, uint32_t actor) {
        if (Name(base, uint64_t(slot) + 4, "pocket")) pocket_empty = actor == 0;
        uint32_t item = 0; if (!Weapon(base, actor, player, item)) return true;
        const auto id = Identity(base, uint64_t(actor) + 0x50);
        present |= 1u << id;
        if (slot == player.primary || Name(base, uint64_t(slot) + 4, "pocket")) add(id);
        return true;
    })) { saved = {}; return 0; }
    // Equipping the retained starter temporarily stows a normal gun in bag.
    // Remember identities, never guest weapon pointers, so that pair stays usable.
    if (same_owner && keep_starter)
        for (const auto id : saved.identities) if (present & (1u << id)) add(id);
    // An old save may already have the starter equipped. Its pocket and first
    // normal bag gun establish the two normal slots on this fresh admission.
    unsigned first_bag = 0;
    if (!Visit(base, player, [&](uint32_t slot, uint32_t actor) {
        uint32_t item = 0;
        if (Name(base, uint64_t(slot) + 4, "bag") && Weapon(base, actor, player, item)) {
            const auto id = Identity(base, uint64_t(actor) + 0x50);
            if (id >= 2 && !first_bag) first_bag = id;
            if (keep_starter) add(id);
        }
        return true;
    })) { saved = {}; return 0; }
    // After removing the disabled starter, a later native switch may fill the
    // empty second slot from stored inventory. It still exposes at most two guns.
    if (!keep_starter) { saved = {}; return pocket_empty && first_bag ? 1u << first_bag : 0; }
    saved = {base, player.actor, player.inventory, pair};
    return (pair[0] ? 1u << pair[0] : 0) | (pair[1] ? 1u << pair[1] : 0);
}
bool Scratch(const X86Context& ctx, const uint8_t* base) {
    return ctx.esp >= 0x2000 && Span(base, uint64_t(ctx.esp) - 0x2000, 0x2000);
}
uint32_t Native(X86Context& ctx, uint8_t* base, void(*fn)(X86Context&, uint8_t*), uint32_t object,
                uint32_t a, uint32_t b = 0) {
    auto call = ctx; call.ecx = object; call.esp -= 16;
    uint32_t saved[3]; std::memcpy(saved, base + call.esp, sizeof(saved));
    Write(base, call.esp, 0); Write(base, call.esp + 4, a); Write(base, call.esp + 8, b);
    fn(call, base); std::memcpy(base + ctx.esp - 16, saved, sizeof(saved)); return call.eax;
}

// Retention is an inventory-event policy, not a frame-time inventory rewrite.
// The original opening pistol, mounted guns and intentional disarms keep their
// native paths. Only our added restores and the native Redeemer handoff change.
int RetentionOwner(const X86Context& ctx, const uint8_t* base, uint32_t inventory, Player& player) {
    if (darkwatch::GetKeepStartingRevolver() || base != kernel::g_base || !Scratch(ctx, base)) return -1;
    const int ordinal = Owner(base, inventory, player);
    uint8_t local = 0, disabled = 1; uint32_t busy = 1;
    if (ordinal < 0 || !Read(base, PlayerRecord(base, unsigned(ordinal)) + 0x128, local) || local != 1 ||
        player.input_port >= 2 || !Read(base, uint64_t(player.actor) + 0x5E, disabled) || disabled ||
        !Read(base, uint64_t(inventory) + 0x6C, busy) || busy) return -1;
    bool safe = true;
    if (!Visit(base, player, [&](uint32_t slot, uint32_t actor) {
        uint32_t owner = 0;
        if (!Read(base, uint64_t(slot) + 8, owner) || owner != inventory) return false;
        if (actor && (Name(base, uint64_t(actor) + 0x50, "HorseRevolver") ||
            (Identity(base, uint64_t(actor) + 0x50) && Name(base, uint64_t(slot) + 4, "stash")))) safe = false;
        return true;
    }) || !safe) return -1;
    return ordinal;
}
bool IncomingStarter(const uint8_t* base, uint32_t actor, const Player& player, uint32_t& item) {
    uint8_t disabled = 1; uint32_t owner = 0;
    if (!actor || !Name(base, uint64_t(actor) + 0x50, "BasicPistol") ||
        !Read(base, uint64_t(actor) + 0x5E, disabled) || disabled ||
        !Component(base, actor, 0x418390, item) || !Name(base, uint64_t(item) + 0x24, "BasicPistol") ||
        !Read(base, uint64_t(item) + 0x58, owner) || (owner && owner != player.actor)) return false;
    bool carried = false;
    return Visit(base, player, [&](uint32_t, uint32_t existing) { carried |= existing == actor; return true; }) && !carried;
}
void DiscardRestore(X86Context& ctx, uint8_t* base, uint32_t actor) {
    // This is the original 95F64 rejected-default path. 215932 queues a weak
    // actor reference for later destruction, so the current dispatch can finish.
    const auto manager = Native(ctx, base, __imp__sub_00012731, 0, actor);
    Native(ctx, base, __imp__sub_00215932, manager, actor);
}
void RemoveRetainedStarter(X86Context& ctx, uint8_t* base, uint32_t inventory) {
    Player player;
    if (RetentionOwner(ctx, base, inventory, player) < 0) return;
    uint32_t active = 0, active_item = 0, starter = 0, redeemer = 0;
    if (!Read(base, uint64_t(player.primary) + 0xC, active) || !Weapon(base, active, player, active_item) ||
        Identity(base, uint64_t(active) + 0x50) == 1) return;
    if (!Visit(base, player, [&](uint32_t, uint32_t actor) {
        const auto identity = Identity(base, uint64_t(actor) + 0x50);
        if (identity != 1 && identity != 2) return true;
        uint32_t item = 0;
        if (!Weapon(base, actor, player, item)) return false;
        auto& found = identity == 1 ? starter : redeemer;
        if (found) return false;
        found = actor; return true;
    }) || !starter || !redeemer) return;
    // Never remove an equipped/only gun or synthesize a replacement. Native
    // pickup/equip has already installed a usable weapon before this point.
    uint32_t name = 0;
    if (!Read(base, uint64_t(starter) + 0x50, name) || !Name(base, uint64_t(starter) + 0x50, "BasicPistol")) return;
    const auto message = ctx.esp - 0x100;
    std::array<uint8_t, 12> saved; std::memcpy(saved.data(), base + message, saved.size());
    Write(base, message, 0x41E948); Write(base, message + 4, 0x192); Write(base, message + 8, name + 2);
    auto call = ctx; call.esp = message - 0x20;
    Native(call, base, __imp__sub_00096003, inventory, message);
    Native(call, base, __imp__sub_000953B6, inventory, 0);
    std::memcpy(base + message, saved.data(), saved.size());
}
} // namespace

void DarkwatchResetWeaponChoices() {
    std::lock_guard lock(pair_mutex);
    limited_pairs = {};
}

int DarkwatchWeaponCycleAction(unsigned port) {
    const auto* base = kernel::g_base; Player player; uint32_t actor = 0, item = 0, busy = 0;
    if (ResolveInput(base, port, player) < 0 || !Read(base, uint64_t(player.inventory) + 0x6C, busy) || busy ||
        !Read(base, uint64_t(player.primary) + 0xC, actor) || !Weapon(base, actor, player, item)) return -1;
    if (Name(base, uint64_t(player.profile) + 0xC, "Chieftain")) return 11;
    for (const auto* preset : {"Default", "Lefty", "Hopalong", "Hoss"})
        if (Name(base, uint64_t(player.profile) + 0xC, preset)) return 1;
    return -1;
}
void DarkwatchQueueWeaponCycle(unsigned port, int direction) {
    if (port >= requests.size()) return;
    Player player; const auto* base = kernel::g_base;
    const int ordinal = direction ? ResolveInput(base, port, player) : -1;
    std::lock_guard<std::mutex> lock(request_mutex);
    // Cancel by originating port even if controllers were reassigned meanwhile.
    for (auto& request : requests) if (request.input_port == port) request = {};
    if (ordinal >= 0) requests[ordinal] = Request{base, player.actor, direction < 0 ? -1 : 1,
        Clock::now() + std::chrono::milliseconds(150), port};
}

X86_FUNC(sub_00097941) {
    Player player; const uint32_t inventory = ctx.ecx;
    const int ordinal = Owner(base, inventory, player);
    uint32_t message = 0, category = 1; Request before;
    if (ordinal >= 0 && Read(base, uint64_t(ctx.esp) + 4, message) &&
        Read(base, uint64_t(message) + 8, category) && category == 0) {
        std::lock_guard<std::mutex> lock(request_mutex); before = requests[ordinal];
        uint32_t busy = 0;
        if (before.accepted && Read(base, uint64_t(inventory) + 0x6C, busy) && !busy) {
            // A fresh command after a canceled lowering animation is unrelated.
            requests[ordinal] = {}; before = {};
        }
    }
    __imp__sub_00097941(ctx, base);
    if (!before.direction || before.accepted || before.base != base || before.actor != player.actor || before.input_port != player.input_port) return;
    uint32_t busy = 0; Read(base, uint64_t(inventory) + 0x6C, busy);
    std::lock_guard<std::mutex> lock(request_mutex); auto& request = requests[ordinal];
    if (request.base != before.base || request.actor != before.actor || request.expires != before.expires) return;
    // A blocked weapon/state must not reverse a later ordinary Swap press.
    // Only an accepted lower animation can outlive the synthetic input pulse.
    if (busy == 1 && Clock::now() < before.expires) {
        request.accepted = true; request.expires = Clock::now() + std::chrono::seconds(2);
    } else request = {};
}

X86_FUNC(sub_00094E82) {
    const uint32_t inventory = ctx.ecx, stack = ctx.esp;
    uint32_t message = 0, excluded = 0, replaced = 0, refill = 0;
    const bool args = Read(base, uint64_t(stack) + 4, message) && Read(base, uint64_t(stack) + 12, excluded) &&
        Read(base, uint64_t(stack) + 16, replaced) && Span(base, replaced, 1) &&
        Read(base, uint64_t(stack) + 20, refill) && Span(base, refill, 1);
    __imp__sub_00094E82(ctx, base);
    Player player;
    // Free pockets and native duplicate/ammo handling keep their original priority.
    if (!args || (ctx.eax && !base[replaced]) || base[refill] ||
        (!darkwatch::GetCarryAllWeapons() && cycling_inventory != inventory) ||
        Owner(base, inventory, player) < 0 || !Scratch(ctx, base)) return;
    const auto identity = Identity(base, uint64_t(message) + 0x18);
    if (!identity) return;
    bool duplicate = false;
    if (!Visit(base, player, [&](uint32_t, uint32_t actor) { duplicate |= actor && Identity(base, uint64_t(actor) + 0x50) == identity; return true; }) || duplicate) return;
    uint32_t bag = 0;
    for (unsigned i = 0; i < player.count; ++i) {
        uint32_t slot = 0, type = 0;
        if (!Read(base, uint64_t(player.slots) + i * 4, slot) || !Read(base, slot, type)) return;
        if (type == 0x41F178 && slot != excluded && Name(base, uint64_t(slot) + 4, "bag")) { if (bag) return; bag = slot; }
    }
    // The original bag owns insertion, removal, weak references and serialization.
    if (!bag || Native(ctx, base, __imp__sub_00093D7C, bag, message) != 0) return;
    base[replaced] = base[refill] = 0; ctx.eax = bag;
}
X86_FUNC(sub_000973A2) {
    const uint32_t inventory = ctx.ecx;
    uint32_t category = 0, explicit_actor = 0; Player player;
    CycleScope scope;
    if (Read(base, uint64_t(ctx.esp) + 4, category) && category == 0 &&
        Read(base, uint64_t(ctx.esp) + 12, explicit_actor) && !explicit_actor && Owner(base, ctx.ecx, player) >= 0)
        cycling_inventory = ctx.ecx;
    // Stowing during a swap must preserve collected guns, including parked ones.
    __imp__sub_000973A2(ctx, base);
    if (!category) RemoveRetainedStarter(ctx, base, inventory);
}

X86_FUNC(sub_00095F64) {
    uint32_t caller = 0, actor = 0, item = 0; Player player;
    // Native event5 grants the deferred default actors after the player record
    // is registered. Only six mod-added loadout rows force BasicPistol into bag.
    if (Read(base, ctx.esp, caller) && caller == 0x96C7F &&
        RetentionOwner(ctx, base, ctx.ecx, player) >= 0 && Read(base, uint64_t(ctx.esp) + 4, actor) &&
        IncomingStarter(base, actor, player, item) && Name(base, uint64_t(item) + 0x54, "bag")) {
        DiscardRestore(ctx, base, actor); ctx.esp += 8; return;
    }
    __imp__sub_00095F64(ctx, base);
}

X86_FUNC(sub_0009711D) {
    const uint32_t inventory = ctx.ecx;
    uint32_t message = 0, actor = 0, item = 0, mode = ~0u; Player player;
    const bool args = Read(base, uint64_t(ctx.esp) + 4, message) && Span(base, message, 0x1C) &&
        Read(base, uint64_t(ctx.esp) + 8, actor) && Read(base, uint64_t(message) + 0xC, mode);
    const auto identity = args ? Identity(base, uint64_t(message) + 0x18) : 0;
    const int ordinal = args && mode <= 1 && identity == 1 ? RetentionOwner(ctx, base, inventory, player) : -1;
    if (ordinal >= 0 && IncomingStarter(base, actor, player, item) &&
        Name(base, uint64_t(actor) + 0x54, ordinal ? "CampaignBasicPistol_Player1" : "CampaignBasicPistol_Player0")) {
        // The four authored restore scripts do not wait for this optional gun.
        // Decline normally; do not pretend a pickup succeeded or touch other guns.
        base[message + 0xA] = 0;
        if (mode == 0) DiscardRestore(ctx, base, actor);
        ctx.esp += 16; return;
    }
    __imp__sub_0009711D(ctx, base);
    if (args && mode == 0 && identity > 1 && cycling_inventory != inventory &&
        Owner(base, inventory, player) >= 0 && Weapon(base, actor, player, item)) {
        // A real pickup establishes a new native active/pocket pair. Internal
        // stowing during cycling must not invalidate the retained-starter pair.
        bool carried = false;
        if (Visit(base, player, [&](uint32_t, uint32_t candidate) { carried |= candidate == actor; return true; }) && carried) {
            std::lock_guard lock(pair_mutex);
            for (auto& pair : limited_pairs) if (pair.base == base && pair.inventory == inventory) pair = {};
        }
    }
    if (args && mode == 0 && identity == 2) RemoveRetainedStarter(ctx, base, inventory);
}

X86_FUNC(sub_000195C7) {
    uint32_t message = 0, event = 0, actor = 0, receiver = 0, pickup = 0, item = 0;
    if (!darkwatch::GetKeepStartingRevolver() && Read(base, uint64_t(ctx.esp) + 4, message) &&
        Read(base, uint64_t(message) + 4, event) && event == 0x116 &&
        Read(base, uint64_t(message) + 8, receiver) && Read(base, uint64_t(ctx.ecx) + 0xC, actor) &&
        Component(base, actor, 0x4179E8, pickup) && pickup == ctx.ecx) {
        for (unsigned i = 0; i < 2; ++i) {
            Player player;
            if (!Resolve(base, i, player) || player.actor != receiver ||
                RetentionOwner(ctx, base, player.inventory, player) != int(i) ||
                !IncomingStarter(base, actor, player, item) ||
                !Name(base, uint64_t(actor) + 0x54, i ? "CampaignBasicPistol_Player1" : "CampaignBasicPistol_Player0")) continue;
            // Scripted Interact normally queries admission before committing.
            // Retire our optional actor here so declining its query cannot leave
            // a visible, unusable extra pistol behind at a re-arming station.
            DiscardRestore(ctx, base, actor); ctx.esp += 8; return;
        }
    }
    __imp__sub_000195C7(ctx, base);
}
X86_FUNC(sub_000957A9) {
    Player player; const int ordinal = Owner(base, ctx.ecx, player);
    uint32_t caller = 0, active = 0, storage_out = 0, actor_out = 0;
    bool previous = false;
    if (ordinal >= 0 && Read(base, ctx.esp, caller) && caller == 0x973EE &&
        Read(base, uint64_t(ctx.esp) + 4, active) && active == player.primary) {
        std::lock_guard<std::mutex> lock(request_mutex);
        const auto request = requests[ordinal]; requests[ordinal] = {};
        previous = request.base == base && request.actor == player.actor && request.input_port == player.input_port &&
            request.direction < 0 && Clock::now() < request.expires;
    }
    if (ordinal < 0 || active != player.primary || !Scratch(ctx, base) || !Read(base, uint64_t(ctx.esp) + 8, storage_out) || !Span(base, storage_out, 4) ||
        !Read(base, uint64_t(ctx.esp) + 12, actor_out) || !Span(base, actor_out, 4)) {
        __imp__sub_000957A9(ctx, base); return;
    }
    uint32_t current = 0, item = 0;
    if (!Read(base, uint64_t(active) + 0xC, current) || !Weapon(base, current, player, item)) { __imp__sub_000957A9(ctx, base); return; }
    const auto settings = darkwatch::ControlsSnapshot();
    bool redeemer = false, disarmed = false;
    if (!Visit(base, player, [&](uint32_t slot, uint32_t actor) {
        const auto identity = Identity(base, uint64_t(actor) + 0x50);
        if (actor && (Name(base, uint64_t(actor) + 0x50, "HorseRevolver") ||
            (identity && Name(base, uint64_t(slot) + 4, "stash")))) disarmed = true;
        uint32_t component = 0;
        if (identity == 2 && Weapon(base, actor, player, component)) redeemer = true;
        return true;
    }) || disarmed) { __imp__sub_000957A9(ctx, base); return; }
    const bool exclude_starter = !settings.keep_starting_revolver && redeemer;
    const bool limited = !settings.carry_all_weapons || exclude_starter;
    const auto normal_pair = LimitedNormalWeapons(base, unsigned(ordinal), player,
        settings.carry_all_weapons, settings.keep_starting_revolver);
    uint32_t best = 0, best_slot = 0, wrap = 0, wrap_slot = 0; unsigned candidates = 0;
    auto compare = [&](uint32_t a, uint32_t b) { return int32_t(Native(ctx, base, __imp__sub_0009A801, 0, a, b)); };
    const bool complete = Visit(base, player, [&](uint32_t slot, uint32_t actor) {
        uint32_t component = 0; uint8_t selectable = 0;
        if (!actor || actor == current || slot == active || !Weapon(base, actor, player, component)) return true;
        const auto identity = Identity(base, uint64_t(actor) + 0x50);
        if (exclude_starter && identity == 1) return true;
        // Existing saves keep their overflow inventory. With Carry All off it
        // stays parked; the independently retained starter is the only exception.
        if (!settings.carry_all_weapons && !Name(base, uint64_t(slot) + 4, "pocket") &&
            !(Name(base, uint64_t(slot) + 4, "bag") &&
              ((settings.keep_starting_revolver && identity == 1) || (normal_pair & (1u << identity))))) return true;
        if (!Read(base, uint64_t(component) + 0x38, selectable)) return false;
        if (!selectable || !(Native(ctx, base, __imp__sub_00099625, component, active + 4) & 0xFF)) return true;
        ++candidates;
        const auto before = [&](uint32_t a, uint32_t b) { return previous ? compare(a, b) > 0 : compare(a, b) < 0; };
        if (!wrap || before(actor, wrap)) { wrap = actor; wrap_slot = slot; }
        const int relative = compare(actor, current);
        if ((previous ? relative < 0 : relative > 0) && (!best || before(actor, best))) { best = actor; best_slot = slot; }
        return true;
    });
    // The original merge was authored for one pocket: a bag candidate can skip
    // that pocket when more guns exist. Order the extended primary set together.
    if (!complete || (!limited && !previous && candidates <= 1)) { __imp__sub_000957A9(ctx, base); return; }
    Write(base, storage_out, best ? best_slot : wrap_slot); Write(base, actor_out, best ? best : wrap);
    ctx.esp += 16;
}
