#include "cpu/x86_context.h"
#include "kernel/memory.h"
#include <cstring>

namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage) - 1); page < at + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(T));
    return true;
}
template<size_t N> bool Text(const uint8_t* base, uint64_t slot, const char (&expected)[N]) {
    uint32_t ref;
    return Read(base, slot, ref) && ref && Span(base, uint64_t(ref) + 2, N) &&
        std::memcmp(base + uint64_t(ref) + 2, expected, N) == 0;
}
template<size_t N> bool LuaEntry(const uint8_t* base, uint32_t table, unsigned index,
                                uint32_t id, uint32_t time, const char (&script)[N],
                                uint32_t& descriptor) {
    uint32_t wrapper, type, action, event, event_action, params, actual_id, actual_time, dependent;
    uint16_t count;
    return Read(base, uint64_t(table) + index * 4, wrapper) &&
        Read(base, wrapper, descriptor) && Read(base, descriptor, type) && type == 0x440E24 &&
        Read(base, uint64_t(descriptor) + 4, action) && Read(base, action, type) && type == 0x423340 &&
        Read(base, uint64_t(wrapper) + 4, event) && Read(base, event, type) && type == 0x440614 &&
        Read(base, uint64_t(event) + 0x54, event_action) && event_action == action &&
        Read(base, uint64_t(descriptor) + 8, dependent) && !dependent &&
        Read(base, uint64_t(descriptor) + 0xC, actual_time) && actual_time == time &&
        Read(base, uint64_t(descriptor) + 0x14, actual_id) && actual_id == id &&
        Text(base, uint64_t(action) + 4, script) &&
        Read(base, uint64_t(action) + 8, count) && count == 1 &&
        Read(base, uint64_t(action) + 0xC, params) && Text(base, params, "Scourge_v2_Attacks");
}
}

void DarkwatchBossIntroStart(X86Context& ctx, uint8_t* base) {
    const uint64_t sequence = ctx.ecx;
    uint32_t type, table, spawn, disable;
    uint16_t count, capacity;
    if (!Read(base, sequence, type) || type != 0x440E34 ||
        !Read(base, sequence + 0x70, count) || count != 18 ||
        !Read(base, sequence + 0x72, capacity) || capacity < count ||
        !Read(base, sequence + 0x74, table) || !Span(base, table, count * 4) ||
        !LuaEntry(base, table, 2, 35, 0, "Scripts\\SpawnActor", spawn) ||
        !LuaEntry(base, table, 4, 54, 0x3C5C486B, "Scripts\\DeactivateAI", disable)) return;

    // Disable in the same ordered pass as Spawn, before an early attack can be cancelled.
    const uint32_t zero = 0;
    std::memcpy(base + uint64_t(disable) + 0xC, &zero, sizeof(zero));
}
