#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <cmath>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_002341AC);

namespace {
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
bool Name(const uint8_t* base, uint64_t at, const char* name) {
    uint32_t token=0;
    const auto size=std::strlen(name)+1;
    return Read(base, at, token) && token && Span(base, uint64_t(token)+2, size) &&
        !std::memcmp(base+uint64_t(token)+2, name, size);
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    uint16_t count=0; uint32_t list=0, result=0;
    if (!Read(base, uint64_t(actor)+0x60, count) || !count || count>128 ||
        !Read(base, uint64_t(actor)+0x64, list) || !Span(base, list, count*8)) return 0;
    for (unsigned i=0; i<count; ++i) {
        uint32_t part=0, type=0, owner=0;
        if (!Read(base, uint64_t(list)+i*8+4, part) || !Read(base, part, type)) return 0;
        if (type!=wanted) continue;
        if (result || !Read(base, uint64_t(part)+0xC, owner) || owner!=actor) return 0;
        result=part;
    }
    return result;
}
bool PlayerBody(const uint8_t* base, uint32_t actor, uint32_t controller) {
    uint32_t game=0, players=0, records=0; uint16_t count=0;
    if (!Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game)+0x44, players) || !players || players>2 ||
        !Read(base, uint64_t(game)+0x50, count) || count<players || count>64 ||
        !Read(base, uint64_t(game)+0x54, records) || !Span(base, records, count*0x130)) return false;
    unsigned matches=0;
    for (unsigned i=0; i<count; ++i) {
        uint32_t ordinal=0, candidate=0;
        if (!Read(base, uint64_t(records)+i*0x130+0x10C, ordinal) ||
            !Read(base, uint64_t(records)+i*0x130+0x118, candidate)) return false;
        if (ordinal<players && candidate==actor) ++matches;
    }
    if (matches!=1) return false;
    const auto control=Component(base, actor, 0x41F878), animation=Component(base, actor, 0x41D258);
    uint32_t owned_controller=0, owned_animation=0;
    return control && animation && Read(base, uint64_t(animation)+0x60, owned_controller) &&
        owned_controller==controller && Read(base, uint64_t(control)+0x2C0, owned_animation) &&
        owned_animation==animation;
}
bool PreserveReload(const X86Context& ctx, const uint8_t* base) {
    uint32_t caller=0, index=0, type=0, controller=0, actor=0, groups=0, resource=0, rows=0;
    uint16_t group_count=0, row_count=0;
    const uint32_t group=ctx.ecx;
    // 234217 retires rows whose modifiers changed. Other stop requests, such
    // as switching weapons or dying, must still reach the original routine.
    if (!Read(base, ctx.esp, caller) || caller!=0x23426D ||
        !Read(base, uint64_t(ctx.esp)+4, index) || !Read(base, group, type) || type!=0x44111C ||
        !Read(base, uint64_t(group)+0xC, controller) || !controller ||
        !Read(base, uint64_t(controller)+0x88, actor) || !actor ||
        !Read(base, uint64_t(controller)+0x28, group_count) || !group_count || group_count>64 ||
        !Read(base, uint64_t(controller)+0x2C, groups) || !Span(base, groups, group_count*0x3C) ||
        group<groups || uint64_t(group)>=uint64_t(groups)+group_count*0x3C || (group-groups)%0x3C ||
        !Read(base, uint64_t(group)+0x14, resource) || !Read(base, resource, row_count) ||
        !row_count || row_count>128 || index>=row_count ||
        !Read(base, uint64_t(resource)+4, rows) || !Span(base, rows, row_count*0x8C)) return false;
    const uint64_t row=uint64_t(rows)+index*0x8C;
    if (!Name(base,row+0x70,"PRERELOAD") && !Name(base,row+0x70,"RELOAD") && !Name(base,row+0x70,"POSTRELOAD")) return false;
    uint32_t bitmap=0, predicates=0, selectors=0; uint16_t count=0;
    if (!Read(base, uint64_t(group)+0x2C+(index/32)*4, bitmap) || !(bitmap&(1u<<(index%32))) ||
        !Read(base,row+0x80,count) || !count || count>32 || !Read(base,row+0x84,predicates) ||
        !Span(base,predicates,count*8) || !Read(base,uint64_t(controller)+0x144,selectors) ||
        !Span(base,selectors,12*4)) return false;
    unsigned required=0, matched=0;
    for (unsigned i=0; i<count; ++i) {
        uint32_t category=0,value=0,actual=0;
        if (!Read(base,uint64_t(predicates)+i*8,category) || category>=12 ||
            !Read(base,uint64_t(predicates)+i*8+4,value) ||
            !Read(base,uint64_t(selectors)+category*4,actual) ||
            (category==2 && (value>1 || actual>1))) return false;
        required|=1u<<category;
        if (actual==value) matched|=1u<<category;
    }
    if ((required&~matched)!=(1u<<2) || !PlayerBody(base,actor,controller)) return false;
    constexpr unsigned capacities[]{4,14,24};
    uint32_t mode=0, slots=0, key=0;
    if (!Read(base,uint64_t(controller)+0x160,mode) || mode>=3 ||
        !Read(base,uint64_t(controller)+0xE0,slots) || !Span(base,slots,capacities[mode]*0x3C) ||
        !Read(base,row+0x6C,key) || !key) return false;
    for (unsigned i=0; i<capacities[mode]; ++i) {
        const uint64_t slot=uint64_t(slots)+i*0x3C;
        uint32_t candidate=0, clock=0; float weight=0,target=0,phase=0; uint8_t complete=0;
        if (!Read(base,slot+0x10,candidate) || candidate!=key) continue;
        if (Read(base,slot,weight) && Read(base,slot+4,target) &&
            std::isfinite(weight) && weight>0 && weight<=1.001f &&
            std::isfinite(target) && target>0 && target<=1.001f &&
            Read(base,slot+0x20,clock) && clock && Read(base,clock,phase) &&
            std::isfinite(phase) && phase>=0 && phase<1 &&
            Read(base,uint64_t(clock)+0x18,complete) && !complete) return true;
    }
    return false;
}
}

X86_FUNC(sub_002341AC) {
    if (!PreserveReload(ctx,base)) { __imp__sub_002341AC(ctx,base); return; }
    // Finish the current body clip at its existing phase. The hidden hands and
    // weapon keep their original clocks, ammunition events and cancellation.
    ctx.eax &= 0xFFFFFF00u;
    ctx.esp += 8;
}
