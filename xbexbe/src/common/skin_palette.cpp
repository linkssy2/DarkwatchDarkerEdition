#include <array>
#include <cstring>
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

extern "C" void __imp__sub_0010BF30(X86Context&, uint8_t*);

namespace {
bool Span(const uint8_t* base, uint64_t address, size_t size) {
    if (!base || !address || !size || address + size > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < address + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t address) {
    uint32_t value; std::memcpy(&value, base + address, 4); return value;
}
bool Overlap(uint32_t a, size_t an, uint32_t b, size_t bn) {
    return uint64_t(a) < uint64_t(b) + bn && uint64_t(b) < uint64_t(a) + an;
}
}

extern "C" void sub_0010BF30(X86Context& ctx, uint8_t* base) {
    // Only the two atomic-world inverses inside the original skin producer.
    // Blood Vision temporarily reattaches clumps and reclassifies unchanged
    // matrices. Switching between transpose and general inverse then moves
    // highlighted vertices by a few ULPs relative to their depth-tested mesh.
    const uint32_t stack = ctx.esp, aligned = ctx.ebp & ~15u;
    if (base != kernel::g_base || aligned < 0x140 || stack != aligned - 0xF0 ||
        !Span(base, stack - 0x50, 0x5C) || !Span(base, ctx.ebp, 0x14)) {
        __imp__sub_0010BF30(ctx, base); return;
    }
    const uint32_t caller = Read(base, stack);
    const uint32_t offset = caller == 0x260DAF ? 0xB0 : caller == 0x260EE5 ? 0x30 : 0;
    const uint32_t output = Read(base, stack + 4), source = Read(base, stack + 8);
    const uint32_t atomic = Read(base, ctx.ebp + 0xC);
    if (!offset || output != stack + offset || !Span(base, atomic, 8) ||
        !Span(base, source, 64) || !Span(base, output, 64) ||
        uint64_t(Read(base, atomic + 4)) + 0x50 != source ||
        Overlap(source, 64, stack - 0x50, 0x5C) || Overlap(source, 64, output, 64)) {
        __imp__sub_0010BF30(ctx, base); return;
    }
    const uint32_t flags = Read(base, source + 0xC);
    if (!(flags & 0x20000) && (flags & 3) != 3) {
        __imp__sub_0010BF30(ctx, base); return;
    }
    // Original inverse needs at most one word below ESP. Keep the copy away
    // from that slot, restore the borrowed bytes and argument, and never
    // modify the shared frame, optimization mask, or animation matrices.
    const uint32_t local = stack - 0x50, general = flags & ~0x20003u;
    std::array<uint8_t, 64> saved;
    std::memcpy(saved.data(), base + local, saved.size());
    std::memcpy(base + local, base + source, 64);
    std::memcpy(base + local + 0xC, &general, 4);
    std::memcpy(base + stack + 8, &local, 4);
    __imp__sub_0010BF30(ctx, base);
    std::memcpy(base + stack + 8, &source, 4);
    std::memcpy(base + local, saved.data(), saved.size());
}
