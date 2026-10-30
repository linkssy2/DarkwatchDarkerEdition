#include "common/coop.h"
#include "core/input.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"
#include <cstring>

namespace {
bool HasLiteral(const X86Context& ctx, const uint8_t* base, uint32_t expected) {
    if (!base || !ctx.esp || uint64_t(ctx.esp)+4 > (uint64_t(1)<<32) ||
        !mem::IsCommitted(ctx.esp) || !mem::IsCommitted(ctx.esp+3)) return false;
    uint32_t value;
    std::memcpy(&value,base+ctx.esp,4);
    return value == expected;
}
void ReplaceLiteral(X86Context& ctx, uint8_t* base, uint32_t expected, uint32_t replacement) {
    if (HasLiteral(ctx,base,expected)) std::memcpy(base+ctx.esp,&replacement,4);
}
}

// v2.0 coop.ips frontend edits, applied before the original owned-string APIs.
void DarkwatchCoopLabel(X86Context& ctx, uint8_t* base) {
    ReplaceLiteral(ctx,base,0x429868,0x42A688); // XBL_XboxLive -> GEN_COOP
}
void DarkwatchCoopProfile(X86Context& ctx, uint8_t* base) {
    ReplaceLiteral(ctx,base,0x4298F8,0x429918); // Xbox local profile-selection page.
}
void DarkwatchCoopCallback(X86Context& ctx, uint8_t*) {
    if(ctx.esi==0xEA88F) ctx.esi=0xEA939;
}
void DarkwatchCoopEnter(X86Context& ctx, uint8_t* base) {
    if (HasLiteral(ctx,base,0x4298B8)) input::SetCoopKeyboard(!input::GetLastDevice().controller);
}
void DarkwatchCoopTextureQuality(X86Context& ctx, uint8_t* base) {
    // Keep the full single-player dictionary; the optional HD pack still overrides it.
    if (ctx.esi == 1) ReplaceLiteral(ctx,base,1,0);
}
void DarkwatchCoopParticipants(X86Context& ctx, uint8_t* base) {
    if (!base || ctx.ebp < 0x84 || !ctx.esi || ctx.esi > 0xFFFFFFFC ||
        ctx.ebx != 0 || (ctx.edi != 0 && ctx.edi != 0x20) ||
        ctx.eax != ctx.ebp-0xC || ctx.esp != ctx.ebp-0x84 ||
        !mem::IsCommitted(ctx.esi) || !mem::IsCommitted(ctx.esi+3) ||
        !mem::IsCommitted(ctx.ebp-0xC) || !mem::IsCommitted(ctx.ebp-5)) return;
    uint32_t vtable, count;
    std::memcpy(&vtable,base+ctx.esi,4);
    std::memcpy(&count,base+ctx.ebp-8,4);
    if (vtable != 0x429D38 || base[ctx.ebp-0xC] != 0xF || count != 4) return;
    // This page creates two players; unused ports must not trigger disconnect prompts.
    base[ctx.ebp-0xC] = 3;
    count = 2;
    std::memcpy(base+ctx.ebp-8,&count,4);
}
namespace darkwatch {
void ResetCoopInput() { input::SetCoopKeyboard(false); }
}
