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
        "RocketLauncher", "Rifle", "Shotgun", "SniperRifle"};
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
bool Resolve(const uint8_t* base, unsigned ordinal, Player& out) {
    uint32_t game = 0, players = 0, records = 0; uint16_t count = 0;
    if (ordinal >= 2 || !Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game) + 0x44, players) || !players || players > 2 || ordinal >= players ||
        !Read(base, uint64_t(game) + 0x50, count) || count < players || count > 64 ||
        !Read(base, uint64_t(game) + 0x54, records) || !Span(base, records, count * 0x130)) return false;
    unsigned seen = 0; uint32_t found = 0;
    for (unsigned i = 0; i < count; ++i) {
        const uint32_t record = records + i * 0x130; uint32_t index = 0;
        Read(base, record + 0x10C, index); if (index >= players) continue;
        if (seen & (1u << index)) return false;
        seen |= 1u << index; if (index == ordinal) found = record;
    }
    uint32_t pc = 0, categories = 0, category = 0, type = 0; uint16_t categories_count = 0;
    if (!found || seen != ((1u << players) - 1) || !Read(base, found + 0x118, out.actor) || !out.actor ||
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
        Player player;
        if (!Resolve(base, i, player) || player.input_port >= 2 || (seen & (1u << player.input_port))) return -1;
        seen |= 1u << player.input_port;
        if (player.input_port == port) { out = player; ordinal = int(i); }
    }
    return ordinal;
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
thread_local uint32_t cycling_inventory = 0;
struct CycleScope {
    uint32_t previous = cycling_inventory;
    ~CycleScope() { cycling_inventory = previous; }
};
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
} // namespace

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
    uint32_t category = 0, explicit_actor = 0; Player player;
    CycleScope scope;
    if (Read(base, uint64_t(ctx.esp) + 4, category) && category == 0 &&
        Read(base, uint64_t(ctx.esp) + 12, explicit_actor) && !explicit_actor && Owner(base, ctx.ecx, player) >= 0)
        cycling_inventory = ctx.ecx;
    // Keep already collected weapons reachable after disabling the cheat.
    __imp__sub_000973A2(ctx, base);
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
    uint32_t best = 0, best_slot = 0, wrap = 0, wrap_slot = 0; unsigned candidates = 0;
    auto compare = [&](uint32_t a, uint32_t b) { return int32_t(Native(ctx, base, __imp__sub_0009A801, 0, a, b)); };
    const bool complete = Visit(base, player, [&](uint32_t slot, uint32_t actor) {
        uint32_t component = 0; uint8_t selectable = 0;
        if (!actor || actor == current || slot == active || !Weapon(base, actor, player, component)) return true;
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
    if (!complete || (!previous && candidates <= 1)) { __imp__sub_000957A9(ctx, base); return; }
    Write(base, storage_out, best ? best_slot : wrap_slot); Write(base, actor_out, best ? best : wrap);
    ctx.esp += 16;
}
