#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <cstdint>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_0001CED0);
X86_EXTERN_FUNC(__imp__sub_0001D7B2);

namespace {
bool Span(const uint8_t* base, uint64_t address, uint64_t size) {
    if (!base || !address || !size || address + size > (uint64_t(1) << 32)) return false;
    for (auto page = address & ~(uint64_t(mem::kPage) - 1); page < address + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t address, T& value) {
    if (!Span(base, address, sizeof(T))) return false;
    std::memcpy(&value, base + address, sizeof(T)); return true;
}
void Put(uint8_t* base, uint32_t address, uint32_t value) {
    std::memcpy(base + address, &value, sizeof(value));
}
bool Name(const uint8_t* base, uint64_t address, const char* expected) {
    uint32_t text = 0;
    const auto length = std::strlen(expected) + 1;
    return Read(base, address, text) && text && Span(base, uint64_t(text) + 2, length) &&
        !std::memcmp(base + uint64_t(text) + 2, expected, length);
}
bool Component(const uint8_t* base, uint32_t actor, uint32_t type, uint32_t& found) {
    uint16_t count = 0; uint32_t list = 0;
    if (!actor || !Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !list) return false;
    found = 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component = 0, vtable = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, component) || !component ||
            !Read(base, component, vtable)) return false;
        if (vtable != type) continue;
        if (found || !Read(base, uint64_t(component) + 0xC, owner) || owner != actor) return false;
        found = component;
    }
    return found != 0;
}
// Distinct item identities preserve the original Redeemer pickup and two-gun rules.
unsigned Pistol(const uint8_t* base, uint32_t component) {
    uint32_t type = 0;
    if (!component || !Read(base, component, type) || type != 0x418390) return 0;
    if (Name(base, uint64_t(component) + 0x24, "BasicPistol")) return 1;
    if (Name(base, uint64_t(component) + 0x24, "Revolver")) return 2;
    return 0;
}
struct Pair { uint32_t weapon = 0, peer = 0, owner = 0; };
bool Owned(const uint8_t* base, uint32_t actor, uint32_t owner, uint32_t& component) {
    uint32_t player = 0;
    return Component(base, actor, 0x418390, component) &&
        Read(base, uint64_t(component) + 0x58, player) && player == owner;
}
bool Resolve(const uint8_t* base, uint32_t weapon, Pair& pair) {
    const unsigned identity = Pistol(base, weapon);
    uint32_t actor = 0, owner = 0, item = 0, player = 0, inventory = 0, list = 0;
    uint16_t count = 0;
    if (identity != 2 || !Read(base, uint64_t(weapon) + 0xC, actor) ||
        !Read(base, uint64_t(weapon) + 0x58, owner) || !owner ||
        !Owned(base, actor, owner, item) || item != weapon ||
        !Component(base, owner, 0x4227A4, player) ||
        !Component(base, owner, 0x41F29C, inventory) ||
        !Read(base, uint64_t(inventory) + 0x88, count) || !count || count > 64 ||
        !Read(base, uint64_t(inventory) + 0x8C, list) || !list) return false;
    uint32_t peer = 0;
    bool source_present = false;
    auto inspect = [&](uint32_t candidate) {
        if (candidate == actor) { source_present = true; return true; }
        if (!candidate) return true;
        uint32_t component = 0;
        if (!Owned(base, candidate, owner, component)) return true;
        const auto kind = Pistol(base, component);
        if (!kind || kind == identity) return true;
        if (peer && peer != component) return false;
        peer = component; return true;
    };
    for (unsigned i = 0; i < count; ++i) {
        uint32_t slot = 0, type = 0;
        if (!Read(base, uint64_t(list) + i * 4, slot) || !slot || !Read(base, slot, type)) return false;
        if (type == 0x41F570 || type == 0x41F308) {
            uint32_t candidate = 0;
            if (!Read(base, uint64_t(slot) + 0xC, candidate) || !inspect(candidate)) return false;
        } else if (type == 0x41F178) {
            uint16_t items = 0; uint32_t entries = 0;
            if (!Read(base, uint64_t(slot) + 0xC, items) || items > 64 ||
                !Read(base, uint64_t(slot) + 0x10, entries) || (items && !entries)) return false;
            for (unsigned j = 0; j < items; ++j) {
                uint32_t candidate = 0;
                if (!Read(base, uint64_t(entries) + j * 16, candidate) || !inspect(candidate)) return false;
            }
        }
    }
    uint32_t reserve = 0, peer_reserve = 0;
    if (!source_present || !peer || !Span(base, peer, 0x1E0) ||
        !Read(base, uint64_t(weapon) + 0x1DC, reserve) ||
        !Read(base, uint64_t(peer) + 0x1DC, peer_reserve) || reserve > 32767 || peer_reserve > 32767)
        return false;
    pair = {weapon, peer, owner}; return true;
}
struct Refill { uint32_t weapon = 0, accepted = 0; };
thread_local Refill* active_refill = nullptr;
} // namespace

X86_FUNC(sub_0001CED0) {
    const uint32_t weapon = ctx.ecx;
    __imp__sub_0001CED0(ctx, base);
    // Only a committed pickup counts; reloads and other direct grants stay independent.
    if (active_refill && active_refill->weapon == weapon && int32_t(ctx.eax) > 0)
        active_refill->accepted = ctx.eax;
}
X86_FUNC(sub_0001D7B2) {
    Pair before; uint32_t message = 0, mode = 0, event = 0, requested = 0;
    const bool eligible = Resolve(base, ctx.ecx, before) &&
        Read(base, uint64_t(ctx.esp) + 4, message) &&
        Read(base, uint64_t(message) + 4, event) && (event == 0xA2 || event == 0xA4) &&
        Read(base, uint64_t(message) + 0xC, mode) && mode == 0 &&
        Read(base, uint64_t(message) + 0x1C, requested) && requested && requested <= 32767;
    Refill refill{eligible ? uint32_t(ctx.ecx) : 0, 0};
    auto* previous = active_refill;
    active_refill = &refill;
    __imp__sub_0001D7B2(ctx, base);
    active_refill = previous;

    Pair after;
    if (!eligible || !(ctx.eax & 0xFF) || !refill.accepted || refill.accepted > requested ||
        !Resolve(base, before.weapon, after) || after.peer != before.peer || after.owner != before.owner ||
        ctx.esp < 0x200 || !Span(base, uint64_t(ctx.esp) - 0x200, 0x200)) return;
    // Use the original capacity and empty-magazine notification for the separate pistol reserve.
    X86Context call = ctx;
    call.ecx = after.peer;
    call.esp -= 8;
    uint32_t saved_return = 0, saved_argument = 0;
    Read(base, call.esp, saved_return);
    Read(base, uint64_t(call.esp) + 4, saved_argument);
    Put(base, call.esp, 0);
    Put(base, call.esp + 4, refill.accepted);
    __imp__sub_0001CED0(call, base);
    Put(base, ctx.esp - 8, saved_return);
    Put(base, ctx.esp - 4, saved_argument);
}
