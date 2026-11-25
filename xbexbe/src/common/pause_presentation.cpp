#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <array>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_001E9F1A);
X86_EXTERN_FUNC(__imp__sub_001E8F28);
X86_EXTERN_FUNC(__imp__sub_001E8E4F);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    if (!base || !at || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~uint64_t(mem::kPage - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t at) {
    uint32_t value; std::memcpy(&value, base + at, 4); return value;
}
bool KeepPausePresentation(X86Context& ctx, uint8_t* base, bool manager) {
    if (!Span(base, ctx.esp, 4) || Read(base, ctx.esp) != (manager ? 0xF012Du : 0xF0116u) ||
        !Span(base, ctx.esi, 0x124) || Read(base, ctx.esi) != 0x42B318 ||
        ctx.esp < 16 || !Span(base, uint64_t(ctx.esp) - 16, 16)) return false;
    const auto hud = Read(base, ctx.esi + 0xF4);
    if (!Span(base, hud, 0x124) || Read(base, hud) != 0x427740 ||
        Read(base, hud + 0x120) != ctx.esi || base[hud + 0x2F] != 1) return false;
    if (manager) {
        if (!Span(base, 0x4AD308, 4) || Read(base, 0x4AD308) != ctx.ecx ||
            !Span(base, ctx.ecx, 0x11) || Read(base, ctx.ecx) != 0x43BB6C) return false;
    } else if (ctx.ecx != hud) return false;

    // F00DA hides the HUD and personal-view manager on pause. Retain their
    // rendering, but keep the native focus setter so gameplay cannot take input.
    std::array<uint8_t, 16> saved;
    std::memcpy(saved.data(), base + ctx.esp - 16, saved.size());
    auto call = ctx; call.ecx = hud; call.esp -= 8;
    std::memset(base + call.esp, 0, 8);
    __imp__sub_001E8E4F(call, base);
    std::memcpy(base + ctx.esp - 16, saved.data(), saved.size());
    ctx.esp += 4;
    return true;
}
}

X86_FUNC(sub_001E9F1A) {
    if (!KeepPausePresentation(ctx, base, true)) __imp__sub_001E9F1A(ctx, base);
}
X86_FUNC(sub_001E8F28) {
    if (!KeepPausePresentation(ctx, base, false)) __imp__sub_001E8F28(ctx, base);
}
