#include "character_melee.h"
#include "character_runtime.h"
#include "character_voice_diagnostic.h"
#include "kernel/kernel.h"
#include <cstring>

namespace darkwatch::melee {
bool Span(const uint8_t* base, uint64_t address, uint64_t bytes) {
    if (!base || !address || !bytes || address + bytes > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~uint64_t(mem::kPage - 1); page < address + bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
bool Read(const uint8_t* base, uint64_t address, uint32_t& value) {
    if (!Span(base, address, sizeof(value))) return false;
    std::memcpy(&value, base + address, sizeof(value)); return true;
}
}

bool DarkwatchCharacterMelee(X86Context& ctx, uint8_t* base) {
    DarkwatchCharacterVoiceMelee(ctx, base);
    uint32_t component, weapon, argument, event, actor;
    // The only original caller saves the weapon component in ESI before 1F43E.
    // Replace this start sound only; native animation and hit sounds stay intact.
    if (base != kernel::g_base || ctx.ebp < 0x14 ||
        !darkwatch::melee::Read(base, uint64_t(ctx.ebp) - 0x14, component) ||
        !darkwatch::melee::Read(base, uint64_t(component) + 0xC, weapon) || weapon != ctx.esi ||
        !darkwatch::melee::Read(base, ctx.esp, argument) || argument != weapon ||
        !darkwatch::melee::Read(base, uint64_t(ctx.ebp) - 8, event) ||
        !darkwatch::melee::Read(base, uint64_t(event) + 4, event) || event != 0x17C ||
        !darkwatch::melee::Read(base, uint64_t(component) + 0x58, actor) ||
        ctx.esp < 0x2000 || !darkwatch::melee::Span(base, uint64_t(ctx.esp) - 0x2000, 0x2000)) return false;
    const bool tala = DarkwatchCharacterIsTalaPlayer(base, actor);
    if ((!tala && !DarkwatchCharacterIsCassidyPlayer(base, actor)) ||
        !DarkwatchCharacterAudioReady(base, nullptr, tala)) return false;

    const uint32_t scratch = ctx.esp - 0x100;
    const char* bank = tala ? "TALA" : "CASSIDY";
    const char* cue = tala ? "TALA_ATTACK" : "CASS_ATTK";
    std::memcpy(base + scratch + 16, bank, std::strlen(bank) + 1);
    std::memcpy(base + scratch + 32, cue, std::strlen(cue) + 1);
    X86Context call = ctx;
    call.esp = scratch;
    call.ecx = scratch;
    kernel::CallGuest(call, 0x138FA, {scratch + 16});
    call.ecx = scratch + 4;
    kernel::CallGuest(call, 0x138FA, {scratch + 32});
    // 15201 delivers locally; 1D9017 only sends a network replication wrapper.
    const uint32_t result = scratch + 64;
    // Mode zero is native playback; mode one only prepares a cue.
    kernel::CallGuest(call, 0x15201, {result, actor, scratch, scratch + 4, 0, 0x3F800000, 0, 1});
    std::memcpy(&call.ecx, base + result + 4, sizeof(call.ecx));
    uint32_t sound, status;
    std::memcpy(&sound, base + result, sizeof(sound));
    std::memcpy(&status, base + result + 16, sizeof(status));
    const bool created = sound != 0 && call.ecx != 0 && status == 0;
    if (call.ecx) kernel::CallGuest(call, 0x1CA04, {result});
    call.ecx = scratch;
    kernel::CallGuest(call, 0x11C1A, {});
    call.ecx = scratch + 4;
    kernel::CallGuest(call, 0x11C1A, {});
    // Keep the original mixed weapon sample if no character sound was created.
    return created;
}
