#include <cstring>
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include "xdk/d3d8.h"

X86_EXTERN_FUNC(__imp__sub_0021B0D1);

namespace {
bool SubtitleSpan(const uint8_t* base, uint64_t address, uint32_t size) {
    if (!base || !address || address + size > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < address + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t SubtitleRead(const uint8_t* base, uint32_t address) {
    uint32_t value; std::memcpy(&value, base + address, 4); return value;
}
} // namespace

X86_FUNC(sub_0021B0D1) {
    if (!SubtitleSpan(base, ctx.ecx, 0x48) || SubtitleRead(base, ctx.ecx) != 0x43FB40 ||
        !SubtitleSpan(base, ctx.esp, 8)) {
        __imp__sub_0021B0D1(ctx, base);
        return;
    }
    // Motion blur samples the previous guest front buffer; native subtitle pixels
    // must reach only the presentation layer, retaining original layout and expiry.
    std::lock_guard lock(d3d::Lock());
    auto& layer = d3d::State().presentation_overlay;
    struct Restore { bool& value; bool previous; ~Restore() { value = previous; } } restore{layer, layer};
    layer = true;
    __imp__sub_0021B0D1(ctx, base);
}
