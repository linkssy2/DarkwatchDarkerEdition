#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_00216244);

namespace {
struct GripFit { const char* actor; const char* weapon; float right; float left; };
constexpr GripFit kGripFits[]{
#define BODY_WEAPON_GRIP(actor, weapon, right, left) {actor, weapon, float(right), float(left)},
#include "../../../launcher/body_weapon_grips.inc"
#undef BODY_WEAPON_GRIP
};
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage) - 1); page < at + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base + at, sizeof(value));
    return true;
}
bool Name(const uint8_t* base, uint64_t at, const char* expected) {
    uint32_t text = 0;
    const auto bytes = std::strlen(expected) + 1;
    return Read(base, at, text) && text && Span(base, uint64_t(text) + 2, bytes) &&
        !std::memcmp(base + uint64_t(text) + 2, expected, bytes);
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    uint32_t list = 0, result = 0;
    uint16_t count = 0;
    if (!actor || !Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, count * 8)) return 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component = 0, type = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, component) || !Read(base, component, type)) return 0;
        if (type != wanted) continue;
        if (result || !Read(base, uint64_t(component) + 0xC, owner) || owner != actor) return 0;
        result = component;
    }
    return result;
}
bool RegisteredPlayer(const uint8_t* base, uint32_t actor) {
    uint32_t game = 0, players = 0, records = 0, seen = 0;
    uint16_t count = 0;
    if (!Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game) + 0x44, players) || !players || players > 2 ||
        !Read(base, uint64_t(game) + 0x50, count) || count < players || count > 64 ||
        !Read(base, uint64_t(game) + 0x54, records) || !Span(base, records, count * 0x130)) return false;
    unsigned matches = 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t ordinal = 0, player = 0;
        const uint64_t record = uint64_t(records) + i * 0x130;
        if (!Read(base, record + 0x10C, ordinal)) return false;
        if (ordinal >= players) continue;
        if (seen & (1u << ordinal) || !Read(base, record + 0x118, player)) return false;
        seen |= 1u << ordinal;
        matches += player == actor;
    }
    return matches == 1 && seen == (1u << players) - 1;
}
float Offset(const X86Context& ctx, const uint8_t* base) {
    const uint32_t weapon = ctx.ecx;
    constexpr uint32_t item_types[]{0x418390, 0x417E90, 0x417F78, 0x418098, 0x418150, 0x418208};
    uint32_t item = 0;
    for (const auto type : item_types) {
        const auto candidate = Component(base, weapon, type);
        if (candidate) { if (item) return 0; item = candidate; }
    }
    uint32_t actor = 0;
    if (!item || !Read(base, uint64_t(item) + 0x58, actor) || !actor || !RegisteredPlayer(base, actor)) return 0;
    uint32_t source_actor = 0, source_pose = 0;
    const uint32_t animation = Component(base, actor, 0x41D258);
    if (!animation || !Read(base, uint64_t(ctx.ebp) + 8, source_actor) || source_actor != actor ||
        !Read(base, uint64_t(ctx.ebp) + 0xC, source_pose) ||
        uint64_t(animation) + 0x30 != source_pose) return 0;
    const GripFit* fit = nullptr;
    for (const auto& entry : kGripFits)
        if (Name(base, uint64_t(actor) + 0x50, entry.actor) &&
            Name(base, uint64_t(weapon) + 0x50, entry.weapon) &&
            Name(base, uint64_t(item) + 0x24, entry.weapon)) { fit = &entry; break; }
    if (!fit) return 0;

    const uint32_t inventory = Component(base, actor, 0x41F29C);
    uint32_t mode = 0, slots = 0, categories = 0, category = 0, slot = 0, type = 0;
    uint32_t owner = 0, held = 0, parent = 0;
    uint16_t count = 0, category_count = 0;
    if (!inventory || !Component(base, actor, 0x4227A4) ||
        !Read(base, uint64_t(inventory) + 0x64, mode) || mode != 0 ||
        !Read(base, uint64_t(inventory) + 0x88, count) || !count || count > 64 ||
        !Read(base, uint64_t(inventory) + 0x8C, slots) || !Span(base, slots, count * 4) ||
        !Read(base, uint64_t(inventory) + 0x78, category_count) || !category_count || category_count > 4 ||
        !Read(base, uint64_t(inventory) + 0x7C, categories) || !Read(base, categories, category) || category >= count ||
        !Read(base, uint64_t(slots) + category * 4, slot) || !Read(base, slot, type) || type != 0x41F570 ||
        !Name(base, uint64_t(slot) + 4, "loc_RightHand") ||
        !Read(base, uint64_t(slot) + 8, owner) || owner != inventory ||
        !Read(base, uint64_t(slot) + 0xC, held) || !held ||
        !Read(base, uint64_t(slot) + 0x1C, parent) || parent != actor) return 0;

    const char* locator_name = "loc_RightHand";
    float offset = fit->right;
    if (held != weapon) {
        // Native DoublePistol owns a separate child actor. Its actual body slot
        // is loc_LeftHandDualWield; ordinary left attachments are not weapons.
        if (!fit->left || std::strcmp(fit->weapon, "DoublePistol")) return 0;
        const auto master = Component(base, held, 0x417E90);
        uint32_t child = 0, child_component = 0, master_owner = 0;
        uint8_t master_flag = 0, child_flag = 1;
        if (!master || item != Component(base, weapon, 0x417E90) ||
            !Name(base, uint64_t(held) + 0x50, "DoublePistol") ||
            !Name(base, uint64_t(master) + 0x24, "DoublePistol") ||
            !Read(base, uint64_t(master) + 0x58, master_owner) || master_owner != actor ||
            !Read(base, uint64_t(master) + 0x330, master_flag) || master_flag != 1 ||
            !Read(base, uint64_t(item) + 0x330, child_flag) || child_flag ||
            !Read(base, uint64_t(master) + 0x338, child) || child != weapon ||
            !Read(base, uint64_t(master) + 0x348, child_component) || child_component != item) return 0;
        locator_name = "loc_LeftHandDualWield";
        unsigned matches = 0;
        for (unsigned i = 0; i < count; ++i) {
            uint32_t candidate = 0;
            if (!Read(base, uint64_t(slots) + i * 4, candidate)) return 0;
            if (!Name(base, uint64_t(candidate) + 4, locator_name)) continue;
            if (++matches != 1 || !Read(base, candidate, type) || type != 0x41F570 ||
                !Read(base, uint64_t(candidate) + 8, owner) || owner != inventory ||
                !Read(base, uint64_t(candidate) + 0xC, held) || held != weapon ||
                !Read(base, uint64_t(candidate) + 0x1C, parent) || parent != actor) return 0;
        }
        if (matches != 1) return 0;
        offset = fit->left;
    } else if (!std::strcmp(fit->weapon, "DoublePistol")) {
        uint8_t master_flag = 0;
        if (item != Component(base, weapon, 0x417E90) ||
            !Read(base, uint64_t(item) + 0x330, master_flag) || master_flag != 1) return 0;
    }
    if (!offset) return 0;

    // AA19F can update many actors from the same temporary matrix. Admit only
    // this body's selected attachment; never hidden hands or another loop actor.
    const uint32_t locator = Component(base, actor, 0x422590);
    uint32_t rows = 0;
    uint16_t row_count = 0;
    if (!locator || !Read(base, uint64_t(locator) + 0x20, row_count) || !row_count || row_count > 128 ||
        !Read(base, uint64_t(locator) + 0x24, rows) || !Span(base, rows, row_count * 0x40)) return 0;
    unsigned matches = 0;
    for (unsigned i = 0; i < row_count; ++i) {
        const uint64_t row = uint64_t(rows) + i * 0x40;
        if (!Name(base, row + 0x10, locator_name)) continue;
        uint32_t refs = 0, attached = 0;
        uint16_t refs_count = 0;
        if (++matches != 1 || !Read(base, row, refs_count) || !refs_count || refs_count > 64 ||
            !Read(base, row + 4, refs) || !Span(base, refs, refs_count * 16) ||
            uint64_t(refs) + refs_count * 16 != ctx.esi || ctx.edi < refs || ctx.edi >= ctx.esi ||
            (ctx.edi - refs) % 16 || !Read(base, ctx.edi, attached) || attached != weapon) return 0;
    }
    return matches == 1 ? offset : 0;
}
}

X86_FUNC(sub_00216244) {
    uint32_t caller = 0, matrix = 0;
    if (ctx.ebp >= 0x60 && ctx.esp == (ctx.ebp & ~15u) - 0x58 &&
        Read(base, ctx.esp, caller) && caller == 0xAA1E3 &&
        Read(base, uint64_t(ctx.esp) + 4, matrix) && uint64_t(ctx.esp) + 0x18 == matrix &&
        Span(base, matrix, 64)) {
        const float offset = Offset(ctx, base);
        if (offset) {
            std::array<float, 16> original;
            std::memcpy(original.data(), base + matrix, sizeof(original));
            bool valid = true;
            float length = 0;
            for (unsigned row = 0; row < 4; ++row) for (unsigned axis = 0; axis < 3; ++axis)
                valid &= std::isfinite(original[row * 4 + axis]) && std::abs(original[row * 4 + axis]) < 1000000.f;
            for (unsigned axis = 0; axis < 3; ++axis) length += original[axis] * original[axis];
            if (valid && std::isfinite(length) && std::abs(length - 1.f) < .02f) {
                struct Restore {
                    uint8_t* where; const std::array<float, 16>& saved;
                    ~Restore() { std::memcpy(where, saved.data(), sizeof(saved)); }
                } restore{base + matrix, original};
                std::array<float, 16> adjusted;
                std::memcpy(adjusted.data(), original.data(), sizeof(adjusted));
                // Measured along each held weapon's length from actual hand
                // skin. Keep orientation and transverse grip depth unchanged.
                for (unsigned axis = 0; axis < 3; ++axis) adjusted[12 + axis] += original[axis] * offset;
                std::memcpy(base + matrix, adjusted.data(), sizeof(adjusted));
                __imp__sub_00216244(ctx, base);
                return;
            }
        }
    }
    __imp__sub_00216244(ctx, base);
}
