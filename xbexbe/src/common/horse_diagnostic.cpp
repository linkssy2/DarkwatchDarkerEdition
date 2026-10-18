#include "horse_diagnostic.h"
#include "horse_voice_diagnostic.h"
#include "sound_pool.h"
#include <array>
#include <cstring>
#include <mutex>
#include "audio/audio.h"
#include "core/diag.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

namespace {
constexpr uint32_t kMissing = 0xFFFFFFFF;
constexpr size_t kMaxPairs = 32, kMaxDepth = 8, kSeen = 64;
constexpr uint32_t kEventVtable = 0x00440D28, kParameterVtable = 0x0042D400;
struct Snapshot {
    uint32_t event = 0, parameters = kMissing, actor = kMissing;
    uint32_t flag58 = kMissing, flag59 = kMissing, flag5a = kMissing, filter_checked = kMissing;
    uint32_t attach = kMissing, chance = kMissing, filter = kMissing, filter_empty = kMissing;
    uint32_t actor_disabled = kMissing, components = kMissing, component_table = kMissing;
    uint32_t bank = kMissing, cue = kMissing, readable = 0;
    std::array<uint32_t, 5> result{kMissing, kMissing, kMissing, kMissing, kMissing};
    uint32_t sound_vtable = kMissing, sound_state = kMissing, sound_pause = kMissing;
    uint32_t sound_cue_key = kMissing, sound_definition = kMissing, xact_cue = kMissing;
    bool operator==(const Snapshot&) const = default;
};
struct Frame {
    Snapshot before;
    const uint8_t* base = nullptr;
    uint32_t stack = 0, thread = 0, caller = kMissing, pair = 0;
};
struct Seen {
    uint32_t thread = 0, event = 0, parameters = 0;
    Snapshot before, after;
    bool have_before = false, have_after = false;
};
std::mutex g_lock;
std::array<Seen, kSeen> g_seen{};
size_t g_next_seen = 0;
uint32_t g_pairs = 0;
uint32_t g_admissions = 0;
thread_local std::array<Frame, kMaxDepth> g_frames;
thread_local size_t g_depth = 0;

bool Span(const uint8_t* base, uint64_t address, uint32_t bytes) {
    if (!base || !address || !bytes || address + bytes > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < address + bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
bool Read(const uint8_t* base, uint64_t address, uint32_t bytes, uint32_t& value) {
    if (!Span(base, address, bytes)) return false;
    value = 0;
    std::memcpy(&value, base + address, bytes);
    return true;
}
template<size_t N> bool StringIs(const uint8_t* base, uint32_t reference, const char (&text)[N]) {
    // Original 12B99: the reference points to a 16-bit reference count, then bytes.
    const uint64_t characters = uint64_t(reference) + 2;
    return reference && Span(base, characters, N) && !std::memcmp(base + characters, text, N);
}
bool Matches(const uint8_t* base, uint32_t event) {
    uint32_t vtable, parameters, bank, cue;
    return event && Read(base, event, 4, vtable) && vtable == kEventVtable &&
        Read(base, uint64_t(event) + 0x54, 4, parameters) && parameters &&
        Read(base, parameters, 4, vtable) && vtable == kParameterVtable &&
        Read(base, uint64_t(parameters) + 4, 4, bank) && StringIs(base, bank, "EMITTER") &&
        Read(base, uint64_t(parameters) + 8, 4, cue) && StringIs(base, cue, "HORSE_WAKE01");
}
void CaptureSound(const uint8_t* base, uint32_t object, Snapshot& s) {
    auto field = [&](uint32_t offset, uint32_t bytes, uint32_t bit) {
        uint32_t value = kMissing;
        if (object && object != kMissing && Read(base, uint64_t(object) + offset, bytes, value)) s.readable |= 1u << bit;
        return value;
    };
    s.sound_vtable = field(0, 4, 20);
    uint32_t cue_offset = 0;
    switch (s.sound_vtable) {
        case 0x0043EE2C: cue_offset = 0x3C; break;
        case 0x0043EE74: case 0x0043EEA8: case 0x0043EEDC: cue_offset = 0x4C; break;
    }
    // Original sound classes share these fields; +3C has another role in the spatial classes.
    if (cue_offset) {
        s.sound_state = field(0xC, 4, 21);
        s.sound_pause = field(0x18, 1, 22);
        s.sound_cue_key = field(0x1C, 4, 23);
        s.sound_definition = field(0x20, 4, 24);
        s.xact_cue = field(cue_offset, 4, 25);
    }
}
Snapshot Capture(const uint8_t* base, uint32_t event) {
    Snapshot s;
    s.event = event;
    auto field = [&](uint32_t object, uint32_t offset, uint32_t bytes, uint32_t bit) {
        uint32_t value = kMissing;
        if (object && object != kMissing && Read(base, uint64_t(object) + offset, bytes, value)) s.readable |= 1u << bit;
        return value;
    };
    s.parameters = field(event, 0x54, 4, 0);
    s.actor = field(event, 0x5C, 4, 1);
    s.flag58 = field(event, 0x58, 1, 2); s.flag59 = field(event, 0x59, 1, 3);
    s.flag5a = field(event, 0x5A, 1, 4); s.filter_checked = field(event, 0x84, 1, 5);
    s.attach = field(s.parameters, 0xC, 1, 6); s.chance = field(s.parameters, 0x10, 4, 7);
    s.filter = field(s.parameters, 0x14, 4, 8);
    if ((s.readable & (1u << 8)) && !s.filter) { s.filter_empty = 1; s.readable |= 1u << 9; }
    else {
        const uint32_t first = field(s.filter, 2, 1, 9);
        if (s.readable & (1u << 9)) s.filter_empty = first == 0;
    }
    s.actor_disabled = field(s.actor, 0x5E, 1, 10);
    s.components = field(s.actor, 0x60, 2, 11);
    s.component_table = field(s.actor, 0x64, 4, 12);
    s.bank = field(s.parameters, 4, 4, 13); s.cue = field(s.parameters, 8, 4, 14);
    for (uint32_t i = 0; i < 5; ++i) s.result[i] = field(event, 0x70 + 4 * i, 4, 15 + i);
    CaptureSound(base, s.result[0], s);
    return s;
}
Seen& Find(const Frame& f) {
    for (auto& seen : g_seen)
        if (seen.have_before && seen.thread == f.thread && seen.event == f.before.event &&
            seen.parameters == f.before.parameters) return seen;
    auto& seen = g_seen[g_next_seen++ % kSeen];
    seen = {};
    seen.thread = f.thread; seen.event = f.before.event; seen.parameters = f.before.parameters;
    return seen;
}
void Log(const char* phase, const Frame& f, const Snapshot& s) {
    LOGW("Horse cue pair=%u phase=%s tid=%X caller=%08X stack=%08X event=%08X parameters=%08X "
         "matched_bank=EMITTER matched_cue=HORSE_WAKE01 bank_ref=%08X cue_ref=%08X actor=%08X "
         "flags=%02X/%02X/%02X filter_checked=%02X attach=%02X chance=%u filter_ref=%08X filter_empty=%08X "
         "actor_disabled=%08X components=%08X component_table=%08X result=%08X/%08X/%08X/%08X/%08X "
         "sound_vtable=%08X sound_state=%08X sound_pause=%08X sound_cue_key=%08X sound_definition=%08X xact_cue=%08X readable=%08X",
         f.pair, phase, f.thread, f.caller, f.stack, s.event, s.parameters, s.bank, s.cue, s.actor,
         s.flag58, s.flag59, s.flag5a, s.filter_checked, s.attach, s.chance, s.filter, s.filter_empty,
         s.actor_disabled, s.components, s.component_table,
         s.result[0], s.result[1], s.result[2], s.result[3], s.result[4],
         s.sound_vtable, s.sound_state, s.sound_pause, s.sound_cue_key, s.sound_definition, s.xact_cue, s.readable);
}
void LogAdmissionSound(uint32_t number, const char* role, const uint8_t* base, uint32_t object) {
    Snapshot s;
    CaptureSound(base, object, s);
    LOGW("Horse admission object snapshot=%u role=%s object=%08X vtable=%08X state=%08X pause=%08X "
         "cue_key=%08X definition=%08X xact_cue=%08X readable=%08X",
         number, role, object, s.sound_vtable, s.sound_state, s.sound_pause,
         s.sound_cue_key, s.sound_definition, s.xact_cue, s.readable);
}
struct IncumbentWatch {
    uint32_t slot = 0, record = 0, owner = 0, cue = 0, instance_slot = 0, instance = 0;
    uint32_t definition = 0, tracks = 0, index = 0, track = 0, voice = 0, stream = 0;
};
using IncumbentWatches = std::array<IncumbentWatch, 2>;
IncumbentWatches LogIncumbents(uint32_t number, const uint8_t* base, uint32_t manager, uint32_t selected) {
    // The active expanded spatial pool, at most four tracks per occupant.
    // Committed reads and repeated identities are observations, not lifetime locks.
    constexpr uint32_t kTrackLimit = 4;
    IncumbentWatches watches{};
    size_t watch_count = 0;
    for (uint32_t slot = 0; slot < darkwatch::sound_pool::kCount; ++slot) {
        IncumbentWatch watch;
        const uint64_t record = uint64_t(manager) + darkwatch::sound_pool::kOffset + slot * 0x20;
        uint32_t readable = 0;
        auto field = [&](uint64_t object, uint32_t offset, uint32_t bytes, uint32_t bit) {
            uint32_t value = kMissing;
            if (object && object < kMissing && Read(base, object + offset, bytes, value)) readable |= 1u << bit;
            return value;
        };
        const uint32_t initialized = field(record, 0xC, 1, 0), occupied = field(record, 0xD, 1, 1);
        const uint32_t priority = field(record, 0x10, 4, 2), owner = field(record, 0x18, 4, 3);
        const uint32_t source = field(record, 0x1C, 4, 4);
        Snapshot sound;
        CaptureSound(base, (readable & 8) ? owner : 0, sound);
        const bool known = sound.sound_vtable == 0x43EEDC;
        const uint32_t link = known ? field(owner, 0x3C, 4, 5) : kMissing;
        const uint32_t id = known ? field(owner, 0x24, 4, 6) : kMissing;
        const uint32_t flags = known ? field(owner, 0x70, 1, 7) : kMissing;
        const bool linked = (readable & 0x2B) == 0x2B && initialized && occupied && link == record;
        LOGW("Horse incumbent snapshot=%u slot=%u record=%08X init=%08X occupied=%08X priority=%08X "
             "owner=%08X source=%08X class=%08X state=%08X pause=%08X cue_key=%08X definition=%08X "
             "cue=%08X link=%08X sound_id=%08X flags=%08X linked=%u readable=%02X sound_readable=%08X",
             number, slot, record <= UINT32_MAX ? uint32_t(record) : kMissing, initialized, occupied,
             priority, owner, source, sound.sound_vtable, sound.sound_state, sound.sound_pause,
             sound.sound_cue_key, sound.sound_definition, sound.xact_cue, link, id, flags,
             unsigned(linked), readable, sound.readable);
        if (!linked || !(sound.readable & (1u << 25)) || !sound.xact_cue || sound.xact_cue == kMissing) continue;
        uint32_t sampled = 0, truncated = 0;
        for (uint32_t instance_slot = 0; instance_slot < 3; ++instance_slot) {
            readable = 0;
            const uint32_t instance = field(sound.xact_cue, 0x28 + instance_slot * 4, 4, 0);
            const uint32_t definition = (readable & 1) ? field(instance, 0x10, 4, 1) : kMissing;
            const uint32_t state = (readable & 1) ? field(instance, 0x30, 2, 2) : kMissing;
            const uint32_t tracks = (readable & 1) ? field(instance, 0x34, 4, 3) : kMissing;
            const uint32_t count = (readable & 2) ? field(definition, 8, 1, 4) : kMissing;
            const uint32_t parent_cue = (readable & 1) ? field(instance, 0x44, 4, 5) : kMissing;
            const bool walk = (readable & 0x3B) == 0x3B && instance && tracks && tracks != kMissing && parent_cue == sound.xact_cue;
            if (walk && count > kTrackLimit - sampled) truncated |= 1u << instance_slot;
            LOGW("Horse incumbent instance snapshot=%u slot=%u instance_slot=%u instance=%08X "
                 "definition=%08X state=%08X tracks=%08X count=%08X parent_cue=%08X readable=%02X",
                 number, slot, instance_slot, instance, definition, state, tracks, count, parent_cue, readable);
            if (!walk) continue;
            for (uint32_t i = 0; i < count && sampled < kTrackLimit; ++i, ++sampled) {
                const uint64_t track = uint64_t(tracks) + uint64_t(i) * 0x88;
                readable = 0;
                const uint32_t track_flags = field(track, 0, 2, 0), voice = field(track, 4, 4, 1);
                const uint32_t parent = field(track, 8, 4, 2);
                const uint32_t previous = field(track, 0xC, 4, 3), next = field(track, 0x10, 4, 4);
                const uint32_t event_index = field(track, 0x19, 1, 5), event_definition = field(track, 0x38, 4, 6);
                const uint32_t queue = field(track, 0x40, 4, 7), remaining = field(track, 0x44, 4, 8);
                const uint32_t position = field(track, 0x48, 4, 9), decoder = field(track, 0x50, 4, 10);
                const bool owned = (readable & 6) == 6 && parent == instance;
                const uint32_t buffer = owned ? field(voice, 0x1C, 4, 11) : kMissing;
                const uint32_t stream = owned ? field(voice, 0x20, 4, 12) : kMissing;
                const uint32_t play_flags = owned ? field(voice, 0x18, 4, 13) : kMissing;
                if (slot != selected && !watch.stream && (readable & 0x1000) && stream && stream != kMissing)
                    watch = {slot, uint32_t(record), owner, sound.xact_cue, instance_slot, instance,
                             definition, tracks, i, uint32_t(track), voice, stream};
                LOGW("Horse incumbent track snapshot=%u slot=%u instance=%08X index=%u track=%08X "
                     "parent=%08X flags=%08X previous=%08X next=%08X event_index=%08X event_definition=%08X "
                     "voice=%08X buffer=%08X stream=%08X play_flags=%08X queue=%08X remaining=%08X "
                     "position=%08X decoder=%08X readable=%04X",
                     number, slot, instance, i, track <= UINT32_MAX ? uint32_t(track) : kMissing,
                     parent, track_flags, previous, next, event_index, event_definition, voice, buffer, stream,
                     play_flags, queue, remaining, position, decoder, readable);
                if (!owned || !(readable & 0x80) || !queue || queue == kMissing) continue;
                std::array<uint32_t, 14> values;
                values.fill(kMissing);
                readable = 0;
                for (uint32_t q = 0; q < 2; ++q) {
                    const uint64_t staging = uint64_t(queue) + 0x10 + q * 0x20;
                    for (uint32_t j = 0; j < 7; ++j)
                        values[q * 7 + j] = field(staging, j * 4, 4, q * 7 + j);
                }
                LOGW("Horse incumbent staging snapshot=%u slot=%u track=%08X queue=%08X "
                     "packet0=%08X bytes0=%08X marker0=%08X iosb0=%08X information0=%08X offset_low0=%08X offset_high0=%08X "
                     "packet1=%08X bytes1=%08X marker1=%08X iosb1=%08X information1=%08X offset_low1=%08X offset_high1=%08X readable=%04X",
                     number, slot, uint32_t(track), queue, values[0], values[1], values[2], values[3], values[4], values[5], values[6],
                     values[7], values[8], values[9], values[10], values[11], values[12], values[13], readable);
            }
        }
        uint32_t owner_after = kMissing, cue_after = kMissing, occupied_after = kMissing, after_readable = 0;
        if (Read(base, record + 0x18, 4, owner_after)) after_readable |= 1;
        if (Read(base, record + 0xD, 1, occupied_after)) after_readable |= 2;
        if (Read(base, uint64_t(owner) + 0x4C, 4, cue_after)) after_readable |= 4;
        LOGW("Horse incumbent bounds snapshot=%u slot=%u sampled=%u limit=%u truncated=%X "
             "owner_after=%08X cue_after=%08X occupied_after=%08X stable=%u readable=%X",
             number, slot, sampled, kTrackLimit, truncated, owner_after, cue_after, occupied_after,
             unsigned(after_readable == 7 && owner_after == owner && cue_after == sound.xact_cue && occupied_after == occupied), after_readable);
        if (watch.stream && watch_count < watches.size()) watches[watch_count++] = watch;
    }
    return watches;
}
void TraceIncumbent(uint32_t number, const uint8_t* base, const IncumbentWatch& w) {
    if (!w.stream) return;
    uint32_t value;
    auto same = [&](uint64_t address, uint32_t bytes, uint32_t expected) {
        return Read(base, address, bytes, value) && value == expected;
    };
    const bool valid = same(uint64_t(w.record) + 0xD, 1, 1) && same(uint64_t(w.record) + 0x18, 4, w.owner) &&
        same(w.owner, 4, 0x43EEDC) && same(uint64_t(w.owner) + 0x3C, 4, w.record) &&
        same(uint64_t(w.owner) + 0x4C, 4, w.cue) &&
        same(uint64_t(w.cue) + 0x28 + w.instance_slot * 4, 4, w.instance) &&
        same(uint64_t(w.instance) + 0x44, 4, w.cue) &&
        same(uint64_t(w.instance) + 0x10, 4, w.definition) &&
        Read(base, uint64_t(w.definition) + 8, 1, value) && w.index < value &&
        same(uint64_t(w.instance) + 0x34, 4, w.tracks) &&
        uint64_t(w.tracks) + uint64_t(w.index) * 0x88 == w.track &&
        same(uint64_t(w.track) + 8, 4, w.instance) && same(uint64_t(w.track) + 4, 4, w.voice) &&
        same(uint64_t(w.voice) + 0x20, 4, w.stream);
    static_assert(darkwatch::sound_pool::kCount <= 8);
    const uint64_t observation = (uint64_t(1) << 63) | (uint64_t(number) << 3) | w.slot;
    LOGW("Horse incumbent source snapshot=%u slot=%u observation=%llu owner=%08X cue=%08X instance=%08X "
         "track=%08X voice=%08X stream=%08X revalidated=%u",
         number, w.slot, (unsigned long long)observation, w.owner, w.cue, w.instance, w.track, w.voice, w.stream, unsigned(valid));
    if (valid) audio::TraceVoice(w.stream, observation, "admission-incumbent");
}
void Admission(X86Context& ctx, uint8_t* base, uint32_t site, uint32_t caller,
               uint32_t count, uint32_t offset, uint32_t expected_vtable) {
    if (!diag::Perf() || !g_depth) return;
    const auto& f = g_frames[g_depth - 1];
    auto* thread = kernel::Current();
    const bool spatial = expected_vtable != 0x43EEA8;
    const uint32_t index = spatial ? ctx.edi : ctx.esi;
    if (f.base != base || f.thread != (thread ? thread->id : 0) || index >= count ||
        uint64_t(ctx.esp) + (spatial ? 0x18 : 0x14) != ctx.ebp ||
        uint64_t(ctx.ebp) + 4 >= f.stack || ctx.ebp < 0x18) return;
    std::unique_lock<std::mutex> lock(g_lock);
    if (g_admissions == 2 || !Matches(base, f.before.event)) return;
    uint32_t returned, manager, priority, selected_priority, object, output, distance_pointer = 0, vtable;
    if (!Read(base, uint64_t(ctx.ebp) + 4, 4, returned) || returned != caller ||
        !Read(base, uint64_t(ctx.ebp) - (spatial ? 0xC : 8), 4, manager) || !manager ||
        !Read(base, uint64_t(ctx.ebp) + 8, 4, priority) ||
        !Read(base, uint64_t(ctx.ebp) - 4, 4, selected_priority) ||
        !Read(base, uint64_t(ctx.ebp) + (spatial ? 0x10 : 0xC), 4, object) || !object ||
        !Read(base, object, 4, vtable) || vtable != expected_vtable ||
        !Read(base, uint64_t(ctx.ebp) + (spatial ? 0x14 : 0x10), 4, output) || uint64_t(object) + 0x3C != output ||
        (spatial && (!Read(base, uint64_t(ctx.ebp) + 0xC, 4, distance_pointer) || uint64_t(object) + 0x68 != distance_pointer))) return;
    uint32_t distance = kMissing, selected_distance = kMissing, decision_readable = 0;
    if (spatial && Read(base, distance_pointer, 4, distance)) decision_readable |= 1;
    if (spatial && Read(base, uint64_t(ctx.ebp) - 8, 4, selected_distance)) decision_readable |= 2;
    const uint64_t record = uint64_t(manager) + offset + uint64_t(index) * (spatial ? 0x20 : 0x18);
    uint32_t readable = 0;
    auto field = [&](uint32_t field_offset, uint32_t bytes, uint32_t bit) {
        uint32_t value = kMissing;
        if (Read(base, record + field_offset, bytes, value)) readable |= 1u << bit;
        return value;
    };
    const uint32_t initialized = field(0xC, 1, 0), occupied = field(0xD, 1, 1), current_priority = field(0x10, 4, 2);
    const uint32_t selected_pointer = spatial ? field(0x14, 4, 3) : kMissing;
    uint32_t current_distance = kMissing;
    if ((readable & 8) && Read(base, selected_pointer, 4, current_distance)) readable |= 16;
    const uint32_t owner = field(spatial ? 0x18 : 0x14, 4, 5), source = spatial ? field(0x1C, 4, 6) : kMissing;
    const uint32_t number = ++g_admissions;
    // A synchronous candidate within the matched event, not proof of audible output or lifetime ownership.
    LOGW("Horse admission snapshot=%u pair=%u event=%08X tid=%X site=%08X caller=%08X manager=%08X "
         "pool_count=%u index=%u request=%08X output=%08X priority=%08X selected_priority=%08X "
         "distance_ptr=%08X distance_bits=%08X selected_distance_bits=%08X decision_readable=%02X",
         number, f.pair, f.before.event, f.thread, site, returned, manager, count, index, object, output,
         priority, selected_priority, distance_pointer, distance, selected_distance, decision_readable);
    LOGW("Horse admission slot snapshot=%u record=%08X init=%08X occupied=%08X priority=%08X "
         "distance_ptr=%08X distance_bits=%08X owner=%08X source=%08X readable=%02X",
         number, record <= 0xFFFFFFFF ? uint32_t(record) : kMissing, initialized, occupied,
         current_priority, selected_pointer, current_distance, owner, source, readable);
    LogAdmissionSound(number, "request", base, object);
    LogAdmissionSound(number, "selected", base, owner);
    const auto watches = expected_vtable == 0x43EEDC ? LogIncumbents(number, base, manager, index) : IncumbentWatches{};
    logx::Flush();
    lock.unlock();  // Never acquire the audio diagnostic lock while holding the horse recorder lock.
    for (const auto& watch : watches) TraceIncumbent(number, base, watch);
}
}  // namespace

void DarkwatchHorseReject57(X86Context& ctx, uint8_t* base) { Admission(ctx, base, 0x206013, 0x20F7D6, 57, 0x42C, 0x43EE74); }
void DarkwatchHorseReject3(X86Context& ctx, uint8_t* base) { Admission(ctx, base, 0x2060D6, 0x210468, darkwatch::sound_pool::kCount, darkwatch::sound_pool::kOffset, 0x43EEDC); }
void DarkwatchHorseReject2(X86Context& ctx, uint8_t* base) { Admission(ctx, base, 0x206178, 0x20FCBE, 2, 0xBAC, 0x43EEA8); }

void DarkwatchHorseBegin(X86Context& ctx, uint8_t* base) {
    if (!diag::Perf() || g_depth == kMaxDepth || !Matches(base, ctx.ecx)) return;
    auto* thread = kernel::Current();
    Frame f;
    f.before = Capture(base, ctx.ecx); f.base = base; f.stack = ctx.esp;
    f.thread = thread ? thread->id : 0;
    Read(base, ctx.esp, 4, f.caller);
    {
        std::lock_guard<std::mutex> lock(g_lock);
        auto& seen = Find(f);
        if ((!seen.have_before || seen.before != f.before) && g_pairs < kMaxPairs) {
            f.pair = ++g_pairs;
            Log("before", f, f.before);
        }
        seen.before = f.before; seen.have_before = true;
    }
    g_frames[g_depth++] = f;
    horse_voice::Begin(base, f.before.event, f.stack, f.thread);
}

void DarkwatchHorseEnd(X86Context& ctx, uint8_t* base) {
    if (!diag::Perf() || !g_depth) return;
    auto* thread = kernel::Current();
    const auto& top = g_frames[g_depth - 1];
    // 22EF8B establishes EBP=entry ESP-4. Nonmatching nested events must not
    // consume an outer horse frame, even when they reuse the same event object.
    if (top.base != base || top.before.event != ctx.esi || uint64_t(ctx.ebp) + 4 != top.stack ||
        top.thread != (thread ? thread->id : 0)) return;
    Frame f = top;
    --g_depth;
    horse_voice::End(base, f.before.event, f.stack, f.thread);
    const Snapshot after = Capture(base, ctx.esi);
    std::lock_guard<std::mutex> lock(g_lock);
    auto& seen = Find(f);
    if (!f.pair && (!seen.have_after || seen.after != after) && g_pairs < kMaxPairs) {
        f.pair = ++g_pairs;
        Log("before", f, f.before);
    }
    if (f.pair) { Log("after", f, after); logx::Flush(); }
    seen.before = f.before; seen.after = after; seen.have_before = seen.have_after = true;
}
