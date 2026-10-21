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
namespace darkwatch {
void ResetCoopInput() { input::SetCoopKeyboard(false); }
}
