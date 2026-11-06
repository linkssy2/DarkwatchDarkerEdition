#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

#ifndef XBE_RELEASE
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>

extern bool DarkwatchOnlineStoryContext(const X86Context&, const uint8_t*, uint32_t (&)[3], uint32_t&);
extern bool DarkwatchOnlineSendStory(const X86Context&, uint8_t*, const uint32_t*, uint32_t);
extern void DarkwatchOnlineEventRecord(const char*, uint32_t, uint32_t, uint32_t);
extern bool DarkwatchOnlineCharacterWireEnabled(const X86Context&, const uint8_t*);
extern void DarkwatchOnlineCinematicReset();
extern bool DarkwatchOnlineCinematicResource(uint32_t);
extern bool DarkwatchOnlineCinematicApply(const X86Context&, uint8_t*, uint32_t, uint32_t, uint32_t);
X86_EXTERN_FUNC(__imp__sub_00216560);
X86_EXTERN_FUNC(__imp__sub_00077923);
X86_EXTERN_FUNC(__imp__sub_0009C3E2);

namespace {
using Clock = std::chrono::steady_clock;
using Packet = std::array<uint32_t, 11>;
using RidingPacket = std::array<uint32_t, 30>;
constexpr uint32_t kControl = 0x7FFD, kMagic = 0x44575345;
struct Story {
    uint32_t stamp[3]{}, sent = 0, received = 0;
    bool replay = false;
    uint32_t mounting_horse = 0;
    std::deque<Packet> pending;
    Packet incoming{};
    Clock::time_point last_send{}, started{};
    RidingPacket riding{};
    uint32_t riding_sent = 0, riding_applied = 0;
    Clock::time_point riding_send{};
};
Story story;
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
bool Name(const uint8_t* base, uint32_t token, const char* name) {
    const auto size = uint32_t(std::strlen(name) + 1);
    return Span(base, uint64_t(token) + 2, size) && !std::memcmp(base + token + 2, name, size);
}
bool NamedActor(const uint8_t* base, uint32_t actor, const char* type, const char* name) {
    return Span(base, actor, 0x9C) && !base[actor + 0x5E] &&
        Name(base, Word(base, actor + 0x54), name) && Name(base, Word(base, actor + 0x50), type);
}
constexpr struct { const char* type; const char* name; } kDoors[]{
    {"TrainDoor2_right", "Door_MeatCar_Exit"},
    {"TrainDoor2_left", "Door_BattleCar_Enter"},
    {"TrainDoor2_left", "Door_BattleCar_Exit"},
};
uint32_t Door(const uint8_t* base, uint32_t actor) {
    for (uint32_t i = 0; i < std::size(kDoors); ++i)
        if (NamedActor(base, actor, kDoors[i].type, kDoors[i].name)) return i;
    return ~0u;
}
bool RidingChapter(const uint8_t* base) {
    return Name(base, Word(base, Word(base, 0x4AC9A0)), "M02_CanyonShoot");
}
bool Context(const X86Context& ctx, uint8_t* base, uint32_t& remote, bool& host) {
    uint32_t stamp[3]{};
    if (!DarkwatchOnlineStoryContext(ctx, base, stamp, remote)) return false;
    if (std::memcmp(stamp, story.stamp, sizeof(stamp))) {
        story = {}; std::memcpy(story.stamp, stamp, sizeof(stamp));
    }
    X86Context call = ctx;
    const auto role = kernel::CallGuest(call, 0x186A30, {}) & 255;
    host = role == 1;
    return role == 1 || role == 2;
}
Packet Message(uint32_t sequence, uint32_t event, uint32_t value) {
    return {kMagic, 2, story.stamp[0], story.stamp[1], story.stamp[2], sequence, event, value, 0, 0, 0};
}
bool Position(const uint32_t* words) {
    float position[3]; std::memcpy(position, words, sizeof(position));
    return std::isfinite(position[0]) && std::isfinite(position[1]) && std::isfinite(position[2]);
}
[[noreturn]] void Failed(uint32_t reason) {
    DarkwatchOnlineEventRecord("campaign-story-failed", reason, story.sent, story.received);
    std::fputs("Private online story agreement failed; see the diagnostic trace.\n", stderr);
    std::fflush(stderr);
    std::_Exit(3);
}
uint32_t Player(const uint8_t* base, unsigned ordinal) {
    const auto game = Word(base, 0x4AC9A0), records = Word(base, uint64_t(game) + 0x54);
    if (ordinal > 1 || Word(base, uint64_t(game) + 0x44) != 2 || !Span(base, records, 2 * 0x130)) return 0;
    for (unsigned i = 0; i < 2; ++i) {
        const auto row = records + i * 0x130, actor = Word(base, row + 0x118);
        if (Word(base, row + 0x10C) == ordinal && Span(base, actor, 0x9C)) return actor;
    }
    return 0;
}
bool LocalPlayer(const uint8_t* base, uint32_t actor) {
    const auto game = Word(base, 0x4AC9A0), rows = Word(base, uint64_t(game) + 0x54);
    if (!actor || Word(base, uint64_t(game) + 0x44) != 2 || !Span(base, rows, 2 * 0x130)) return false;
    for (unsigned i = 0; i < 2; ++i)
        if (Word(base, rows + i * 0x130 + 0x118) == actor) return base[rows + i * 0x130 + 0x128] != 0;
    return false;
}
void Queue(Packet packet) {
    if (story.pending.size() >= 64 || story.sent == ~0u) Failed(3);
    packet[5] = ++story.sent;
    story.pending.push_back(packet);
    DarkwatchOnlineEventRecord("campaign-story-queued", packet[5], packet[6], packet[7]);
}
bool FindActor(const uint8_t* base, const char* type, const char* name, uint32_t& found, uint32_t& space) {
    found = space = 0;
    const auto manager = Word(base, 0x4AC118), groups = Word(base, uint64_t(manager) + 4);
    if (!Span(base, manager, 8)) return 0;
    uint16_t count = 0;
    std::memcpy(&count, base + manager, 2);
    if (count > 256 || (count && !Span(base, groups, count * 4))) return 0;
    unsigned visited = 0;
    for (unsigned i = 0; i < count; ++i) {
        const auto group = Word(base, groups + i * 4), actors = Word(base, uint64_t(group) + 0x24);
        if (!Span(base, group, 0x28)) return 0;
        uint16_t size = 0; std::memcpy(&size, base + group + 0x20, 2);
        if (size > 4096 - visited || (size && !Span(base, actors, size * 4))) return 0;
        visited += size;
        for (unsigned j = 0; j < size; ++j) {
            const auto actor = Word(base, actors + j * 4);
            if (!NamedActor(base, actor, type, name)) continue;
            if (found) return 0;
            found = actor; space = Word(base, group);
        }
    }
    return true;
}
uint32_t FindDoor(const uint8_t* base, uint32_t id) {
    uint32_t actor = 0, space = 0;
    return id < std::size(kDoors) && FindActor(base, kDoors[id].type, kDoors[id].name, actor, space) ? actor : 0;
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t type, uint32_t size) {
    if (!Span(base, actor, 0x9C) || base[actor + 0x5E]) return 0;
    uint16_t count = 0; std::memcpy(&count, base + actor + 0x60, 2);
    const auto rows = Word(base, actor + 0x64);
    if (count > 128 || (count && !Span(base, rows, count * 8))) return 0;
    uint32_t result = 0;
    for (unsigned i = 0; i < count; ++i) {
        const auto part = Word(base, rows + i * 8 + 4);
        if (Word(base, part) != type) continue;
        if (result || !Span(base, part, size) || Word(base, part + 12) != actor) return 0;
        result = part;
    }
    return result;
}
bool DetPak(const uint8_t* base, uint32_t actor) {
    return NamedActor(base, actor, "DetPak", "DetPak_1") && Component(base, actor, 0x41C55C, 0xC8);
}
uint32_t FindDetPak(const uint8_t* base) {
    uint32_t actor = 0, space = 0;
    return FindActor(base, "DetPak", "DetPak_1", actor, space) && DetPak(base, actor) ? actor : 0;
}
uint32_t Horse(const X86Context& ctx, uint8_t* base, unsigned ordinal) {
    const char* name = ordinal ? "Horse_Player2" : "Horse_2";
    uint32_t horse = 0, space = 0;
    if (ordinal > 1 || !FindActor(base, "Horse", name, horse, space)) return 0;
    if (horse) return horse;
    uint32_t anchor = 0;
    if (!FindActor(base, "Horse", "Horse_2", anchor, space) || !anchor) return 0;
    const auto at = ctx.esp - 128;
    std::array<uint8_t, 128> saved; std::memcpy(saved.data(), base + at, saved.size());
    X86Context call = ctx; call.esp = at - 32;
    std::strcpy(reinterpret_cast<char*>(base + at), name);
    std::memset(base + at + 64, 0, 4);
    call.ecx = at + 64; kernel::CallGuest(call, 0x138FA, {at});
    call.ecx = kernel::CallGuest(call, 0x26366, {});
    horse = kernel::CallGuest(call, 0x21FC19, {at + 64, space, 1, 3});
    call.ecx = at + 64; kernel::CallGuest(call, 0x11C1A, {});
    std::memcpy(base + at, saved.data(), saved.size());
    return NamedActor(base, horse, "Horse", name) ? horse : 0;
}
bool Mount(const X86Context& ctx, uint8_t* base, uint32_t ordinal) {
    const auto player = Player(base, ordinal);
    if (ordinal > 1 || !RidingChapter(base) || !LocalPlayer(base, player) ||
        ctx.esp < 1024 || !Span(base, uint64_t(ctx.esp) - 1024, 1024)) return false;
    const char* name = ordinal ? "Horse_Player2" : "Horse_2";
    const auto horse = Horse(ctx, base, ordinal);
    const auto at = ctx.esp - 128;
    std::array<uint8_t, 128> saved;
    std::memcpy(saved.data(), base + at, saved.size());
    X86Context call = ctx; call.esp = at - 32;
    const bool valid = NamedActor(base, horse, "Horse", name);
    if (valid) {
        const uint32_t event[]{0x41E948, 0x116, player};
        std::memcpy(base + at, event, sizeof(event));
        call.ecx = horse; story.replay = true; story.mounting_horse = horse;
        kernel::CallGuest(call, 0x216560, {at});
        story.mounting_horse = 0; story.replay = false;
        DarkwatchOnlineEventRecord("campaign-horse-interact-applied", ordinal, horse, player);
    }
    std::memcpy(base + at, saved.data(), saved.size());
    return valid;
}
bool RidingValues(const RidingPacket& packet) {
    if (packet[8] > 1) return false;
    for (unsigned i = 9; i < packet.size(); ++i) {
        if (i < 25 && (i - 9) % 4 == 3 && packet[i]) return false;
        float value; std::memcpy(&value, &packet[i], 4);
        if (!std::isfinite(value) || (!packet[8] && packet[i])) return false;
    }
    return true;
}
void RidingTick(const X86Context& ctx, uint8_t* base, bool host) {
    // shortcut: original M02 horses only; trace other vehicles before extending this codec.
    if (!RidingChapter(base) || ctx.esp < 1024 || !Span(base, ctx.esp - 1024, 1024)) return;
    const auto ordinal = host ? 0u : 1u, player = Player(base, ordinal);
    const auto movement = Component(base, player, 0x41F878, 0x320);
    if (!LocalPlayer(base, player) || !movement) return;
    const auto now = Clock::now();
    if (now - story.riding_send >= std::chrono::milliseconds(8)) {
        RidingPacket packet{};
        const auto header = Message(0, 0x10004, ordinal);
        std::copy_n(header.begin(), 8, packet.begin());
        packet[5] = story.riding_sent + 1;
        if (!packet[5]) Failed(5);
        const auto horse = Word(base, movement + 0x180);
        const auto component = Component(base, horse, 0x41DA58, 0x1D4);
        if (NamedActor(base, horse, "Horse", ordinal ? "Horse_Player2" : "Horse_2") &&
            component && Word(base, component + 0x3C) == player) {
            packet[8] = 1;
            // Native matrices compare four XYZ vectors; the fourth lanes are not pose data.
            for (unsigned row = 0; row < 4; ++row)
                std::memcpy(packet.data() + 9 + row * 4, base + horse + 0x10 + row * 16, 12);
            std::memcpy(packet.data() + 25, base + component + 0x168, 12);
            std::memcpy(packet.data() + 28, base + component + 0xD8, 8);
        }
        if (RidingValues(packet) && DarkwatchOnlineSendStory(ctx, base, packet.data(), sizeof(packet))) {
            story.riding_sent = packet[5]; story.riding_send = now;
        }
    }
    const auto& packet = story.riding;
    if (!packet[5] || packet[5] == story.riding_applied) return;
    const auto other = Player(base, packet[7]), other_movement = Component(base, other, 0x41F878, 0x320);
    if (!other_movement || LocalPlayer(base, other)) return;
    const auto parent = Word(base, other_movement + 0x180);
    X86Context call = ctx; const auto at = ctx.esp - 128; call.esp = at - 32;
    std::array<uint8_t, 128> saved; std::memcpy(saved.data(), base + at, saved.size());
    if (packet[8]) {
        const auto horse = Horse(call, base, packet[7]);
        const auto horse_component = Component(base, horse, 0x41DA58, 0x1D4);
        if (!horse_component) return;
        if (parent != horse) {
            if (parent) return;
            // Native network parent-field receiver uses this same retaining attachment helper.
            call.ecx = horse; kernel::CallGuest(call, 0x216743, {at});
            // ActorRef is an intrusive node: consume it at its constructed address, never copy its words.
            call.ecx = other_movement; call.esp = at;
            kernel::CallGuest(call, 0x9C995, {});
            // Complete StartDrivingVehicle's root lock and phase link, without the owner's camera.
            if (Word(base, horse_component + 0x3C) == other) {
                call.ecx = horse_component; call.esp = at - 32;
                kernel::CallGuest(call, 0x74E1F, {});
                call.ecx = horse_component;
                kernel::CallGuest(call, 0x77FE4, {});
            }
            DarkwatchOnlineEventRecord("campaign-horse-replica-attached", packet[7], horse, other);
        }
    } else if (NamedActor(base, parent, "Horse", packet[7] ? "Horse_Player2" : "Horse_2")) {
        call.ecx = other_movement; kernel::CallGuest(call, 0x9C3E2, {});
        DarkwatchOnlineEventRecord("campaign-horse-replica-detached", packet[7], parent, other);
    }
    std::memcpy(base + at, saved.data(), saved.size());
    story.riding_applied = packet[5];
}
void Acknowledge(const X86Context& ctx, uint8_t* base, uint32_t sequence) {
    const auto ack = Message(sequence, 0, 0);
    DarkwatchOnlineSendStory(ctx, base, ack.data(), sizeof(ack));
}
}

void DarkwatchOnlineStoryReset() { story = {}; DarkwatchOnlineCinematicReset(); }
bool DarkwatchOnlineStoryDrained() { return story.pending.empty() && !story.incoming[5]; }

bool DarkwatchOnlineQueueCinematic(const X86Context& ctx, uint8_t* base, uint32_t kind, uint32_t value, uint32_t time) {
    uint32_t remote = 0; bool host = false;
    float seconds; std::memcpy(&seconds, &time, 4);
    if (!Context(ctx, base, remote, host) || !host ||
        (kind == 0x10001 ? (!DarkwatchOnlineCinematicResource(value) || time) :
         kind != 0x10002 || value > 2 || !std::isfinite(seconds) || seconds < 0 || seconds > 60)) return false;
    auto packet = Message(0, kind, value); packet[8] = time; Queue(packet); return true;
}

void DarkwatchOnlineStoryTick(const X86Context& ctx, uint8_t* base) {
    uint32_t remote = 0; bool host = false;
    if (!Context(ctx, base, remote, host)) return;
    RidingTick(ctx, base, host);
    const auto now = Clock::now();
    if (host && !story.pending.empty()) {
        if (story.started == Clock::time_point{}) story.started = now;
        if (now - story.started > std::chrono::seconds(15)) Failed(1);
        if (now - story.last_send >= std::chrono::milliseconds(100)) {
            const auto& packet = story.pending.front();
            if (DarkwatchOnlineSendStory(ctx, base, packet.data(), sizeof(packet))) {
                DarkwatchOnlineEventRecord("campaign-story-sent", packet[5], packet[6], packet[7]);
                story.last_send = now;
            }
        }
    } else if (!host && story.incoming[5]) {
        const auto packet = story.incoming;
        if (packet[6] == 0x10003) {
            if (!Mount(ctx, base, packet[7])) return;
            story.received = packet[5]; story.incoming = {};
            DarkwatchOnlineEventRecord("campaign-story-applied", packet[5], packet[6], packet[7]);
            Acknowledge(ctx, base, story.received);
            return;
        }
        if (packet[6] == 0x10001 || packet[6] == 0x10002) {
            if (!DarkwatchOnlineCinematicApply(ctx, base, packet[6], packet[7], packet[8])) return;
            story.received = packet[5]; story.incoming = {};
            DarkwatchOnlineEventRecord("campaign-story-applied", packet[5], packet[6], packet[7]);
            Acknowledge(ctx, base, story.received);
            return;
        }
        const bool teleport = packet[6] == 0x1E, player = teleport || packet[6] == 0x1F || packet[6] == 0x23A;
        const bool detpak = packet[6] == 0x21A;
        const auto actor = player ? Player(base, packet[7]) : detpak ? FindDetPak(base) : FindDoor(base, packet[8]);
        const auto value = packet[6] == 0x116 ? (packet[7] == 2 ? 0 : Player(base, packet[7])) : packet[7];
        if (!actor || (packet[6] == 0x116 && packet[7] < 2 && !value)) return;
        if (player && !LocalPlayer(base, actor)) return;
        // Apply on the frame thread, after loading, rather than from the native network callback.
        // The owner publishes the native TeleportProxy after updating its own controller.
        const uint32_t event[]{0x41E948, packet[6], player || detpak ? packet[8] : value,
                              packet[9], packet[10], teleport ? 1u : 0u};
        X86Context call = ctx; call.esp -= 64;
        std::memcpy(base + call.esp, event, sizeof(event));
        call.ecx = actor; story.replay = true;
        kernel::CallGuest(call, 0x216560, {call.esp});
        story.replay = false; story.received = packet[5]; story.incoming = {};
        DarkwatchOnlineEventRecord("campaign-story-applied", packet[5], packet[6], packet[7]);
        Acknowledge(ctx, base, story.received);
    }
}

bool DarkwatchOnlineStoryControl(const X86Context& ctx, uint8_t* base) {
    if (uint16_t(Word(base, uint64_t(ctx.esp) + 4)) != kControl) return false;
    uint32_t remote = 0; bool host = false;
    if (!Context(ctx, base, remote, host)) return DarkwatchOnlineCharacterWireEnabled(ctx, base);
    const auto buffer = Word(base, uint64_t(ctx.esp) + 8), data = Word(base, uint64_t(buffer) + 4);
    uint16_t size = 0;
    if (Span(base, buffer, 8)) std::memcpy(&size, base + buffer, 2);
    if (size == sizeof(RidingPacket)) {
        RidingPacket packet{};
        if (Span(base, data, size)) std::memcpy(packet.data(), base + data, size);
        if (!remote || ctx.ecx != remote || packet[0] != kMagic || packet[1] != 2 ||
            std::memcmp(packet.data() + 2, story.stamp, sizeof(story.stamp)) || !packet[5] ||
            packet[6] != 0x10004 || packet[7] != (host ? 1u : 0u) || !RidingChapter(base) || !RidingValues(packet)) {
            DarkwatchOnlineEventRecord("campaign-horse-replica-rejected", ctx.ecx, size, packet[7]);
        } else if (packet[5] > story.riding[5]) story.riding = packet;
        return true;
    }
    Packet packet{};
    if (size == sizeof(packet) && Span(base, data, sizeof(packet))) std::memcpy(packet.data(), base + data, sizeof(packet));
    float seconds; std::memcpy(&seconds, &packet[8], 4);
    const bool cinematic = !packet[9] && !packet[10] &&
        ((packet[6] == 0x10001 && DarkwatchOnlineCinematicResource(packet[7]) && !packet[8]) ||
         (packet[6] == 0x10002 && packet[7] <= 2 && std::isfinite(seconds) && seconds >= 0 && seconds <= 60));
    if (!remote || ctx.ecx != remote || size != sizeof(packet) || packet[0] != kMagic || packet[1] != 2 ||
        std::memcmp(packet.data() + 2, story.stamp, sizeof(story.stamp)) || !packet[5] ||
        (host ? (packet[6] || packet[7] || packet[8] || packet[9] || packet[10]) :
          !(cinematic || (packet[6] == 0x10003 && packet[7] <= 1 && !packet[8] && !packet[9] && !packet[10] && RidingChapter(base)) ||
            (packet[6] == 0x21A && !packet[7] && Position(packet.data() + 8)) ||
            ((packet[6] == 0x1E || packet[6] == 0x1F || packet[6] == 0x23A) && packet[7] <= 1 && Position(packet.data() + 8)) ||
            (packet[8] < std::size(kDoors) && !packet[9] && !packet[10] &&
             ((packet[6] == 0x116 && packet[7] <= 2) || (packet[6] == 0x117 && packet[7] <= 1)))))) {
        DarkwatchOnlineEventRecord("campaign-story-rejected", ctx.ecx, size, packet[6]);
        return true;
    }
    if (host) {
        if (!story.pending.empty() && story.pending.front()[5] == packet[5]) {
            story.pending.pop_front(); story.started = {}; story.last_send = {};
            DarkwatchOnlineEventRecord("campaign-story-acknowledged", packet[5], 0, 0);
        }
    } else if (packet[5] <= story.received) {
        Acknowledge(ctx, base, packet[5]);
    } else if (packet[5] == story.received + 1 &&
               (!story.incoming[5] || story.incoming == packet)) {
        story.incoming = packet;
    } else {
        DarkwatchOnlineEventRecord("campaign-story-rejected-order", packet[5], story.received, story.incoming[5]);
    }
    return true;
}

extern void DarkwatchOnlinePrepareNpcDeath(const X86Context&, uint8_t*);
X86_FUNC(sub_00216560) {
    const auto message = Word(base, uint64_t(ctx.esp) + 4), event = Word(base, uint64_t(message) + 4);
    if (event == 0x139) DarkwatchOnlinePrepareNpcDeath(ctx, base);
    // The owner's layout horse has no network object; its synchronous mount query is still local.
    const bool local_mount = story.replay && story.mounting_horse && ctx.ecx == story.mounting_horse &&
        event == 0x24 && Span(base, message, 20) && Word(base, message) == 0x41E948 &&
        (Word(base, ctx.esp) == 0x24A005 || Word(base, ctx.esp) == 0x24A096);
    static unsigned observed = 0;
    if (event == 0x116 && observed < 128 && DarkwatchOnlineCharacterWireEnabled(ctx, base) &&
        Span(base, ctx.ecx, 0x9C) && Span(base, message, 12) &&
        (Name(base, Word(base, ctx.ecx + 0x54), "Horse_2") ||
         Name(base, Word(base, ctx.ecx + 0x54), "Horse_Player2"))) {
        ++observed;
        DarkwatchOnlineEventRecord("campaign-horse-interact", ctx.ecx, Word(base, message + 8), Word(base, ctx.esp));
    }
    uint32_t remote = 0; bool host = false;
    if (!story.replay && event == 0x116 && RidingChapter(base) &&
        Span(base, message, 12) && Word(base, message) == 0x41E948 &&
        Context(ctx, base, remote, host) && host) {
        const auto player = Word(base, message + 8);
        for (unsigned ordinal = 0; ordinal < 2; ++ordinal) {
            if (player && player == Player(base, ordinal) && !LocalPlayer(base, player) &&
                NamedActor(base, ctx.ecx, "Horse", ordinal ? "Horse_Player2" : "Horse_2"))
                Queue(Message(0, 0x10003, ordinal));
        }
    }
    // Original Destructible::Explode broadcasts its 21A position in event 26.
    // Carry only coordinates; the peer resolves its own authored DetPak actor.
    if (!story.replay && event == 0x26 && Word(base, ctx.esp) == 0x5F292 &&
        Span(base, message, 13) && Word(base, message) == 0x41E948 && base[message + 12] == 1 &&
        DetPak(base, ctx.ecx) && Context(ctx, base, remote, host) && host) {
        const auto inner = Word(base, message + 8);
        if (Span(base, inner, 20) && Word(base, inner) == 0x41E948 && Word(base, inner + 4) == 0x21A) {
            auto packet = Message(0, 0x21A, 0);
            std::memcpy(packet.data() + 8, base + inner + 8, 12);
            if (!Position(packet.data() + 8)) Failed(4);
            Queue(packet);
        }
    }
    const auto door = event == 0x116 || event == 0x117 ? Door(base, ctx.ecx) : ~0u;
    if (!story.replay && door < std::size(kDoors) &&
        Span(base, message, 12) && Word(base, message) == 0x41E948 && Context(ctx, base, remote, host) && host) {
        auto value = Word(base, message + 8);
        if (event == 0x116) {
            value = !value ? 2 : value == Player(base, 0) ? 0 : value == Player(base, 1) ? 1 : 3;
            if (value == 3) Failed(2);
        } else value = value != 0;
        auto packet = Message(0, event, value); packet[8] = door; Queue(packet);
    } else if (!story.replay &&
               ((event == 0x1E && Span(base, message, 24) &&
                 (base[message + 0x14] || Word(base, ctx.esp) == 0xFCD58 || Word(base, ctx.esp) == 0x105E7D)) ||
                ((event == 0x1F || event == 0x23A) && Span(base, message, 20) && Word(base, ctx.esp) == 0x8F1EB)) &&
               Word(base, message) == 0x41E948 &&
               Context(ctx, base, remote, host) && host && !LocalPlayer(base, ctx.ecx)) {
        // Authored regroup position, movement and facing must reach the owner, not just its replica.
        for (unsigned ordinal = 0; ordinal < 2; ++ordinal) {
            if (!ctx.ecx || Player(base, ordinal) != ctx.ecx) continue;
            auto packet = Message(0, event, ordinal);
            std::memcpy(packet.data() + 8, base + message + 8, 12);
            if (!Position(packet.data() + 8)) Failed(4);
            Queue(packet);
            break;
        }
    }
    __imp__sub_00216560(ctx, base);
    if (local_mount && !Word(base, message + 8) && Word(base, message + 12) == 1) {
        const uint32_t present = 1;
        std::memcpy(base + message + 8, &present, sizeof(present));
    }
}

X86_FUNC(sub_0009C3E2) {
    uint32_t remote = 0; bool host = false;
    if (Context(ctx, base, remote, host) && RidingChapter(base) && story.riding[5] && story.riding_applied) {
        const auto rider = Player(base, story.riding[7]);
        const auto horse = Word(base, uint64_t(ctx.ecx) + 0x180);
        if (rider && !LocalPlayer(base, rider) && Component(base, rider, 0x41F878, 0x320) == ctx.ecx &&
            NamedActor(base, horse, "Horse", story.riding[7] ? "Horse_Player2" : "Horse_2")) {
            if (Word(base, ctx.esp) == 0x9CE10 && story.riding[8] == 1) {
                // A null native network parent must not undo the authenticated riding snapshot.
                ctx.esp += 4;
                return;
            }
            const auto component = Component(base, horse, 0x41DA58, 0x1D4);
            if (component && Word(base, component + 0x3C) == rider) {
                // Release the root override and phase link before detach clears the rider reference.
                X86Context call = ctx; call.ecx = component;
                kernel::CallGuest(call, 0x74EB1, {});
                call.ecx = component;
                kernel::CallGuest(call, 0x76A28, {});
            }
        }
    }
    __imp__sub_0009C3E2(ctx, base);
}

X86_FUNC(sub_00077923) {
    const auto component = ctx.ecx, horse = Word(base, uint64_t(component) + 12);
    uint32_t remote = 0; bool host = false;
    if (Word(base, ctx.esp) == 0x77FD1 && Context(ctx, base, remote, host) && RidingChapter(base) &&
        story.riding[8] == 1 && story.riding[5] && story.riding_applied &&
        Component(base, horse, 0x41DA58, 0x1D4) == component &&
        NamedActor(base, horse, "Horse", story.riding[7] ? "Horse_Player2" : "Horse_2")) {
        const auto rider = Player(base, story.riding[7]);
        const auto movement = Component(base, rider, 0x41F878, 0x320);
        if (rider && !LocalPlayer(base, rider) && Word(base, component + 0x3C) == rider &&
            movement && Word(base, movement + 0x180) == horse && ctx.esp >= 1024 && Span(base, ctx.esp - 1024, 1024)) {
            // Reconcile before the native held-weapon update in the horse tick.
            const auto at = ctx.esp - 128; X86Context call = ctx; call.esp = at - 32;
            std::array<uint8_t, 128> saved; std::memcpy(saved.data(), base + at, saved.size());
            std::memcpy(base + at, base + horse + 0x10, 64);
            for (unsigned row = 0; row < 4; ++row)
                std::memcpy(base + at + row * 16, story.riding.data() + 9 + row * 4, 12);
            call.ecx = horse; kernel::CallGuest(call, 0x216244, {at});
            const auto controller = Word(base, component + 0x190);
            if (Span(base, controller, 4)) { call.ecx = controller; kernel::CallGuest(call, 0x836DA, {at + 48}); }
            std::memcpy(base + component + 0x168, story.riding.data() + 25, 12);
            std::memcpy(base + component + 0xD8, story.riding.data() + 28, 8);
            std::memcpy(base + at, saved.data(), saved.size());
        }
    }
    __imp__sub_00077923(ctx, base);
}
#endif
