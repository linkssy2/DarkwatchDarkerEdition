#include "third_person_weapon.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>

extern "C" void __imp__sub_00260D40(X86Context&, uint8_t*);

namespace {
struct Part { const char* weapon; uint32_t bones, bone; std::array<float, 3> seat; float scale; };
constexpr Part parts[]{
#define MECHANICAL_RELOAD_PART(name, count, bone, x, y, z, scale) {name, count, bone, {x,y,z}, scale},
#include "../../../launcher/body_reload_parts.inc"
#undef MECHANICAL_RELOAD_PART
};
bool Span(const uint8_t* base, uint64_t at, uint64_t bytes) {
    if (!base || !at || !bytes || at + bytes > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage)-1); page < at+bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base+at, sizeof(value)); return true;
}
bool Name(const uint8_t* base, uint64_t at, const char* text) {
    uint32_t pointer = 0;
    const auto size = std::strlen(text)+1;
    return Read(base, at, pointer) && pointer && Span(base, uint64_t(pointer)+2, size) &&
        !std::memcmp(base+uint64_t(pointer)+2, text, size);
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    uint16_t count = 0; uint32_t list = 0, result = 0;
    if (!actor || !Read(base, uint64_t(actor)+0x60, count) || !count || count>128 ||
        !Read(base, uint64_t(actor)+0x64, list) || !Span(base, list, count*8)) return 0;
    for (unsigned i=0; i<count; ++i) {
        uint32_t component=0, type=0, owner=0;
        if (!Read(base, uint64_t(list)+i*8+4, component) || !Read(base, component, type)) return 0;
        if (type!=wanted) continue;
        if (result || !Read(base, uint64_t(component)+0xC, owner) || owner!=actor) return 0;
        result=component;
    }
    return result;
}
bool Reloading(const uint8_t* base, uint32_t controller) {
    // Native 232551 supplies the blend-slot count; 23413B/232E7D queue the
    // row's numeric key. Match a weighted clock, not the row's static flags.
    constexpr unsigned slot_counts[]{4,14,24};
    uint32_t owner=0, mode=0, slots=0, groups=0; uint16_t count=0;
    if (!Read(base, uint64_t(controller)+0xE4, owner) || owner!=controller ||
        !Read(base, uint64_t(controller)+0x160, mode) || mode>=3 ||
        !Read(base, uint64_t(controller)+0xE0, slots) || !Span(base, slots, slot_counts[mode]*0x3C) ||
        !Read(base, uint64_t(controller)+0x28, count) || !count || count>8 ||
        !Read(base, uint64_t(controller)+0x2C, groups) || !Span(base, groups, count*0x3C)) return false;
    for (unsigned g=0; g<count; ++g) {
        uint32_t resource=0, rows=0, group_owner=0; uint16_t row_count=0;
        const uint64_t group=uint64_t(groups)+g*0x3C;
        if (!Read(base, group+0xC, group_owner) || group_owner!=controller ||
            !Read(base, group+0x14, resource) || !resource ||
            !Read(base, resource, row_count) || !row_count || row_count>128 ||
            !Read(base, uint64_t(resource)+4, rows) || !Span(base, rows, row_count*0x8C)) return false;
        for (unsigned r=0; r<row_count; ++r) {
            const uint64_t row=uint64_t(rows)+r*0x8C;
            if (!Name(base, row+0x70, "RELOAD")) continue;
            uint32_t key=0;
            if (!Read(base, row+0x6C, key) || !key) return false;
            for (unsigned s=0; s<slot_counts[mode]; ++s) {
                const uint64_t slot=uint64_t(slots)+s*0x3C;
                uint32_t active=0, clock=0; float weight=0;
                if (!Read(base, slot+0x10, active) || active!=key) continue;
                if (Read(base, slot, weight) && std::isfinite(weight) && weight>0 && weight<=1.001f &&
                    Read(base, slot+0x20, clock) && clock && Span(base, clock, 0x38)) return true;
            }
        }
    }
    return false;
}
const Part* WeaponPart(const uint8_t* base, uint32_t actor, uint32_t hierarchy, uint32_t bones) {
    const uint32_t inventory=Component(base, actor, 0x41F29C);
    uint32_t mode=0, slots=0, categories=0, category=0, slot=0, type=0, owner=0, weapon=0, parent=0;
    uint16_t count=0, categories_count=0;
    if (!inventory || !Read(base, uint64_t(inventory)+0x64, mode) || mode!=0 ||
        !Read(base, uint64_t(inventory)+0x88, count) || !count || count>64 ||
        !Read(base, uint64_t(inventory)+0x8C, slots) || !Span(base, slots, count*4) ||
        !Read(base, uint64_t(inventory)+0x78, categories_count) || !categories_count || categories_count>4 ||
        !Read(base, uint64_t(inventory)+0x7C, categories) || !Read(base, categories, category) || category>=count ||
        !Read(base, uint64_t(slots)+category*4, slot) || !Read(base, slot, type) || type!=0x41F570 ||
        !Read(base, uint64_t(slot)+8, owner) || owner!=inventory ||
        !Name(base, uint64_t(slot)+4, "loc_RightHand") ||
        !Read(base, uint64_t(slot)+0xC, weapon) || !weapon ||
        !Read(base, uint64_t(slot)+0x1C, parent) || parent!=actor) return nullptr;
    const Part* part=nullptr;
    for (const auto& candidate:parts)
        if (candidate.bones==bones && Name(base, uint64_t(weapon)+0x50, candidate.weapon)) part=&candidate;
    if (!part) return nullptr;
    const uint32_t animation=Component(base, weapon, 0x41D258);
    uint32_t pose=0, actual=0, controller=0, controller_pose=0, controller_owner=0, parent_pose=0;
    if (!animation || !Read(base, uint64_t(animation)+0x34, pose) || !pose ||
        !Read(base, pose, parent_pose) || parent_pose ||
        !Read(base, uint64_t(pose)+0x10, actual) || actual!=hierarchy ||
        !Read(base, uint64_t(animation)+0x60, controller) || !controller ||
        !Read(base, uint64_t(controller)+0x88, controller_owner) || controller_owner!=weapon ||
        !Read(base, uint64_t(controller)+0x58, controller_pose) || controller_pose!=pose ||
        !Reloading(base, controller)) return nullptr;
    return part;
}
const Part* Match(const uint8_t* base, uint32_t hierarchy, uint32_t bones) {
    uint32_t game=0, players=0, records=0, seen=0; uint16_t count=0;
    if (!Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game)+0x44, players) || !players || players>2 ||
        !Read(base, uint64_t(game)+0x50, count) || count<players || count>64 ||
        !Read(base, uint64_t(game)+0x54, records) || !Span(base, records, count*0x130)) return nullptr;
    const Part* result=nullptr;
    for (unsigned i=0; i<count; ++i) {
        uint32_t ordinal=0, actor=0;
        const uint64_t row=uint64_t(records)+i*0x130;
        if (!Read(base, row+0x10C, ordinal)) return nullptr;
        if (ordinal>=players) continue;
        if ((seen&(1u<<ordinal)) || !Read(base, row+0x118, actor) || !actor) return nullptr;
        seen|=1u<<ordinal;
        if (const auto* part=WeaponPart(base, actor, hierarchy, bones)) {
            if (result) return nullptr;
            result=part;
        }
    }
    return seen==(1u<<players)-1 ? result : nullptr;
}
}

void DarkwatchWeaponSkinPalette(X86Context& ctx, uint8_t* base) {
    uint32_t atomic=0, offset=0, hierarchy=0, flags=0, bones=0, matrices=0, output=0, skin=0, palette_count=0;
    if (base==kernel::g_base && Read(base, uint64_t(ctx.esp)+8, atomic) && atomic &&
        Read(base, 0x4BA834, offset) && offset && offset<0x1000 &&
        Read(base, uint64_t(atomic)+offset, hierarchy) && hierarchy &&
        Read(base, hierarchy, flags) && !(flags&2) &&
        Read(base, uint64_t(hierarchy)+4, bones) && (bones==4 || bones==5 || bones==8) &&
        Read(base, uint64_t(hierarchy)+8, matrices) && Span(base, matrices, bones*64) &&
        Read(base, uint64_t(ctx.esp)+4, output) &&
        Read(base, uint64_t(ctx.esp)+12, skin) && skin &&
        Read(base, uint64_t(skin)+0x81C, palette_count) && palette_count && palette_count<=bones &&
        Span(base, output, palette_count*48) &&
        !(uint64_t(output)<uint64_t(matrices)+bones*64 && uint64_t(matrices)<uint64_t(output)+palette_count*48)) {
        if (const auto* part=Match(base, hierarchy, bones)) {
            std::array<float,16> root{}, saved{}, adjusted{};
            const uint64_t address=uint64_t(matrices)+part->bone*64;
            std::memcpy(root.data(), base+matrices, sizeof(root));
            std::memcpy(saved.data(), base+address, sizeof(saved));
            adjusted=saved;
            bool valid=true;
            for (unsigned row=0; row<4; ++row) for (unsigned axis=0; axis<3; ++axis)
                valid &= std::isfinite(root[row*4+axis]) && std::isfinite(saved[row*4+axis]);
            for (unsigned axis=0; axis<3; ++axis) {
                const float seat=root[12+axis]+part->seat[0]*root[axis]+
                    part->seat[1]*root[4+axis]+part->seat[2]*root[8+axis];
                adjusted[12+axis]=seat+part->scale*(saved[12+axis]-seat);
                valid &= std::isfinite(adjusted[12+axis]);
            }
            if (valid) {
                // 260D40 copies the current hierarchy into fresh draw constants.
                // Restore the cached pose before the next atomic, camera, or
                // first-person pass; no shared animation/clock is edited.
                struct Restore { uint8_t* at; const std::array<float,16>& saved;
                    ~Restore(){std::memcpy(at,saved.data(),sizeof(saved));} } restore{base+address,saved};
                std::memcpy(base+address, adjusted.data(), sizeof(adjusted));
                __imp__sub_00260D40(ctx, base);
                return;
            }
        }
    }
    __imp__sub_00260D40(ctx, base);
}
