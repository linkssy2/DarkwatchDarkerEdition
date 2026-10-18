#include "horse_voice_diagnostic.h"
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
constexpr size_t kDepth = 8, kCandidates = 8, kTracks = 8, kRegistry = 4;
struct Node {
    uint32_t instance = 0, track = 0, flags = kMissing, owner = kMissing, voice = kMissing;
    uint32_t buffer = kMissing, stream = kMissing, play_flags = kMissing, readable = 0;
    bool operator==(const Node&) const = default;
};
struct Graph {
    uint32_t event = 0, parameters = 0, object = 0, control = 0, vtable = 0, cue = 0;
    uint32_t state = kMissing, paused = kMissing, count = 0, truncated = 0, readable = 0;
    std::array<uint32_t, 3> instances{kMissing, kMissing, kMissing}, track_counts{kMissing, kMissing, kMissing};
    std::array<Node, 3 * kTracks> nodes{};
    bool valid = false, known_class = false;
    bool operator==(const Graph&) const = default;
};
struct Start {
    uint32_t thread = 0, stack = 0, caller = kMissing, voice = 0, track = 0, instance = 0;
    uint32_t buffer = kMissing, stream = kMissing, play_flags = kMissing, result = kMissing;
    uint32_t readable = 0, owner_event = 0;
    uint64_t observation = 0;
    uint8_t* base = nullptr;
    bool known_caller = false, returned = false, asynchronous = false;
    Graph expected;
};
struct Event {
    uint8_t* base = nullptr;
    uint32_t event = 0, stack = 0, thread = 0, count = 0;
    uint64_t observation = 0;
    std::array<Start, kCandidates> starts{};
};
struct Registered { uint8_t* base = nullptr; Graph graph; };
std::mutex g_lock;
std::array<Registered, kRegistry> g_registered{};
size_t g_next_registered = 0;
uint64_t g_observation = 0;
uint32_t g_graph_lines = 0, g_start_lines = 0, g_stats_lines = 0;
uint32_t g_graph_dropped = 0, g_start_dropped = 0, g_candidate_dropped = 0, g_frame_dropped = 0;
uint32_t g_watch_evicted = 0;
uint32_t g_audio_requests = 0;
uint32_t g_audio_rejected = 0;
thread_local std::array<Event, kDepth> g_events;
thread_local size_t g_event_depth = 0;
thread_local std::array<Start, kDepth> g_starts;
thread_local size_t g_start_depth = 0;

bool Span(const uint8_t* base, uint64_t address, uint32_t bytes) {
    if (!base || !address || !bytes || address + bytes > (uint64_t(1) << 32)) return false;
    for (uint64_t p = address & ~(uint64_t(mem::kPage) - 1); p < address + bytes; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
bool Read(const uint8_t* base, uint64_t address, uint32_t bytes, uint32_t& value) {
    if (bytes > 4 || !Span(base, address, bytes)) return false;
    value = 0; std::memcpy(&value, base + address, bytes); return true;
}
template<size_t N> bool Text(const uint8_t* base, uint32_t ref, const char (&text)[N]) {
    return ref && Span(base, uint64_t(ref) + 2, N) && !std::memcmp(base + uint64_t(ref) + 2, text, N);
}
Graph Capture(uint8_t* base, uint32_t event) {
    Graph g; g.event = event;
    uint32_t vtable, bank, cue, represented;
    if (!Read(base, event, 4, vtable) || vtable != 0x440D28 ||
        !Read(base, uint64_t(event) + 0x54, 4, g.parameters) || !g.parameters ||
        !Read(base, g.parameters, 4, vtable) || vtable != 0x42D400 ||
        !Read(base, uint64_t(g.parameters) + 4, 4, bank) || !Text(base, bank, "EMITTER") ||
        !Read(base, uint64_t(g.parameters) + 8, 4, cue) || !Text(base, cue, "HORSE_WAKE01") ||
        !Read(base, uint64_t(event) + 0x70, 4, g.object) || !g.object ||
        !Read(base, uint64_t(event) + 0x74, 4, g.control) || !g.control ||
        !Read(base, uint64_t(g.control) + 4, 4, represented) || represented != g.object ||
        !Read(base, g.object, 4, g.vtable)) return g;
    uint32_t cue_offset = 0;
    if (g.vtable == 0x43EE2C) cue_offset = 0x3C;
    else if (g.vtable == 0x43EE74 || g.vtable == 0x43EEA8 || g.vtable == 0x43EEDC) cue_offset = 0x4C;
    if (!cue_offset) return g;
    g.known_class = true;
    if (Read(base, uint64_t(g.object) + 0xC, 4, g.state)) g.readable |= 1;
    if (Read(base, uint64_t(g.object) + 0x18, 1, g.paused)) g.readable |= 2;
    if (!Read(base, uint64_t(g.object) + cue_offset, 4, g.cue)) return g;
    g.readable |= 4;
    g.valid = true;
    if (!g.cue) return g;
    for (uint32_t slot = 0; slot < 3; ++slot) {
        uint32_t instance = 0, definition = 0, tracks = 0, count = 0;
        if (!Read(base, uint64_t(g.cue) + 0x28 + slot * 4, 4, instance)) continue;
        g.readable |= 1u << (3 + slot);
        g.instances[slot] = instance;
        if (!instance || !Read(base, uint64_t(instance) + 0x10, 4, definition)) continue;
        g.readable |= 1u << (6 + slot);
        if (!definition || !Read(base, uint64_t(definition) + 8, 1, count)) continue;
        g.readable |= 1u << (9 + slot);
        g.track_counts[slot] = count;
        if (count > kTracks) g.truncated |= 1u << slot;
        if (!Read(base, uint64_t(instance) + 0x34, 4, tracks)) continue;
        g.readable |= 1u << (12 + slot);
        if (!tracks) continue;
        for (uint32_t i = 0; i < count && i < kTracks; ++i) {
            const uint64_t track = uint64_t(tracks) + i * 0x88;
            if (track > UINT32_MAX) break;
            Node& n = g.nodes[g.count++]; n.instance = instance; n.track = uint32_t(track);
            auto field = [&](uint64_t address, uint32_t bytes, uint32_t bit, uint32_t& value) {
                if (Read(base, address, bytes, value)) n.readable |= 1u << bit;
            };
            field(track, 2, 0, n.flags); field(track + 4, 4, 1, n.voice); field(track + 8, 4, 2, n.owner);
            if ((n.readable & 6) == 6 && n.owner == instance && n.voice) {
                field(uint64_t(n.voice) + 0x1C, 4, 3, n.buffer);
                field(uint64_t(n.voice) + 0x20, 4, 4, n.stream);
                field(uint64_t(n.voice) + 0x18, 4, 5, n.play_flags);
            }
        }
    }
    return g;
}
bool SameIdentity(const Graph& a, const Graph& b) {
    return a.valid && b.valid && a.cue && a.event == b.event && a.parameters == b.parameters &&
        a.object == b.object && a.control == b.control && a.vtable == b.vtable && a.cue == b.cue;
}
bool Owns(const Graph& g, const Start& s) {
    if (!g.valid || !g.cue || !s.known_caller || !s.voice) return false;
    for (uint32_t i = 0; i < g.count; ++i) {
        const Node& n = g.nodes[i];
        if ((n.readable & 6) == 6 && n.track == s.track && n.instance == s.instance &&
            n.owner == s.instance && n.voice == s.voice) return true;
    }
    return false;
}
void TraceOwnedStream(const Start& s, bool confirmed) {
    if (!confirmed || !s.returned || s.result || !s.known_caller || g_audio_requests >= 2) return;
    if ((s.readable & 2) && !s.stream) return;  // A buffer-only source is not a stream watch.
    // These are observations without a guest lifetime lock, not acquired ownership.
    uint32_t stream = kMissing, voice = kMissing, readable = 0;
    if (Read(s.base, uint64_t(s.track) + 4, 4, voice)) readable |= 1;
    if (Read(s.base, uint64_t(s.voice) + 0x20, 4, stream)) readable |= 2;
    if (!(s.readable & 2) || s.stream == kMissing || readable != 3 ||
        voice != s.voice || stream != s.stream) {
        if (g_audio_rejected < 2) {
            ++g_audio_rejected;
            LOGW("Horse source rejected observation=%llu expected_voice=%08X current_voice=%08X "
                 "expected_stream=%08X current_stream=%08X entry_readable=%X current_readable=%X",
                 (unsigned long long)s.observation, s.voice, voice, s.stream, stream, s.readable, readable);
        }
        return;
    }
    ++g_audio_requests;
    std::array<uint32_t, 8> source, entry;
    source.fill(kMissing); entry.fill(kMissing);
    uint32_t source_readable = 0, entry_readable = 0;
    auto field = [&](uint64_t address, uint32_t bytes, uint32_t bit,
                     std::array<uint32_t, 8>& values, uint32_t& readable) {
        if (Read(s.base, address, bytes, values[bit])) readable |= 1u << bit;
    };
    // Original XACT preparation: entry index is WORD, all remaining fields are DWORD.
    field(uint64_t(s.track) + 0x56, 2, 0, source, source_readable);
    field(uint64_t(s.track) + 0x74, 4, 1, source, source_readable);
    field(uint64_t(s.voice) + 0x0C, 4, 2, source, source_readable);
    for (uint32_t i = 0; i < 5; ++i)
        field(uint64_t(s.track) + 0x3C + 4 * i, 4, 3 + i, source, source_readable);
    // Raw wave-entry metadata can describe encoded input to a decoder, not native PCM.
    for (uint32_t i = 0; i < 6; ++i)
        field(uint64_t(s.track) + 0x5C + 4 * i, 4, i, entry, entry_readable);
    field(uint64_t(s.voice) + 0x150, 4, 6, entry, entry_readable);
    if ((entry_readable & 0x40) && entry[6] && entry[6] != kMissing)
        field(uint64_t(entry[6]) + 0x1C, 4, 7, entry, entry_readable);
    LOGW("Horse source observation=%llu event=%08X track=%08X voice=%08X stream=%08X index=%04X "
         "track_bank=%08X voice_bank=%08X prefetch=%08X queue=%08X remaining=%08X position=%08X decoder=%08X readable=%02X",
         (unsigned long long)s.observation, s.owner_event, s.track, s.voice, stream,
         source[0], source[1], source[2], source[3], source[4], source[5], source[6], source[7], source_readable);
    LOGW("Horse entry observation=%llu raw=%08X/%08X/%08X/%08X/%08X/%08X parent_voice=%08X parent_buffer=%08X readable=%02X",
         (unsigned long long)s.observation, entry[0], entry[1], entry[2], entry[3], entry[4], entry[5],
         entry[6], entry[7], entry_readable);
    // This post-return observation can miss the first mixed frames; it never replays samples.
    audio::TraceVoice(stream, s.observation);
}
void LogStart(const Start& s, bool confirmed) {
    if (g_start_lines >= 32) { ++g_start_dropped; return; }
    ++g_start_lines;
    LOGW("Horse voice start observation=%llu event=%08X async=%u confirmed=%u returned=%u tid=%X caller=%08X "
         "track=%08X instance=%08X voice=%08X buffer=%08X stream=%08X flags=%08X result=%08X readable=%X",
         (unsigned long long)s.observation, s.owner_event, unsigned(s.asynchronous), unsigned(confirmed),
         unsigned(s.returned), s.thread, s.caller, s.track, s.instance, s.voice, s.buffer, s.stream,
         s.play_flags, s.result, s.readable);
    TraceOwnedStream(s, confirmed);
}
void LogGraph(const Graph& g, uint64_t observation) {
    if (g_graph_lines >= 32) { ++g_graph_dropped; return; }
    ++g_graph_lines;
    LOGW("Horse voice graph observation=%llu event=%08X object=%08X class=%08X valid=%u known_class=%u "
         "state=%08X paused=%08X cue=%08X instances=%08X/%08X/%08X tracks=%u/%u/%u nodes=%u truncated=%X readable=%X",
         (unsigned long long)observation, g.event, g.object, g.vtable, unsigned(g.valid), unsigned(g.known_class),
         g.state, g.paused, g.cue, g.instances[0], g.instances[1], g.instances[2],
         g.track_counts[0], g.track_counts[1], g.track_counts[2], g.count, g.truncated, g.readable);
    for (uint32_t i = 0; i < g.count; ++i) {
        if (g_graph_lines >= 32) { ++g_graph_dropped; continue; }
        ++g_graph_lines; const Node& n = g.nodes[i];
        LOGW("Horse voice node observation=%llu instance=%08X track=%08X owner=%08X flags=%04X voice=%08X "
             "buffer=%08X stream=%08X play_flags=%08X readable=%X", (unsigned long long)observation,
             n.instance, n.track, n.owner, n.flags, n.voice, n.buffer, n.stream, n.play_flags, n.readable);
    }
}
void Stats() {
    if (g_stats_lines >= 8) return;
    ++g_stats_lines;
    LOGW("Horse voice bounds graph_lines=%u start_lines=%u graph_dropped=%u start_dropped=%u candidates_dropped=%u frames_dropped=%u watch_evicted=%u",
         g_graph_lines, g_start_lines, g_graph_dropped, g_start_dropped, g_candidate_dropped, g_frame_dropped, g_watch_evicted);
}
uint32_t Thread() { auto* t = kernel::Current(); return t ? t->id : 0; }
}  // namespace

void horse_voice::Begin(uint8_t* base, uint32_t event, uint32_t stack, uint32_t thread) {
    if (!diag::Perf()) return;
    std::lock_guard<std::mutex> lock(g_lock);
    if (g_event_depth == kDepth) { ++g_frame_dropped; return; }
    Event f; f.base = base; f.event = event; f.stack = stack; f.thread = thread; f.observation = ++g_observation;
    g_events[g_event_depth++] = f;
}
void horse_voice::End(uint8_t* base, uint32_t event, uint32_t stack, uint32_t thread) {
    if (!diag::Perf() || !g_event_depth) return;
    const Event& top = g_events[g_event_depth - 1];
    if (top.base != base || top.event != event || top.stack != stack || top.thread != thread) return;
    Event f = top; --g_event_depth;
    const Graph graph = Capture(base, event);
    std::lock_guard<std::mutex> lock(g_lock);
    Registered* slot = nullptr;
    for (auto& r : g_registered) if (r.base == base && r.graph.event == event) { slot = &r; break; }
    if (!slot) {
        slot = &g_registered[g_next_registered++ % kRegistry];
        if (slot->base) ++g_watch_evicted;
    }
    if (slot->base != base || slot->graph != graph) LogGraph(graph, f.observation);
    slot->base = base; slot->graph = graph;
    for (uint32_t i = 0; i < f.count; ++i) LogStart(f.starts[i], Owns(graph, f.starts[i]));
    // If an observed call did not reach its normal return, do not fabricate an HRESULT.
    size_t retained = 0;
    for (size_t i = 0; i < g_start_depth; ++i) {
        if (g_starts[i].observation == f.observation) LogStart(g_starts[i], Owns(graph, g_starts[i]));
        else g_starts[retained++] = g_starts[i];
    }
    g_start_depth = retained;
    Stats(); logx::Flush();
}
void DarkwatchHorseVoiceStart(X86Context& ctx, uint8_t* base) {
    if (!diag::Perf()) return;
    Start s; s.base = base; s.thread = Thread(); s.stack = ctx.esp; s.voice = ctx.eax;
    Read(base, ctx.esp, 4, s.caller);
    if (s.caller == 0x3EBD84 || s.caller == 0x3EA044) {
        s.track = ctx.esi; s.known_caller = s.track && Read(base, uint64_t(s.track) + 8, 4, s.instance);
        if (s.caller == 0x3EBD84 && s.instance != ctx.edi) s.known_caller = false;
    } else if (s.caller == 0x3E827C) {
        uint32_t tracks = 0;
        s.instance = ctx.edi;
        if (s.instance && !(ctx.ebx % 0x88) && Read(base, uint64_t(s.instance) + 0x34, 4, tracks) &&
            tracks && uint64_t(tracks) + ctx.ebx <= UINT32_MAX) {
            s.track = tracks + ctx.ebx; s.known_caller = true;
        }
    }
    if (s.voice) {
        if (Read(base, uint64_t(s.voice) + 0x1C, 4, s.buffer)) s.readable |= 1;
        if (Read(base, uint64_t(s.voice) + 0x20, 4, s.stream)) s.readable |= 2;
        if (Read(base, uint64_t(s.voice) + 0x18, 4, s.play_flags)) s.readable |= 4;
    }
    std::lock_guard<std::mutex> lock(g_lock);
    if (g_start_depth == kDepth) { ++g_frame_dropped; return; }
    if (g_event_depth) {
        const auto& f = g_events[g_event_depth - 1];
        if (f.base != base || f.thread != s.thread) return;
        s.observation = f.observation; s.owner_event = f.event;
    } else {
        for (const auto& r : g_registered) if (r.base == base && r.graph.valid && r.graph.cue) {
            Graph now = Capture(base, r.graph.event);
            if (SameIdentity(now, r.graph) && Owns(now, s)) {
                s.asynchronous = true; s.expected = now; s.owner_event = now.event;
                s.observation = ++g_observation; break;
            }
        }
        if (!s.asynchronous) return;
    }
    g_starts[g_start_depth++] = s;
}
void DarkwatchHorseVoiceEnd(X86Context& ctx, uint8_t* base) {
    if (!diag::Perf() || !g_start_depth) return;
    const Start& top = g_starts[g_start_depth - 1];
    if (top.base != base || top.thread != Thread() || uint64_t(ctx.ebp) + 4 != top.stack) return;
    Start s = top; --g_start_depth; s.result = ctx.eax; s.returned = true;
    std::lock_guard<std::mutex> lock(g_lock);
    if (s.asynchronous) {
        const Graph now = Capture(base, s.owner_event);
        LogStart(s, SameIdentity(now, s.expected) && Owns(now, s));
        Stats(); logx::Flush();
    } else {
        for (size_t i = g_event_depth; i; --i) {
            auto& f = g_events[i - 1];
            if (f.observation != s.observation) continue;
            if (f.count < kCandidates) f.starts[f.count++] = s;
            else ++g_candidate_dropped;
            return;
        }
        LogStart(s, false);
    }
}
