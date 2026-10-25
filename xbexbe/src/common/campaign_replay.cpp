#include "campaign_replay.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <atomic>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_000CACD2);
X86_EXTERN_FUNC(__imp__sub_000CABC8);

namespace {
struct SavedProfile { uint32_t live = 0, copy = 0, identity = 0; };
struct Replay {
    uint8_t* base = nullptr;
    uint32_t game = 0, count = 0;
    std::array<SavedProfile, 2> profiles{};
} replay;
std::atomic<bool> failure_notice{false};
bool Reject() { failure_notice = true; return true; }

bool Span(const uint8_t* base, uint64_t at, uint64_t bytes) {
    if (!base || !at || !bytes || at + bytes > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + bytes; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(T)); return true;
}
bool Ref(const uint8_t* base, uint32_t at) {
    uint32_t ref;
    if (!Read(base, at, ref)) return false;
    if (!ref) return true;
    for (unsigned i = 0; i < 4096; ++i) {
        uint8_t c;
        if (!Read(base, uint64_t(ref) + 2 + i, c)) return false;
        if (!c) return true;
    }
    return false;
}
bool Array(const uint8_t* base, uint32_t at, unsigned stride, unsigned limit,
           uint16_t& count, uint32_t& data) {
    uint16_t capacity;
    return Read(base, at, count) && Read(base, at + 2, capacity) && count <= capacity &&
        count <= limit && Read(base, at + 4, data) && (!count || Span(base, data, uint64_t(count) * stride));
}
bool Profile(const uint8_t* base, uint32_t profile) {
    if (!Span(base, profile, 0x6C) || !Ref(base, profile) || !Ref(base, profile + 0xC)) return false;
    uint16_t count; uint32_t data;
    if (!Array(base, profile + 0x38, 8, 2, count, data) || count != 2) return false;
    for (unsigned i = 0; i < count; ++i) {
        uint16_t entries; uint32_t stats;
        if (!Array(base, data + i * 8, 0x38, 65535, entries, stats)) return false;
        for (unsigned j = 0; j < entries; ++j) {
            const auto record = stats + j * 0x38;
            uint32_t counters, size;
            if (!Ref(base, record) || !Read(base, record + 0x30, size) || size > 64 ||
                !Read(base, record + 0x34, counters) || (size && !Span(base, counters, size * 4))) return false;
        }
    }
    // The writer updates a chapter's tail checkpoint, but can append a repeated
    // chapter later. Bound the native uint16 array, not the chapter table size.
    if (!Array(base, profile + 0x5C, 0x14, 65535, count, data)) return false;
    for (unsigned i = 0; i < count; ++i) {
        const auto record = data + i * 0x14;
        uint32_t chapter, buffer, size, capacity, bytes;
        if (!Read(base, record, chapter) || chapter >= 17 || !Ref(base, record + 4) ||
            !Read(base, record + 8, buffer) || !Span(base, buffer, 0x14) ||
            !Read(base, buffer + 8, capacity) || !Read(base, buffer + 0xC, size) || size > capacity ||
            capacity > 1024 * 1024 || !Read(base, buffer + 0x10, bytes) ||
            (size && !Span(base, bytes, size))) return false;
    }
    // C9056 retains this shared handle through the original reference API.
    uint32_t handle;
    return Read(base, profile + 0x2C, handle) && (!handle || Span(base, handle, 8));
}
bool Stack(const X86Context& ctx, const uint8_t* base) {
    return ctx.esp >= 0x4000 && Span(base, uint64_t(ctx.esp) - 0x4000, 0x4000);
}
bool Players(X86Context& ctx, uint8_t* base, uint32_t& game, uint32_t& count,
             std::array<uint32_t, 2>& profiles, bool allow_empty = false) {
    if (base != kernel::g_base || !Stack(ctx, base) || !Read(base, 0x4AC9A0, game) ||
        !Span(base, game, 0x50) || !Read(base, game + 0x44, count) || (!count && !allow_empty) || count > 2) return false;
    auto call = ctx;
    for (unsigned i = 0; i < count; ++i) {
        call.ecx = game + 0x40;
        const auto player = kernel::CallGuest(call, 0xF9A4D, {i});
        if (!Span(base, player, 0x108)) return false;
        profiles[i] = player + 0x9C;
        if (!Profile(base, profiles[i])) return false;
    }
    return count != 2 || profiles[0] != profiles[1];
}
void Destroy(X86Context& call, const Replay& state) {
    for (const auto& profile : state.profiles) if (profile.copy) {
        call.ecx = profile.copy; kernel::CallGuest(call, 0xCAA17, {});
        kernel::CallGuest(call, 0x24C6DB, {profile.copy});
    }
}
bool Finish(X86Context& ctx, uint8_t* base) {
    if (!replay.count) return true;
    if (replay.base != base || !Stack(ctx, base)) return false;
    uint32_t game, count; std::array<uint32_t, 2> profiles{};
    if (!Players(ctx, base, game, count, profiles, true) || game != replay.game) return false;
    // Only still-owned player records can be restored. Menu teardown may have
    // already removed Player 2; its persistent profile was protected at commit.
    for (const auto& profile : replay.profiles) if (profile.copy) {
        if (!Profile(base, profile.copy)) return false;
    }
    std::array<const SavedProfile*, 2> restore{};
    for (unsigned i = 0; i < count; ++i) for (const auto& profile : replay.profiles) {
        if (profiles[i] != profile.live || !profile.copy) continue;
        uint32_t identity;
        if (!Read(base, profiles[i] + 0x68, identity)) return false;
        if (identity == profile.identity) restore[i] = &profile;
    }
    auto call = ctx;
    for (unsigned i = 0; i < count; ++i) {
        if (!restore[i]) continue;
        const auto& profile = *restore[i];
        // Retain control/preferences edits; all campaign progress comes from the snapshot.
        call.ecx = profile.copy; kernel::CallGuest(call, 0xC8CE0, {profile.live});
        call.ecx = profile.live; kernel::CallGuest(call, 0xC9056, {profile.copy});
    }
    Destroy(call, replay);
    replay = {};
    return true;
}
uint32_t SaveSource(X86Context& ctx, uint8_t* base, uint32_t source) {
    for (const auto& profile : replay.profiles) if (profile.live == source && profile.copy) {
        uint32_t identity;
        if (replay.base != base || !Stack(ctx, base) || !Profile(base, source) || !Profile(base, profile.copy) ||
            !Read(base, source + 0x68, identity) || identity != profile.identity) return 0;
        auto call = ctx;
        call.ecx = profile.copy; kernel::CallGuest(call, 0xC8CE0, {source});
        return profile.copy;
    }
    return source;
}
} // namespace

bool DarkwatchCampaignReplayBegin(X86Context& ctx, uint8_t* base) {
    // Native chapter-restart confirmation, after its prologue but before CA907.
    uint32_t type, menu, selected, mode;
    if (!Read(base, ctx.ecx, type) || type != 0x429B80 || !Read(base, ctx.ecx + 0x70, mode) || mode != 0 ||
        !Read(base, ctx.ecx + 0x58, menu) || !Read(base, menu + 0x68, selected) || selected != ctx.ebx ||
        selected >= 65535 || !Finish(ctx, base)) return Reject();
    Replay pending; std::array<uint32_t, 2> profiles{};
    if (!Players(ctx, base, pending.game, pending.count, profiles)) return Reject();
    for (unsigned i = 0; i < pending.count; ++i) {
        uint16_t count;
        if (!Read(base, profiles[i] + 0x5C, count) || selected >= count) return Reject();
    }
    pending.base = base;
    auto call = ctx;
    for (unsigned i = 0; i < pending.count; ++i) {
        const auto copy = kernel::CallGuest(call, 0x24C546, {0x6C});
        if (!copy) {Destroy(call, pending); return Reject();}
        call.ecx = copy; kernel::CallGuest(call, 0xCAAEF, {});
        pending.profiles[i] = {profiles[i], copy, 0};
        Read(base, profiles[i] + 0x68, pending.profiles[i].identity);
        call.ecx = copy; kernel::CallGuest(call, 0xC9056, {profiles[i]});
        if (!Profile(base, copy)) {Destroy(call, pending); return Reject();}
    }
    replay = pending;
    return false;
}

bool DarkwatchCampaignReplayFinish(X86Context& ctx, uint8_t* base) {
    if (Finish(ctx, base)) return true;
    failure_notice = true;
    return false;
}
void DarkwatchCampaignReplayEnd(X86Context& ctx, uint8_t* base) { DarkwatchCampaignReplayFinish(ctx, base); }
bool DarkwatchCampaignReplayBeforeChapter(X86Context& ctx, uint8_t* base) { return !DarkwatchCampaignReplayFinish(ctx, base); }
bool DarkwatchCampaignReplayTakeFailure() { return failure_notice.exchange(false); }

// The original save path copies live profiles into its database before writing.
// Protect that copy, rather than relying on shutdown to restore an on-disk save.
X86_FUNC(sub_000CACD2) {
    if (!replay.count) {__imp__sub_000CACD2(ctx, base); return;}
    uint32_t source;
    if (!Read(base, uint64_t(ctx.esp) + 4, source) || !(source = SaveSource(ctx, base, source))) {
        kernel::Return(ctx, 0, 1); return;
    }
    std::memcpy(base + ctx.esp + 4, &source, 4);
    __imp__sub_000CACD2(ctx, base);
}

X86_FUNC(sub_000CABC8) {
    if (!replay.count) {__imp__sub_000CABC8(ctx, base); return;}
    std::array<uint32_t, 2> source{};
    for (unsigned i = 0; i < 2; ++i) {
        if (!Read(base, uint64_t(ctx.esp) + 4 + i * 4, source[i]) ||
            !(source[i] = SaveSource(ctx, base, source[i]))) {
            kernel::Return(ctx, 0, 2); return;
        }
    }
    std::memcpy(base + ctx.esp + 4, source.data(), 8);
    __imp__sub_000CABC8(ctx, base);
}
