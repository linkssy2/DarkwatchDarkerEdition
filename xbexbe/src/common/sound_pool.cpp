#include "sound_pool.h"
#include "cpu/x86_ops.h"

using namespace darkwatch::sound_pool;
namespace {
constexpr uint32_t kRelocation = kOffset - kOriginalOffset;
}

// Append the enlarged pool so every existing manager field keeps its address.
void DarkwatchSoundPoolAllocate(X86Context& ctx, uint8_t* base) {
    X86_MEM32(ctx.esp) = kManagerSize;
}

void DarkwatchSoundPoolArray(X86Context& ctx, uint8_t* base) {
    ctx.eax += kRelocation;
    X86_MEM32(ctx.esp + 4) = kCount;
}

void DarkwatchSoundPoolCleanup(X86Context& ctx, uint8_t* base) {
    ctx.edi += kRelocation;
    X86_MEM32(ctx.esp) = kCount;
}

void DarkwatchSoundPoolEsi(X86Context& ctx, uint8_t*) { ctx.esi += kRelocation; }
void DarkwatchSoundPoolEcx(X86Context& ctx, uint8_t*) { ctx.ecx += kRelocation; }
void DarkwatchSoundPoolEdi(X86Context& ctx, uint8_t*) { ctx.edi += kRelocation; }
bool DarkwatchSoundPoolMore(X86Context& ctx, uint8_t*) { return ctx.ebx < kCount; }

// XACT reserves stream units separately from its 64 spatial-source records.
void DarkwatchSoundPoolStreams(X86Context& ctx, uint8_t* base) {
    X86_MEM32(ctx.ebp - 0x24) = kVoiceCount;
    X86_MEM32(ctx.ebp - 0x1C) = kStreamCount;
}
