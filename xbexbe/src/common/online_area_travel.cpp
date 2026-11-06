#include "online_area_travel.h"
#include "online_area_destinations.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

#ifndef XBE_RELEASE
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>

extern bool DarkwatchOnlineCharacterContext(const X86Context&, const uint8_t*, uint32_t, uint32_t);
extern bool DarkwatchOnlineCampaignReady(const X86Context&, const uint8_t*);
extern bool DarkwatchOnlineStoryDrained();
extern void DarkwatchOnlineEventRecord(const char*, uint32_t, uint32_t, uint32_t);
X86_EXTERN_FUNC(__imp__sub_000C58BB);
X86_EXTERN_FUNC(__imp__sub_00104BF0);

namespace {
using Clock = std::chrono::steady_clock;
struct Travel {
    uint32_t session = 0, game = 0, generation = 0, phase = 0, destination = 0, peer_phase = 0, written = 0;
    unsigned ordinal = 0;
    bool requested = false, applied = false;
    Clock::time_point started{}, sent{};
};
Travel travel;
bool replay = false;
constexpr uint32_t kChapter = 0x100, kDropWeapons = 0x200, kIndex = 0xFF;
bool ValidDestination(uint32_t value) {
    const auto index = value & kIndex;
    if (!index || index > std::size(kOnlineAreas) || value & ~(kIndex | kChapter | kDropWeapons)) return false;
    if (!(value & kChapter)) return !(value & kDropWeapons);
    return index == 1 || std::strcmp(kOnlineAreas[index - 1].level, kOnlineAreas[index - 2].level);
}
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
bool Equals(const uint8_t* base, uint32_t ref, const char* text) {
    const auto token = Word(base, ref);
    const auto n = std::strlen(text) + 1;
    return token && Span(base, uint64_t(token) + 2, uint32_t(n)) && !std::memcmp(base + token + 2, text, n);
}
bool Context(const X86Context& ctx, const uint8_t* base) {
    return travel.session && DarkwatchOnlineCharacterContext(ctx, base, travel.game, travel.session);
}
[[noreturn]] void Failed(unsigned reason) {
    DarkwatchOnlineEventRecord("campaign-area-failed", reason, travel.generation, travel.phase);
    std::fputs("Private online area handoff failed; see the diagnostic trace.\n", stderr);
    std::fflush(stderr);
    // shortcut: diagnostic abort; add recoverable lobby errors before public online play.
    std::_Exit(3);
}
void Phase(uint32_t phase) {
    travel.phase = phase; travel.sent = {};
    DarkwatchOnlineEventRecord("campaign-area-phase", travel.generation, phase, travel.destination);
}
void Request(uint32_t destination) {
    if (!travel.ordinal) {
        if (travel.requested && !travel.applied) {
            if (destination != travel.destination) Failed(6);
        } else {
            if (travel.generation == ~0u) Failed(6);
            ++travel.generation; travel.destination = destination; travel.peer_phase = travel.written = 0;
            travel.requested = true; travel.applied = false; travel.started = Clock::now(); Phase(1);
        }
    } else {
        DarkwatchOnlineEventRecord("campaign-area-await-host", destination, travel.generation, travel.phase);
    }
}
void Load(const X86Context& ctx, uint8_t* base) {
    const auto& destination = kOnlineAreas[(travel.destination & kIndex) - 1];
    const bool chapter = travel.destination & kChapter;
    const auto loader = Word(base, 0x4ACFBC);
    if (ctx.esp < 2048 || !Span(base, ctx.esp - 2048, 2048) || !Span(base, loader, 0x74) ||
        Word(base, loader + 8) != 5 || (!chapter && !Equals(base, travel.game, destination.level))) Failed(4);
    // Retain a native title string through C58BB, then release the temporary after return.
    const auto temporary = ctx.esp - 256;
    uint8_t saved[128]; std::memcpy(saved, base + temporary, sizeof(saved));
    std::memset(base + temporary, 0, sizeof(saved));
    const auto name = chapter ? destination.level : destination.slot;
    const auto length = std::strlen(name) + 1;
    if (length > 120) Failed(4);
    std::memcpy(base + temporary + 8, name, length);
    auto call = ctx; call.esp = temporary - 256; call.ecx = temporary;
    if (chapter) {
        // Execute the original EndLevel action on each owner after agreement, including weapon/drop/save rules.
        const auto description = kernel::CallGuest(call, 0xE0C6B, {});
        if (!Span(base, description, 12) || Word(base, description) != 0x424BF0) Failed(8);
        call.ecx = description + 4; kernel::CallGuest(call, 0x138FA, {temporary + 8});
        base[description + 8] = bool(travel.destination & kDropWeapons);
        call.ecx = description;
        const auto action = kernel::CallGuest(call, 0x104BAE, {});
        if (!Span(base, action, 0x90) || Word(base, action) != 0x42F008 || Word(base, action + 0x54) != description) Failed(8);
        replay = true; call.ecx = action; kernel::CallGuest(call, 0x104BF0, {}); replay = false;
        call.ecx = action; kernel::CallGuest(call, 0x104BCE, {1});
        call.ecx = description; kernel::CallGuest(call, 0xB9491, {1});
    } else {
      kernel::CallGuest(call, 0x138FA, {temporary + 8});
      if (travel.ordinal) {
        const auto manager = kernel::CallGuest(call, 0x12542, {});
        call.ecx = manager;
        const auto slot = kernel::CallGuest(call, 0x1D6CBE, {temporary});
        if (slot == ~0u) Failed(7);
        // Client also needs the native player-state capture and area-change flag.
        replay = true; call.ecx = travel.game;
        kernel::CallGuest(call, 0xC3B92, {slot}); replay = false;
      } else {
        call.ecx = loader;
        kernel::CallGuest(call, 0xC58BB, {travel.game, temporary, 1});
      }
      call.ecx = temporary; kernel::CallGuest(call, 0x11C1A, {});
    }
    std::memcpy(base + temporary, saved, sizeof(saved));
    travel.applied = true;
    DarkwatchOnlineEventRecord("campaign-area-load", travel.generation, travel.destination, travel.ordinal);
}
}

void DarkwatchOnlineAreaBegin(uint32_t session, uint32_t game, unsigned ordinal) {
    travel = {}; replay = false; travel.session = session; travel.game = game; travel.ordinal = ordinal;
}
void DarkwatchOnlineAreaWrite(uint32_t* words) {
    words[0] = travel.generation; words[1] = travel.phase; words[2] = travel.destination;
    travel.written = travel.phase;
}
void DarkwatchOnlineAreaReceive(const uint32_t* words) {
    const auto generation = words[0], phase = words[1], destination = words[2];
    if (!generation && !phase && !destination) return;
    if (!travel.session || !generation || !ValidDestination(destination) ||
        (travel.ordinal == 0 ? phase != 2 && phase != 4 : phase != 1 && phase != 3)) Failed(1);
    if (generation < travel.generation) return;
    if (generation > travel.generation) {
        if (!travel.ordinal || generation != travel.generation + 1 || phase != 1 ||
            (travel.generation && !travel.applied)) Failed(2);
        travel.generation = generation; travel.destination = destination; travel.peer_phase = 0;
        travel.phase = travel.written = 0; travel.requested = true; travel.applied = false;
        travel.started = Clock::now();
    }
    if (destination != travel.destination) Failed(2);
    if (phase > travel.peer_phase) travel.peer_phase = phase;
}
bool DarkwatchOnlineAreaTick(const X86Context& ctx, uint8_t* base) {
    if (!travel.requested || !Context(ctx, base)) return false;
    if (!travel.applied && Clock::now() - travel.started > std::chrono::minutes(5)) Failed(3);
    if (!travel.applied && DarkwatchOnlineCampaignReady(ctx, base) && DarkwatchOnlineStoryDrained()) {
        if (!(travel.destination & kChapter) && !Equals(base, travel.game, kOnlineAreas[travel.destination - 1].level)) Failed(4);
        if (travel.ordinal == 0 && travel.phase == 1 && travel.peer_phase == 2) Phase(3);
        if (travel.ordinal == 1 && !travel.phase && travel.peer_phase == 1) Phase(2);
        if (travel.ordinal == 1 && travel.phase == 2 && travel.peer_phase == 3) Phase(4);
        if ((travel.ordinal == 0 && travel.phase == 3 && travel.peer_phase == 4) ||
            (travel.ordinal == 1 && travel.phase == 4 && travel.written == 4)) Load(ctx, base);
    }
    // PlayerDO survives world teardown; keep the acknowledgment available during both loads.
    if (travel.phase && Clock::now() - travel.sent >= std::chrono::milliseconds(100)) {
        travel.sent = Clock::now(); return true;
    }
    return false;
}

X86_FUNC(sub_000C58BB) {
    const auto caller = Word(base, ctx.esp), mode = Word(base, uint64_t(ctx.esp) + 12);
    if (replay || caller != 0xC3BE3 || mode != 1 || !Context(ctx, base)) {
        __imp__sub_000C58BB(ctx, base); return;
    }
    const auto level = Word(base, uint64_t(ctx.esp) + 4), slot = Word(base, uint64_t(ctx.esp) + 8);
    if (ctx.ecx != Word(base, 0x4ACFBC) || !DarkwatchOnlineCampaignReady(ctx, base)) Failed(4);
    uint32_t destination = 0;
    for (unsigned i = 0; i < std::size(kOnlineAreas); ++i)
        if (Equals(base, level, kOnlineAreas[i].level) && Equals(base, slot, kOnlineAreas[i].slot)) destination = i + 1;
    if (!destination || !Equals(base, travel.game, kOnlineAreas[destination - 1].level)) Failed(5);
    Request(destination);
    ctx.esp += 16;
}
X86_FUNC(sub_00104BF0) {
    if (replay || !Context(ctx, base)) { __imp__sub_00104BF0(ctx, base); return; }
    const auto description = Word(base, uint64_t(ctx.ecx) + 0x54);
    if (!DarkwatchOnlineCampaignReady(ctx, base) || !Span(base, ctx.ecx, 0x90) ||
        Word(base, ctx.ecx) != 0x42F008 || !Span(base, description, 12) || Word(base, description) != 0x424BF0) Failed(8);
    uint32_t destination = 0;
    const bool next = !Word(base, description + 4) || Equals(base, description + 4, "");
    bool found_current = false;
    for (unsigned i = 0; i < std::size(kOnlineAreas); ++i) {
        if (!ValidDestination((i + 1) | kChapter)) continue;
        if (next ? found_current : Equals(base, description + 4, kOnlineAreas[i].level)) { destination = i + 1; break; }
        found_current |= Equals(base, travel.game, kOnlineAreas[i].level);
    }
    if (next && !destination) destination = 1; // Original chapter table wraps at the end.
    if (!destination) Failed(5);
    Request(destination | kChapter | (base[description + 8] ? kDropWeapons : 0));
    ctx.esp += 4;
}
#endif
