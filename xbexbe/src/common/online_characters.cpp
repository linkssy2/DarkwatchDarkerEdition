#include "online_characters.h"
#include "online_area_travel.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

#ifndef XBE_RELEASE
#include <cstdio>
#include <cstdlib>
#include <cstring>

extern bool DarkwatchOnlineCharacterContext(const X86Context&, const uint8_t*, uint32_t, uint32_t);
extern bool DarkwatchOnlineCharacterWireEnabled(const X86Context&, const uint8_t*);
extern void DarkwatchOnlineEventRecord(const char*, uint32_t, uint32_t, uint32_t);
X86_EXTERN_FUNC(__imp__sub_001C2FB9);
X86_EXTERN_FUNC(__imp__sub_001C2FD4);

namespace {
constexpr uint32_t kMagic = 0x44574350, kVersion = 2, kUnknown = ~0u;
struct Selection {
    uint32_t session = 0, game = 0, local = 0, peer = 0;
    unsigned ordinal = 0;
    uint32_t choices[2]{kUnknown, kUnknown}, acknowledgment = kUnknown;
    bool dirty = false;
};
Selection selection;
struct Pending { uint32_t session = 0, peer = 0, choice = kUnknown, ack = kUnknown; } pending;
bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    if (base != kernel::g_base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~uint64_t(mem::kPage - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
uint32_t Word(const uint8_t* base, uint64_t at) {
    uint32_t value = 0;
    if (Span(base, at, 4)) std::memcpy(&value, base + at, 4);
    return value;
}
bool PlayerObject(const uint8_t* base, uint32_t object) {
    const auto table = Word(base, object);
    // The title's derived PlayerDO retains the base field codec (native 1C5DE7).
    return Span(base, object, 0xD8) && (table == 0x439B48 || table == 0x439CD8);
}
bool Context(const X86Context& ctx, const uint8_t* base) {
    return selection.session && DarkwatchOnlineCharacterContext(ctx, base, selection.game, selection.session);
}
[[noreturn]] void Failed(uint32_t reason, uint32_t value) {
    DarkwatchOnlineEventRecord("campaign-character-contract-failed", reason, value, selection.session);
    std::fputs("Online character agreement failed; both peers need the same test build.\n", stderr);
    std::fflush(stderr);
    // shortcut: private diagnostic abort; expose this as a lobby error before public online play.
    std::_Exit(3);
}
bool Field(const X86Context& ctx, const uint8_t* base, uint32_t& object) {
    if (!DarkwatchOnlineCharacterWireEnabled(ctx, base)) return false;
    object = Word(base, uint64_t(ctx.esp) + 4);
    if (!Span(base, ctx.esp, 32) || !PlayerObject(base, object) ||
        Word(base, uint64_t(ctx.esp) + 8) != object + 0x44 || Word(base, uint64_t(ctx.esp) + 12) != 1 ||
        !Word(base, object + 0xC) || !Word(base, object + 0x2C) ||
        ctx.esp < 0x1000 || !Span(base, ctx.esp - 0x1000, 0x1000)) {
        DarkwatchOnlineEventRecord("campaign-character-field-args", Word(base, ctx.esp), Word(base, uint64_t(ctx.esp) + 8), Word(base, uint64_t(ctx.esp) + 12));
        DarkwatchOnlineEventRecord("campaign-character-field-object", Word(base, object), Word(base, uint64_t(object) + 0xC), Word(base, uint64_t(object) + 0x2C));
        Failed(1, object);
    }
    return true;
}
void Receive(uint32_t peer, uint32_t choice, uint32_t ack) {
    const auto previous = selection.choices[1 - selection.ordinal];
    if (!peer || peer == selection.local || (selection.peer && peer != selection.peer) ||
        choice >= darkwatch::settings::kCharacterCount || (previous != kUnknown && previous != choice) ||
        (ack != kUnknown && ack != selection.choices[selection.ordinal])) Failed(5, choice);
    selection.peer = peer; selection.choices[1 - selection.ordinal] = choice;
    // A stale initial publication cannot revoke an acknowledgment already received.
    if (ack != kUnknown) selection.acknowledgment = ack;
    selection.dirty |= previous == kUnknown;
    DarkwatchOnlineEventRecord("campaign-character-received", choice, ack, peer);
}
}

void DarkwatchOnlineCharactersBegin(uint32_t session, uint32_t game, uint32_t local, unsigned ordinal) {
    selection = {};
    DarkwatchOnlineAreaBegin(session, game, ordinal);
    if (!session || !game || !local || ordinal > 1) return;
    selection.session = session; selection.game = game; selection.local = local; selection.ordinal = ordinal;
    selection.choices[ordinal] = unsigned(darkwatch::settings::configured_character(0));
    if (pending.session == session) Receive(pending.peer, pending.choice, pending.ack);
    pending = {};
}
bool DarkwatchOnlineCharactersReady() {
    return selection.session && selection.choices[0] < darkwatch::settings::kCharacterCount &&
        selection.choices[1] < darkwatch::settings::kCharacterCount &&
        selection.acknowledgment == selection.choices[selection.ordinal];
}
bool DarkwatchOnlineCharacterChoices(const X86Context& ctx, const uint8_t* base, uint32_t game,
    std::array<darkwatch::settings::Character, 2>& choices, unsigned& local) {
    if (game != selection.game || !Context(ctx, base) || !DarkwatchOnlineCharactersReady()) return false;
    choices = {darkwatch::settings::Character(selection.choices[0]), darkwatch::settings::Character(selection.choices[1])};
    local = selection.ordinal;
    return true;
}
void DarkwatchOnlineCharactersTick(const X86Context& ctx, uint8_t* base, uint32_t object) {
    if (!Context(ctx, base)) return;
    selection.dirty |= DarkwatchOnlineAreaTick(ctx, base);
    if (!selection.dirty) return;
    if (!PlayerObject(base, object) || Word(base, object + 0xC) != selection.local)
        Failed(2, object);
    selection.dirty = false;
    X86Context call = ctx; call.ecx = object;
    kernel::CallGuest(call, 0x16C250, {object + 0x44});
}

// Extend the native PlayerDO field codec, without changing any original field or user preference.
X86_FUNC(sub_001C2FB9) {
    uint32_t object = 0;
    const bool active = Field(ctx, base, object);
    const auto stream = active ? Word(base, uint64_t(ctx.esp) + 24) : 0;
    __imp__sub_001C2FB9(ctx, base);
    if (!active) return;
    if (!Context(ctx, base) || Word(base, object + 0xC) != selection.local || !Span(base, stream, 0x10)) Failed(3, object);
    uint32_t packet[]{kMagic, kVersion, selection.choices[selection.ordinal], selection.choices[1 - selection.ordinal], 0, 0, 0};
    DarkwatchOnlineAreaWrite(packet + 4);
    X86Context call = ctx;
    for (auto value : packet) { call.ecx = stream; kernel::CallGuest(call, 0x173A10, {value}); }
    DarkwatchOnlineEventRecord("campaign-character-sent", packet[2], packet[3], Word(base, object + 0xC));
}
X86_FUNC(sub_001C2FD4) {
    uint32_t object = 0;
    const bool active = Field(ctx, base, object);
    const auto stream = active ? Word(base, uint64_t(ctx.esp) + 16) : 0;
    __imp__sub_001C2FD4(ctx, base);
    if (!active) return;
    const auto peer = Word(base, object + 0xC), buffer = Word(base, stream), offset = Word(base, uint64_t(stream) + 4);
    const auto bytes = Word(base, uint64_t(buffer) + 0xC);
    if (!Span(base, stream, 0x10) || !Span(base, buffer, 0x10) || offset > bytes || bytes - offset < 28 ||
        !Span(base, uint64_t(Word(base, buffer + 8)) + offset, 28)) Failed(4, bytes);
    uint32_t packet[7]{};
    X86Context call = ctx; const auto temporary = ctx.esp - 128; call.esp = temporary - 32;
    for (auto& value : packet) {
        call.ecx = stream; kernel::CallGuest(call, 0x173530, {temporary}); value = Word(base, temporary);
    }
    if (packet[0] != kMagic || packet[1] != kVersion || packet[2] >= darkwatch::settings::kCharacterCount ||
        (packet[3] != kUnknown && packet[3] >= darkwatch::settings::kCharacterCount)) Failed(5, packet[2]);
    const auto session = Word(base, 0x4AF628);
    if (!session) Failed(6, object);
    if (session != selection.session) {
        if (packet[4] || packet[5] || packet[6]) Failed(6, object);
        pending = {session, peer, packet[2], packet[3]};
        return;
    }
    Receive(peer, packet[2], packet[3]);
    DarkwatchOnlineAreaReceive(packet + 4);
}
#endif
