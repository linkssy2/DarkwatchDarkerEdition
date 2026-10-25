#pragma once
#include <cstdint>
#include <cstring>
#include "kernel/memory.h"

namespace darkwatch::prompt_owner {
struct Owner { const uint8_t* base = nullptr; int port = -1; };
inline thread_local Owner current;

inline bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    if (!base || !address || address + size > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < address + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T = uint32_t> inline T Read(const uint8_t* base, uint32_t address) {
    T value; std::memcpy(&value, base + address, sizeof(value)); return value;
}
inline int Resolve(const uint8_t* base, uint32_t root) {
    if (!Span(base, root, 0x58) || Read(base, root) != 0x427740 || !Span(base, 0x4AC9A0, 4)) return -1;
    const uint32_t actor = Read(base, root + 0x54), game = Read(base, 0x4AC9A0);
    if (!Span(base, actor, 4) || !Span(base, game, 0x58) || Read(base, game + 0x44) != 2) return -1;
    const uint32_t capacity = Read<uint16_t>(base, game + 0x50), records = Read(base, game + 0x54);
    // DACC6 binds the HUD actor, then F9D95/F9A4D resolve its player record.
    // Record +114 is the original input port, not the viewport/player ordinal.
    if (capacity < 2 || capacity > 64 || !Span(base, records, capacity * 0x130)) return -1;
    unsigned seen = 0; int port = -1;
    for (unsigned i = 0; i < capacity; ++i) {
        const uint32_t record = records + i * 0x130, ordinal = Read(base, record + 0x10C);
        if (ordinal >= 2) continue;
        if (seen & (1u << ordinal)) return -1;
        seen |= 1u << ordinal;
        if (Read(base, record + 0x118) == actor) {
            const uint32_t candidate = Read(base, record + 0x114);
            if (port >= 0 || candidate >= 4) return -1;
            port = int(candidate);
        }
    }
    return seen == 3 ? port : -1;
}
inline int Port(const uint8_t* base) { return current.base == base ? current.port : -1; }
class Scope {
    Owner previous = current;
public:
    Scope(const uint8_t* base, uint32_t root) { current = {base, Resolve(base, root)}; }
    ~Scope() { current = previous; }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
};
} // namespace darkwatch::prompt_owner
