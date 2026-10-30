#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_00097A42);
X86_EXTERN_FUNC(__imp__sub_000978DF);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage) - 1); page < at + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(T)); return true;
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
bool LocalSecondaryInventory(const uint8_t* base, uint32_t inventory) {
    uint32_t owner = 0, flags = 0, game = 0, players = 0, records = 0;
    uint16_t record_count = 0;
    if (!Read(base, uint64_t(inventory) + 0xC, owner) || !owner ||
        !Read(base, uint64_t(owner) + 0x90, flags) || !(flags & 4) ||
        !Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game) + 0x44, players) || !players || players > 2 ||
        !Read(base, uint64_t(game) + 0x50, record_count) || record_count < players || record_count > 64 ||
        !Read(base, uint64_t(game) + 0x54, records) || !Span(base, records, record_count * 0x130)) return false;
    unsigned seen = 0, matches = 0;
    for (unsigned i = 0; i < record_count; ++i) {
        uint32_t index = 0, actor = 0;
        if (!Read(base, uint64_t(records) + i * 0x130 + 0x10C, index)) return false;
        if (index >= players) continue;
        if (seen & (1u << index)) return false;
        seen |= 1u << index;
        if (!Read(base, uint64_t(records) + i * 0x130 + 0x118, actor) || !actor) return false;
        matches += actor == owner;
    }
    uint32_t player_component = 0, owned_inventory = 0;
    if (matches != 1 || seen != ((1u << players) - 1) ||
        !Component(base, owner, 0x4227A4, player_component) ||
        !Component(base, owner, 0x41F29C, owned_inventory) || owned_inventory != inventory) return false;

    // The added character templates have different slot counts/indices. Resolve
    // category 1 through the original table instead of assuming slot 10 or 12.
    uint16_t categories_count = 0, slots_count = 0;
    uint32_t categories = 0, category = 0, slots = 0, secondary = 0, vtable = 0, name = 0;
    constexpr char locator[] = "loc_LeftHand";
    return Read(base, uint64_t(inventory) + 0x78, categories_count) && categories_count >= 2 && categories_count <= 4 &&
        Read(base, uint64_t(inventory) + 0x7C, categories) && Span(base, categories, categories_count * 4) &&
        Read(base, uint64_t(categories) + 4, category) &&
        Read(base, uint64_t(inventory) + 0x88, slots_count) && slots_count && slots_count <= 64 && category < slots_count &&
        Read(base, uint64_t(inventory) + 0x8C, slots) && Span(base, slots, slots_count * 4) &&
        Read(base, uint64_t(slots) + category * 4, secondary) &&
        Read(base, secondary, vtable) && vtable == 0x41F570 &&
        Read(base, uint64_t(secondary) + 4, name) && name && Span(base, uint64_t(name) + 2, sizeof(locator)) &&
        !std::memcmp(base + uint64_t(name) + 2, locator, sizeof(locator));
}
} // namespace

X86_FUNC(sub_00097A42) {
    uint32_t message = 0;
    if (!Read(base, uint64_t(ctx.esp) + 4, message) ||
        ctx.esp < 0x2000 || !Span(base, uint64_t(ctx.esp) - 0x2000, 0x2008) ||
        !LocalSecondaryInventory(base, ctx.ecx)) {
        __imp__sub_00097A42(ctx, base); return;
    }
    // Xbox 97A42 refuses secondary cycling for actor flag bit 2. PlayerComponent
    // AE453 sets this identity flag permanently. With both TNT and Splitters
    // available, the input reaches the native handler but can never select the
    // other grenade. Keep the flag intact and use its existing category-1 path
    // for a validated local player only. Native selection, storage, attachment,
    // counts and ownership remain in 978DF -> 973A2; Carry All is unrelated.
    // The argument is opaque here: both message dispatch and the original empty
    // grenade fallback (97AB7) call this handler, which never reads its payload.
    const uint32_t argument = ctx.esp + 4, secondary = 1;
    std::memcpy(base + argument, &secondary, sizeof(secondary));
    __imp__sub_000978DF(ctx, base); // Same ret 4 ABI as the intercepted handler.
    std::memcpy(base + argument, &message, sizeof(message));
}
