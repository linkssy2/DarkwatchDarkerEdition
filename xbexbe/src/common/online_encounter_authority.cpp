#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

#ifndef XBE_RELEASE
#include <cstring>

extern bool DarkwatchOnlineCampaignLoadContext(const X86Context&, const uint8_t*,
                                              uint32_t&, uint32_t&, uint32_t&, uint32_t&);
extern void DarkwatchOnlineEventRecord(const char*, uint32_t, uint32_t, uint32_t);
X86_EXTERN_FUNC(__imp__sub_0021F974);
X86_EXTERN_FUNC(__imp__sub_0022AA64);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    if (base != kernel::g_base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~uint64_t(mem::kPage - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
uint32_t Word(const uint8_t* base, uint64_t at) {
    uint32_t result = 0;
    if (Span(base, at, 4)) std::memcpy(&result, base + at, 4);
    return result;
}
bool Name(const uint8_t* base, uint32_t token, const char* text) {
    const auto size = uint32_t(std::strlen(text) + 1);
    return token && Span(base, uint64_t(token) + 2, size) && !std::memcmp(base + token + 2, text, size);
}
uint32_t ClientHostOwner(const X86Context& ctx, uint8_t* base) {
    uint32_t game = 0, session = 0, local = 0, remote = 0;
    if (!DarkwatchOnlineCampaignLoadContext(ctx, base, game, session, local, remote) ||
        Word(base, uint64_t(Word(base, 0x4ACFBC)) + 8) != 5 ||
        !Name(base, Word(base, game), "WrongTrain")) return false;
    X86Context call = ctx;
    return (kernel::CallGuest(call, 0x186A30, {}) & 255) == 2 ? remote : 0;
}
bool EnrolledNames(const uint8_t* base, uint32_t type, uint32_t name) {
    // shortcut: only the authored opening encounter; enroll later encounters after their event audit.
    return (Name(base, type, "DwOnlineProofReaper") &&
            (Name(base, name, "IntroReaper") || Name(base, name, "BattleReaper1") || Name(base, name, "BattleReaper2"))) ||
           (Name(base, type, "DwOnlineProofRegulator") &&
            (Name(base, name, "Regulator1") || Name(base, name, "Regulator_Detpack")));
}
bool Enrolled(const uint8_t* base, uint32_t layout) {
    return Span(base, layout, 0x10) && EnrolledNames(base, Word(base, layout), Word(base, layout + 8));
}
unsigned Score(const uint8_t* base, uint32_t event) {
    if (!Span(base, event, 0x74) || Word(base, event) != 0x440614) return 0;
    const auto config = Word(base, event + 0x54);
    if (!Span(base, config, 0x10) || Word(base, config) != 0x423340) return 0;
    uint16_t count = 0; std::memcpy(&count, base + config + 8, 2);
    const auto args = Word(base, config + 12), script = Word(base, config + 4);
    if ((count != 2 && count != 5) || !Span(base, args, count * 4)) return 0;
    const bool reapers = Name(base, Word(base, args), "BattleReaper1") &&
                         Name(base, Word(base, args + 4), "BattleReaper2");
    if (count == 2 && Name(base, script, "Scripts\\SpawnActor")) {
        if (reapers) return 1;
        if (Name(base, Word(base, args), "Regulator1") &&
            Name(base, Word(base, args + 4), "Regulator_Detpack")) return 2;
    }
    return count == 5 && reapers && Name(base, script, "Scripts\\WatchMobs_PlayFile_event") &&
           Name(base, Word(base, args + 8), "Delay0.5") &&
           Name(base, Word(base, args + 12), "Scripts/ActivateTrigger") &&
           Name(base, Word(base, args + 16), "Minimatic_Revolver") ? 3 : 0;
}
}

void DarkwatchOnlinePrepareNpcDeath(const X86Context& ctx, uint8_t* base) {
    const auto actor = ctx.ecx, object = ctx.edi, message = Word(base, uint64_t(ctx.esp) + 4);
    if (Word(base, ctx.esp) != 0x24A82B || !Span(base, message, 8) ||
        Word(base, message) != 0x41E948 || Word(base, message + 4) != 0x139 ||
        !Span(base, actor, 0x9C) || !Span(base, object, 0x3F8) ||
        Word(base, object) != 0x425CD0 || Word(base, object + 0x68) != actor ||
        !EnrolledNames(base, Word(base, actor + 0x50), Word(base, actor + 0x54))) return;
    const auto host = ClientHostOwner(ctx, base);
    if (!host || Word(base, object + 0xC) != host) return;
    uint16_t count = 0; std::memcpy(&count, base + actor + 0x60, 2);
    const auto parts = Word(base, actor + 0x64);
    if (!count || count > 128 || !Span(base, parts, count * 8)) return;
    uint32_t network = 0;
    for (unsigned i = 0; i < count; ++i) {
        const auto part = Word(base, parts + i * 8 + 4);
        if (!Span(base, part, 0x10) || Word(base, part + 0xC) != actor) return;
        if (Word(base, part) != 0x4432DC) continue;
        if (network || !Span(base, part, 0x24) || Word(base, part + 0x1C) != object) return;
        network = part;
    }
    if (!network || (Word(base, actor + 0x90) & 2)) return;
    // ActorDO bypasses Health::Die, which sets this bit before death reactions run.
    const auto flags = Word(base, actor + 0x90) | 2u;
    std::memcpy(base + actor + 0x90, &flags, sizeof(flags));
    DarkwatchOnlineEventRecord("campaign-npc-death-state", actor, object, flags);
}

X86_FUNC(sub_0021F974) {
    const auto layout = Word(base, uint64_t(ctx.esp) + 4);
    if (Enrolled(base, layout) && ClientHostOwner(ctx, base)) {
        DarkwatchOnlineEventRecord("campaign-spawn-await-host", layout, Word(base, layout + 8), Word(base, ctx.esp));
        ctx.eax = 0; ctx.esp += 20;
        return;
    }
    __imp__sub_0021F974(ctx, base);
}
X86_FUNC(sub_0022AA64) {
    const auto kind = Score(base, ctx.ecx);
    if (kind && ClientHostOwner(ctx, base)) {
        // Release the unstarted coroutine, then use native registration and no-coroutine completion.
        X86Context call = ctx;
        kernel::CallGuest(call, 0x22A954, {});
        DarkwatchOnlineEventRecord("campaign-score-await-host", kind, ctx.ecx, Word(base, ctx.esp));
    }
    __imp__sub_0022AA64(ctx, base);
}
#endif
