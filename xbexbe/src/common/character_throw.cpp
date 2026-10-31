#include "character_runtime.h"
#include "character_voice_diagnostic.h"
#include "cpu/x86_ops.h"
#include "kernel/kernel.h"
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_00207F60);

namespace darkwatch::throw_voice {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage) - 1); page < at + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base + at, sizeof(value)); return true;
}
bool Name(const uint8_t* base, uint64_t at, const char* expected) {
    uint32_t ref = 0; const size_t size = std::strlen(expected) + 1;
    if (!Read(base, at, ref) || !ref || !Span(base, uint64_t(ref) + 2, size)) return false;
    for (size_t i = 0; i < size; ++i) {
        char ch = char(base[uint64_t(ref) + 2 + i]);
        if (ch >= 'a' && ch <= 'z') ch -= 'a' - 'A';
        if (ch != expected[i]) return false;
    }
    return true;
}
bool Component(const uint8_t* base, uint32_t actor, uint32_t type, uint32_t& found) {
    uint16_t count = 0; uint32_t rows = 0; found = 0;
    if (!Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, rows) || !Span(base, rows, count * 8)) return false;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t item = 0, table = 0, owner = 0;
        if (!Read(base, uint64_t(rows) + i * 8 + 4, item) || !Read(base, item, table)) return false;
        if (table != type) continue;
        if (found || !Read(base, uint64_t(item) + 12, owner) || owner != actor) return false;
        found = item;
    }
    return found != 0;
}
bool Request(const X86Context& ctx, const uint8_t* base, uint32_t& weapon, uint32_t& component, uint32_t& player) {
    uint32_t caller = 0, speaker = 0, rows = 0, bank = 0, cue = 0, mapped_bank = 0, mapped_cue = 0;
    uint16_t count = 0;
    // 2083E2's effects lane passes its speaker state in ESI and matching map row
    // in EDI. Both the reused-slot and newly allocated-slot calls have this ABI.
    if (base != kernel::g_base || !Read(base, ctx.esp, caller) ||
        (caller != 0x2086D7 && caller != 0x20877B) || ctx.esi < 0x48 ||
        !Span(base, ctx.esp, 48) || !Name(base, uint64_t(ctx.esp) + 8, "PLAYER") ||
        (!Name(base, uint64_t(ctx.esp) + 12, "DYN_THROW") &&
         !Name(base, uint64_t(ctx.esp) + 12, "DYN_THROW2")) ||
        !Read(base, uint64_t(ctx.esi) + 0x60, count) || !count || count > 256 ||
        !Read(base, uint64_t(ctx.esi) + 0x64, rows) || !Span(base, rows, count * 16) ||
        ctx.edi < rows || uint64_t(ctx.edi) >= uint64_t(rows) + count * 16 || (ctx.edi - rows) % 16 ||
        !Name(base, ctx.edi, "FIRE") ||
        !Read(base, uint64_t(ctx.esp) + 8, bank) || !Read(base, uint64_t(ctx.esp) + 12, cue) ||
        !Read(base, uint64_t(ctx.edi) + 4, mapped_bank) || mapped_bank != bank ||
        !Read(base, uint64_t(ctx.edi) + 8, mapped_cue) || mapped_cue != cue ||
        !Read(base, uint64_t(ctx.esi) - 0x48 + 12, weapon) ||
        !Component(base, weapon, 0x43B114, speaker) || speaker != ctx.esi - 0x48 ||
        !Component(base, weapon, 0x418390, component) ||
        !Read(base, uint64_t(component) + 0x58, player)) return false;
    return true;
}
bool Grenade(const uint8_t* base, uint32_t weapon, uint32_t component) {
    // Keep the actor template and native inventory-name getter (+24) consistent.
    for (const char* name : {"DYNAMITE", "DYNAMITE_MP", "SPLITTERGRENADES", "SPLITTERGRENADES_MP"})
        if (Name(base, uint64_t(weapon) + 0x50, name) && Name(base, uint64_t(component) + 0x24, name)) return true;
    return false;
}
} // namespace darkwatch::throw_voice

X86_FUNC(sub_00207F60) {
    namespace voice = darkwatch::throw_voice;
    uint32_t weapon = 0, component = 0, player = 0;
    if (!voice::Request(ctx, base, weapon, component, player)) { __imp__sub_00207F60(ctx, base); return; }
    DarkwatchCharacterVoiceThrow(ctx, base, component, player);
    const bool tala = DarkwatchCharacterIsTalaPlayer(base, player);
    if (!voice::Name(base, uint64_t(ctx.esp) + 12, "DYN_THROW2") || !voice::Grenade(base, weapon, component) ||
        (!tala && !DarkwatchCharacterIsCassidyPlayer(base, player)) ||
        !DarkwatchCharacterAudioReady(base, nullptr, tala) ||
        ctx.esp < 0x2000 || !voice::Span(base, uint64_t(ctx.esp) - 0x2000, 0x2000)) {
        __imp__sub_00207F60(ctx, base); return;
    }
    // DYN_THROW2 is the separate variable effort track. DYN_THROW, projectile
    // sounds, animation, volume, position and native sound-handle ownership stay
    // on the original path. No speaker map or shared soundbank is modified.
    const uint32_t scratch = ctx.esp - 0x100, arguments = ctx.esp + 8;
    uint32_t original[2], replacement[2]{};
    std::memcpy(original, base + arguments, sizeof(original));
    const char* names[]{tala ? "TALA" : "CASSIDY", tala ? "TALA_ATTACK" : "CASS_ATTK"};
    X86Context call = ctx; call.esp = scratch;
    for (unsigned i = 0; i < 2; ++i) {
        std::memcpy(base + scratch + 16, names[i], std::strlen(names[i]) + 1);
        call.ecx = scratch;
        kernel::CallGuest(call, 0x138FA, {scratch + 16});
        std::memcpy(&replacement[i], base + scratch, 4);
    }
    if (replacement[0] && replacement[1]) std::memcpy(base + arguments, replacement, sizeof(replacement));
    __imp__sub_00207F60(ctx, base);
    std::memcpy(base + arguments, original, sizeof(original));
    // The sound creation call consumes borrowed string handles synchronously.
    // It may reuse our scratch area; restore each owned reference before release.
    for (const auto ref : replacement) if (ref) {
        std::memcpy(base + scratch, &ref, 4); call.ecx = scratch;
        kernel::CallGuest(call, 0x11C1A, {});
    }
}
