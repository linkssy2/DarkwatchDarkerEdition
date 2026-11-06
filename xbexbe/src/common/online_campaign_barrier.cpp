#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include "character_runtime.h"

#ifndef XBE_RELEASE
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>

extern bool DarkwatchOnlineCampaignLoadContext(const X86Context&, const uint8_t*,
                                              uint32_t&, uint32_t&, uint32_t&, uint32_t&);
extern void DarkwatchOnlineEventRecord(const char*, uint32_t, uint32_t, uint32_t);
X86_EXTERN_FUNC(__imp__sub_000C3E34);
X86_EXTERN_FUNC(__imp__sub_00246015);
X86_EXTERN_FUNC(__imp__sub_00246296);
extern bool DarkwatchOnlineCampaignTriggerContext(const X86Context&, const uint8_t*);
extern void DarkwatchOnlineStoryTick(const X86Context&, uint8_t*);
extern void DarkwatchOnlineStoryReset();

namespace {
using Clock = std::chrono::steady_clock;
constexpr uint32_t kControl = 0x7FFE, kMagic = 0x44435742, kVersion = 1;
struct Load {
    uint32_t session = 0, game = 0, generation = 0, level = 0, checkpoint = 0;
    uint32_t local = 0, remote = 0;
    bool loaded = false, received = false, acknowledged = false;
    bool agreed = false;
    unsigned attempts = 0;
    Clock::time_point started{}, sent{};
};
Load load;
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
void Put(uint8_t* base, uint32_t at, uint32_t value) { std::memcpy(base + at, &value, 4); }
bool Key(const uint8_t* base, uint32_t at, uint32_t& hash) {
    const auto token = Word(base, at);
    hash = 2166136261u;
    if (!token) return true;
    for (unsigned i = 2; i < 1026; ++i) {
        if (!Span(base, uint64_t(token) + i, 1)) return false;
        const auto c = base[token + i];
        if (!c) return true;
        hash = (hash ^ c) * 16777619u;
    }
    return false;
}
bool Context(const X86Context& ctx, const uint8_t* base) {
    uint32_t game = 0, session = 0, local = 0, remote = 0, level = 0, checkpoint = 0;
    return load.loaded && DarkwatchOnlineCampaignLoadContext(ctx, base, game, session, local, remote) &&
        game == load.game && session == load.session && local == load.local && remote == load.remote &&
        Key(base, game, level) && Key(base, game + 4, checkpoint) &&
        level == load.level && checkpoint == load.checkpoint;
}
uint32_t PlayerObject(const uint8_t* base, bool local) {
    const auto records = Word(base, load.game + 0x54);
    if (Word(base, load.game + 0x44) != 2 || !Span(base, records, 2 * 0x130)) return 0;
    for (unsigned i = 0; i < 2; ++i) {
        const auto record = records + i * 0x130;
        if (bool(base[record + 0x128]) != local) continue;
        const auto actor = Word(base, record + 0x118), list = Word(base, uint64_t(actor) + 0x64);
        uint16_t count = 0;
        if (!Span(base, actor, 0x9C)) return 0;
        std::memcpy(&count, base + actor + 0x60, 2);
        if (!count || count > 128 || !Span(base, list, count * 8)) return 0;
        for (unsigned j = 0; j < count; ++j) {
            const auto part = Word(base, list + j * 8 + 4);
            if (Word(base, part) != 0x4432DC || Word(base, uint64_t(part) + 0xC) != actor) continue;
            const auto object = Word(base, uint64_t(part) + 0x1C);
            if (Span(base, object, 0x3F8) && Word(base, object) == 0x425CD0 &&
                Word(base, object + 0x68) == actor && Word(base, object + 0x2C) &&
                Word(base, object + 0xC) == (local ? load.local : load.remote)) return object;
        }
    }
    return 0;
}
[[noreturn]] void Failed(uint32_t reason) {
    DarkwatchOnlineEventRecord("campaign-load-barrier-failed", reason, load.generation, load.received | (load.acknowledged << 1));
    std::fputs("Online campaign load agreement failed; see the diagnostic trace.\n", stderr);
    std::fflush(stderr);
    // shortcut: private diagnostic abort; the public lobby must display a recoverable join error.
    std::_Exit(3);
}
bool SendPacket(const X86Context& ctx, uint8_t* base, uint32_t control,
                const uint32_t* packet, uint32_t size) {
    if (!Context(ctx, base) || !packet || !size || size > 128) return false;
    const auto object = PlayerObject(base, true);
    const auto attempt = ++load.attempts;
    if ((attempt & (attempt - 1)) == 0)
        DarkwatchOnlineEventRecord("campaign-load-send-attempt", object, load.local, load.remote);
    if (!object) return false;
    const auto temporary = ctx.esp - 256;
    X86Context call = ctx;
    call.esp = temporary - 32;
    auto invoke = [&](uint32_t fn, uint32_t self, std::initializer_list<uint32_t> args) {
        call.ecx = self; return kernel::CallGuest(call, fn, args);
    };
    // Native 24AC78 queues events until the object is distributed; a handle alone is insufficient.
    const auto distributed = invoke(0x16A480, object, {}) & 0xFF;
    if ((attempt & (attempt - 1)) == 0)
        DarkwatchOnlineEventRecord("campaign-load-send-distributed", object, distributed, base[object + 0x16]);
    if (!distributed) return false;
    std::memset(base + temporary + 160, 0, 12);
    Put(base, temporary + 172, Word(base, object + 0x2C));
    invoke(0x16E4A0, temporary + 160, {temporary + 172});
    const bool registered = Word(base, temporary + 160) == object;
    invoke(0x16E370, temporary + 160, {});
    if (!registered) {
        DarkwatchOnlineEventRecord("campaign-load-object-pending", object, Word(base, object + 0x2C), control);
        return false;
    }
    std::memcpy(base + temporary, packet, size);
    Put(base, temporary + 128, size);
    Put(base, temporary + 132, temporary);
    Put(base, temporary + 136, control);
    const auto request = invoke(0x16A080, 0, {0xC8});
    if (!request) Failed(1);
    invoke(0x170360, request, {0, 1});
    invoke(0x16F1A0, request, {0x206});
    // Original OneWayMessage copies the supplied bytes before dispatching its owned request.
    invoke(0x24B6C1, object, {request, temporary + 136, temporary + 128});
    return true;
}
void Send(const X86Context& ctx, uint8_t* base, uint32_t kind) {
    const uint32_t packet[]{kMagic, kVersion, load.generation, load.level, load.checkpoint, kind};
    SendPacket(ctx, base, kControl, packet, sizeof(packet));
}
}

bool DarkwatchOnlineStoryContext(const X86Context& ctx, const uint8_t* base,
                                uint32_t (&stamp)[3], uint32_t& remote) {
    if (!Context(ctx, base)) return false;
    stamp[0] = load.generation; stamp[1] = load.level; stamp[2] = load.checkpoint;
    remote = PlayerObject(base, false);
    return true;
}
bool DarkwatchOnlineSendStory(const X86Context& ctx, uint8_t* base, const uint32_t* packet, uint32_t size) {
    return SendPacket(ctx, base, 0x7FFD, packet, size);
}

bool DarkwatchOnlineCampaignLoaded(const X86Context& ctx, const uint8_t* base) {
    return Context(ctx, base);
}
bool DarkwatchOnlineCampaignReady(const X86Context& ctx, const uint8_t* base) {
    return Context(ctx, base) && load.received && load.acknowledged;
}
// Defer the whole scan: skipping only its action would still consume a one-shot entry.
#define CAMPAIGN_TRIGGER(entry, table) \
X86_FUNC(sub_##entry) { \
    if (Word(base, ctx.ecx) == table && DarkwatchOnlineCampaignTriggerContext(ctx, base) && \
        !DarkwatchOnlineCampaignReady(ctx, base)) { \
        static unsigned held = 0; \
        ++held; \
        if ((held & (held - 1)) == 0) \
            DarkwatchOnlineEventRecord("campaign-trigger-wait", ctx.ecx, table, held); \
        ctx.esp += 4; return; \
    } \
    __imp__sub_##entry(ctx, base); \
}
CAMPAIGN_TRIGGER(00246015, 0x4428EC)
CAMPAIGN_TRIGGER(00246296, 0x442904)
#undef CAMPAIGN_TRIGGER
void DarkwatchOnlineCampaignLoadTick(const X86Context& ctx, uint8_t* base) {
    if (!load.loaded) return;
    // Other callbacks and transient loader states must not discard the owning thread's agreement.
    if (!Context(ctx, base)) return;
    if (load.received && load.acknowledged) {
        if (!load.agreed) DarkwatchOnlineEventRecord("campaign-load-agreed", load.generation,
            uint32_t(std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - load.started).count()), PlayerObject(base, false));
        load.agreed = true;
        DarkwatchOnlineStoryTick(ctx, base);
        return;
    }
    if (Clock::now() - load.started > std::chrono::minutes(5)) Failed(4);
    if (Clock::now() - load.sent >= std::chrono::milliseconds(100)) {
        Send(ctx, base, 1); load.sent = Clock::now();
    }
}
bool DarkwatchOnlineCampaignControl(const X86Context& ctx, uint8_t* base) {
    // Native RPC decoding writes only the low short of this stack argument.
    if (uint16_t(Word(base, uint64_t(ctx.esp) + 4)) != kControl || !Context(ctx, base)) return false;
    const auto buffer = Word(base, uint64_t(ctx.esp) + 8), data = Word(base, uint64_t(buffer) + 4);
    uint16_t size = 0;
    if (Span(base, buffer, 8)) std::memcpy(&size, base + buffer, 2);
    uint32_t packet[6]{};
    if (size == sizeof(packet) && Span(base, data, sizeof(packet))) std::memcpy(packet, base + data, sizeof(packet));
    const auto kind = packet[5];
    if (ctx.ecx != PlayerObject(base, false) || !ctx.ecx || size != sizeof(packet) ||
        packet[0] != kMagic || packet[1] != kVersion || packet[2] != load.generation ||
        packet[3] != load.level || packet[4] != load.checkpoint || (kind != 1 && kind != 2)) {
        DarkwatchOnlineEventRecord("campaign-load-control-rejected", ctx.ecx, size, kind);
        return true;
    }
    if (kind == 1) {
        if (!load.received) DarkwatchOnlineEventRecord("campaign-load-peer-ready", load.generation, load.remote, ctx.ecx);
        load.received = true;
        Send(ctx, base, 2); // Re-ack duplicate Ready packets, including after we leave the barrier.
    } else {
        if (!load.acknowledged) DarkwatchOnlineEventRecord("campaign-load-peer-ack", load.generation, load.remote, ctx.ecx);
        load.acknowledged = true;
    }
    return true;
}
X86_FUNC(sub_000C3E34) {
    uint32_t game = 0, session = 0, local = 0, remote = 0;
    const bool active = Word(base, ctx.esp) == 0xC5CF7 &&
        DarkwatchOnlineCampaignLoadContext(ctx, base, game, session, local, remote) && ctx.ecx == game &&
        Word(base, uint64_t(Word(base, 0x4ACFBC)) + 8) == 4;
    if (active) {
        DarkwatchOnlineStoryReset();
        const auto generation = load.session == session ? load.generation + 1 : 1;
        load = {}; load.generation = generation; load.session = session; load.game = game;
        load.local = local; load.remote = remote;
    }
    if (active && !DarkwatchCharacterPrepareOnline(ctx, base)) Failed(5);
    __imp__sub_000C3E34(ctx, base);
    if (!active) return;
    load.loaded = true;
    if (!Key(base, game, load.level) || !Key(base, game + 4, load.checkpoint) || !Context(ctx, base)) Failed(2);
    DarkwatchOnlineEventRecord("campaign-load-local-ready", load.generation, load.level, load.checkpoint);
    // Native network components publish only after the loader returns to the frame loop.
    load.started = Clock::now();
    load.sent = load.started - std::chrono::seconds(1);
}
#endif
