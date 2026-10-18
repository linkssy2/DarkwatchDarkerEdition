#include "cri_diagnostic.h"
#include <array>
#include <cstring>
#include <mutex>
#include "core/diag.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

namespace {
// Read-only witnesses for the original CRI owner/ring lifetime. The per-ring
// critical section does not span the caller's two consecutive acquisitions.
constexpr uint32_t kPool = 0x004F2B60, kPoolEnd = kPool + 0x4000;
constexpr uint32_t kMissing = 0xFFFFFFFF;
constexpr size_t kHistory = 128, kMaxFlushes = 4, kMaxCriticalFlushes = 2;
enum class Kind { Create, Destroy, PoolInitialize, PoolRelease, OwnerAcquire,
    OwnerGet, OwnerDestroy, ChunkBegin, ChunkFirst, ChunkSecond, ChunkEnd,
    Divide, Compare, WorkerBegin, WorkerEnd, DrainBegin, DrainEnd,
    HandshakeBegin, HandshakeEnd, WorkerAcknowledge, WorkerSuspend,
    DestroyCleared, PoolInitializeCleared, PoolReleaseCleared,
    DecoderCallback, DecoderCleared, DecoderPublished };
constexpr const char* kNames[] = {"create", "destroy", "pool-init", "pool-release",
    "owner-acquire", "owner-get", "owner-destroy", "chunk-begin", "chunk-first",
    "chunk-second", "chunk-end", "divide", "compare", "worker-begin", "worker-end",
    "drain-begin", "drain-end", "handshake-begin", "handshake-end", "worker-ack", "worker-suspend",
    "destroy-cleared", "pool-init-cleared", "pool-release-cleared",
    "decoder-callback", "decoder-cleared", "decoder-published"};
struct Record {
    uint64_t sequence = 0;
    Kind kind{};
    uint32_t thread = 0, caller = kMissing, owner = 0, descriptor = 0, ring = 0, generation = 0;
    uint32_t capacity = kMissing, used = kMissing, read = kMissing, write = kMissing;
    uint32_t state = kMissing, enabled = kMissing, descriptor_ring = kMissing;
    uint32_t wrapper = 0, busy = kMissing, block = kMissing, global_block = kMissing;
    uint32_t handshake = kMissing, worker = kMissing, suspend = kMissing;
    uint32_t cs_owner = kMissing, cs_count = kMissing, cs_recursion = kMissing;
    uint32_t available = 0, pool_references = kMissing, readable = 0;
    uint32_t decoder_cached_table = kMissing, decoder_current_table = kMissing;
    uint32_t decoder_cached_callback = kMissing, decoder_current_callback = kMissing;
    uint64_t owner_observation = 0;
};
struct Active { uint32_t thread = 0, ring = 0, owner = 0, descriptor = 0; };
std::mutex g_lock;
std::array<Record, kHistory> g_history;
std::array<uint32_t, 256> g_generation{};
std::array<Active, 32> g_active{};
uint64_t g_sequence = 0;
size_t g_flushes = 0, g_critical_flushes = 0;
thread_local uint32_t g_owner = 0, g_descriptor = 0, g_wrapper = 0;
thread_local uint64_t g_owner_observation = 0;

bool Enabled() {
    return diag::Perf();
}
uint32_t Read(const uint8_t* base, uint64_t address, bool* readable = nullptr) {
    if (readable) *readable = false;
    if (!base || !address || address + 4 > (uint64_t(1) << 32)) return kMissing;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < address + 4; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return kMissing;
    uint32_t value;
    std::memcpy(&value, base + address, 4);
    if (readable) *readable = true;
    return value;
}
uint32_t Field(const uint8_t* base, uint32_t object, uint32_t offset) {
    return object && object != kMissing ? Read(base, uint64_t(object) + offset) : kMissing;
}
uint32_t Argument(const X86Context& ctx, const uint8_t* base, uint32_t index) {
    return Read(base, uint64_t(ctx.esp) + 4 * index);
}
void Flush(const char* reason, bool critical = false) {
    auto& count = critical ? g_critical_flushes : g_flushes;
    if (count >= (critical ? kMaxCriticalFlushes : kMaxFlushes)) return;
    ++count;
    LOGW("CRI lifetime history reason=%s critical=%u flush=%zu sequence=%llu missing=FFFFFFFF", reason, unsigned(critical), count,
         static_cast<unsigned long long>(g_sequence));
    const uint64_t first = g_sequence > kHistory ? g_sequence - kHistory : 0;
    for (uint64_t i = first; i < g_sequence; ++i) {
        const auto& r = g_history[i % kHistory];
        LOGW("CRI event seq=%llu kind=%s tid=%X caller=%08X owner=%08X descriptor=%08X ring=%08X gen=%u "
             "capacity=%08X used=%08X read=%08X write=%08X state=%08X enabled=%08X descriptor_ring=%08X "
             "wrapper=%08X busy=%08X block=%08X global_block=%08X handshake=%08X worker=%08X suspend=%08X "
             "cs_owner=%08X cs_count=%08X cs_recursion=%08X available=%08X pool_refs=%08X readable=%08X owner_observation=%llu "
             "decoder_cached_table=%08X decoder_current_table=%08X decoder_cached_callback=%08X decoder_current_callback=%08X",
             static_cast<unsigned long long>(r.sequence), kNames[size_t(r.kind)], r.thread, r.caller,
             r.owner, r.descriptor, r.ring, r.generation, r.capacity, r.used, r.read, r.write,
             r.state, r.enabled, r.descriptor_ring, r.wrapper, r.busy, r.block, r.global_block,
             r.handshake, r.worker, r.suspend, r.cs_owner, r.cs_count, r.cs_recursion, r.available,
             r.pool_references, r.readable, static_cast<unsigned long long>(r.owner_observation),
             r.decoder_cached_table, r.decoder_current_table, r.decoder_cached_callback, r.decoder_current_callback);
    }
    logx::Flush();
}
void Observe(X86Context& ctx, uint8_t* base, Kind kind) {
    if (!Enabled()) return;
    uint32_t decoder_owner = ctx.esi;
    if (kind == Kind::DecoderCleared) {
        decoder_owner = Argument(ctx, base, 2);
        // This loop clears nine records. Only index 3 writes owner+1FFC.
        if (ctx.edx != 3 || !decoder_owner || decoder_owner == kMissing ||
            uint64_t(decoder_owner) + 0x1F28 + uint64_t(ctx.edx) * 0x44 != ctx.eax) return;
    }
    if (kind == Kind::DecoderPublished) {
        const uint32_t argument = Argument(ctx, base, 5);
        if (!decoder_owner || decoder_owner == kMissing || argument != decoder_owner ||
            ctx.ebx != decoder_owner || ctx.eax != ctx.edi ||
            uint64_t(decoder_owner) + 0x33B8 != ctx.edi) return;
    }
    auto* thread = kernel::Current();
    const uint32_t tid = thread ? thread->id : 0;
    std::lock_guard<std::mutex> lock(g_lock);
    Record r;
    r.kind = kind; r.thread = tid; r.available = ctx.ebp;
    uint32_t caller_slot = 0;
    switch (kind) {
        case Kind::Create: case Kind::Destroy: case Kind::PoolInitialize: case Kind::PoolRelease:
        case Kind::DestroyCleared: case Kind::PoolInitializeCleared: case Kind::PoolReleaseCleared:
        case Kind::OwnerDestroy: case Kind::DrainEnd: case Kind::WorkerAcknowledge:
        case Kind::DecoderCleared: caller_slot = 1; break;
        case Kind::Divide: case Kind::WorkerBegin: case Kind::WorkerEnd: case Kind::WorkerSuspend: caller_slot = 2; break;
        case Kind::OwnerAcquire: caller_slot = 6; break;
        case Kind::ChunkFirst: caller_slot = 7; break;
        case Kind::ChunkSecond: caller_slot = 5; break;
        case Kind::Compare: case Kind::DecoderCallback: caller_slot = 9; break;
        case Kind::DecoderPublished: caller_slot = 4; break;
        default: break;
    }
    auto capture = [&](uint64_t address, uint32_t bit) {
        bool readable;
        uint32_t value = Read(base, address, &readable);
        if (readable) r.readable |= 1u << bit;
        return value;
    };
    auto field = [&](uint32_t object, uint32_t offset, uint32_t bit) {
        return object && object != kMissing ? capture(uint64_t(object) + offset, bit) : kMissing;
    };
    r.caller = capture(uint64_t(ctx.esp) + uint64_t(caller_slot) * 4, 0);
    if (kind == Kind::OwnerAcquire) { g_owner = ctx.edx; g_descriptor = ctx.eax; }
    if (kind == Kind::OwnerGet) {
        g_owner = Argument(ctx, base, 1);
        const uint32_t index = Argument(ctx, base, 2);
        // The decoder has three descriptors. Invalid indices are recorded, never followed.
        const uint64_t descriptor = uint64_t(g_owner) + 0x1308 + uint64_t(index) * 0x74;
        g_descriptor = g_owner && g_owner != kMissing && index < 3 && descriptor < (uint64_t(1) << 32)
            ? uint32_t(descriptor) : 0;
    }
    if (kind == Kind::OwnerDestroy) { g_owner = ctx.ecx; g_descriptor = ctx.esi; }
    if (kind == Kind::WorkerBegin) { g_wrapper = ctx.esi; g_owner = Field(base, g_wrapper, 0x40); }
    if (kind == Kind::DrainBegin) { g_wrapper = Argument(ctx, base, 1); g_owner = Field(base, g_wrapper, 0x40); }
    if (kind == Kind::OwnerAcquire || kind == Kind::OwnerGet || kind == Kind::OwnerDestroy ||
        kind == Kind::WorkerBegin || kind == Kind::DrainBegin) g_owner_observation = g_sequence + 1;
    if (kind == Kind::DecoderCallback || kind == Kind::DecoderCleared || kind == Kind::DecoderPublished) {
        // These boundaries carry their own owner, independent of the older TLS ring observation.
        r.owner = decoder_owner; r.owner_observation = g_sequence + 1;
        r.decoder_current_table = field(decoder_owner, 0x1FFC, 18);
        r.decoder_current_callback = field(r.decoder_current_table, 0x3C, 20);
        if (kind == Kind::DecoderCallback) {
            r.decoder_cached_table = ctx.ebx;
            r.decoder_cached_callback = field(ctx.ebx, 0x3C, 19);
        }
    } else {
        r.owner = g_owner; r.descriptor = g_descriptor; r.wrapper = g_wrapper;
        r.owner_observation = g_owner_observation;
    }
    switch (kind) {
        case Kind::Create: r.ring = ctx.esi; break;
        case Kind::Destroy: case Kind::DestroyCleared: r.ring = ctx.edx; break;
        case Kind::PoolInitialize: case Kind::PoolRelease:
        case Kind::PoolInitializeCleared: case Kind::PoolReleaseCleared: r.ring = kPool; break;
        case Kind::OwnerDestroy: r.ring = ctx.eax; break;
        case Kind::ChunkBegin: case Kind::ChunkFirst: case Kind::ChunkSecond: case Kind::ChunkEnd:
        case Kind::Compare: r.ring = ctx.esi; break;
        case Kind::Divide: r.ring = ctx.ecx; break;
        case Kind::OwnerAcquire: case Kind::OwnerGet: r.ring = Field(base, g_descriptor, 0x14); break;
        default: break;
    }
    r.capacity = field(r.ring, 0x20, 1); r.used = field(r.ring, 0xC, 2);
    r.read = field(r.ring, 0x18, 3); r.write = field(r.ring, 0x14, 4);
    r.state = field(r.descriptor, 0, 5); r.enabled = field(r.descriptor, 4, 6);
    r.descriptor_ring = field(r.descriptor, 0x14, 7);
    r.busy = field(r.wrapper, 0x64, 8); r.block = field(r.wrapper, 0x60, 9);
    r.global_block = capture(0x005F6D44, 10); r.handshake = capture(0x004C2934, 11);
    r.worker = capture(0x00505CB0, 12); r.suspend = thread ? uint32_t(thread->suspend.load()) : kMissing;
    if (thread) r.readable |= 1u << 13;
    r.cs_owner = capture(0x00505CD8, 14); r.cs_count = capture(0x00505CD0, 15);
    r.cs_recursion = capture(0x00505CD4, 16); r.pool_references = capture(0x004C3828, 17);
    if (r.ring >= kPool && r.ring < kPoolEnd && !((r.ring - kPool) & 0x3F)) {
        auto& generation = g_generation[(r.ring - kPool) / 0x40];
        if (kind == Kind::Create) ++generation;
        r.generation = generation;
    }
    bool overlaps = false;
    for (auto& active : g_active) {
        if (active.thread && active.thread != tid && active.ring &&
            ((kind == Kind::DestroyCleared && active.ring == r.ring) ||
             kind == Kind::PoolInitializeCleared || kind == Kind::PoolReleaseCleared)) overlaps = true;
        if (kind == Kind::ChunkEnd && active.thread == tid) active = {};
    }
    if (kind == Kind::ChunkBegin && tid) {
        for (auto& active : g_active) if (!active.thread || active.thread == tid) {
            active = {tid, r.ring, r.owner, r.descriptor}; break;
        }
    }
    r.sequence = ++g_sequence;
    g_history[(g_sequence - 1) % kHistory] = r;
    if (overlaps) Flush("clear-overlaps-consumer");
    else if ((kind == Kind::Divide || kind == Kind::ChunkSecond) && r.capacity == 0) Flush("zero-capacity", true);
    else if (kind == Kind::Compare && !r.ring) Flush("null-comparison-ring", true);
    else if (kind == Kind::DecoderCallback && !r.decoder_cached_table) Flush("null-decoder-callback-table", true);
    if (kind == Kind::WorkerEnd || kind == Kind::DrainEnd) {
        g_owner = g_descriptor = g_wrapper = 0; g_owner_observation = 0;
    }
}
}  // namespace

#define CRI_HOOK(name, kind) void name(X86Context& ctx, uint8_t* base) { Observe(ctx, base, Kind::kind); }
CRI_HOOK(DarkwatchCriCreate, Create)
CRI_HOOK(DarkwatchCriDestroy, Destroy)
CRI_HOOK(DarkwatchCriDestroyCleared, DestroyCleared)
CRI_HOOK(DarkwatchCriPoolInitialize, PoolInitialize)
CRI_HOOK(DarkwatchCriPoolRelease, PoolRelease)
CRI_HOOK(DarkwatchCriPoolInitializeCleared, PoolInitializeCleared)
CRI_HOOK(DarkwatchCriPoolReleaseCleared, PoolReleaseCleared)
CRI_HOOK(DarkwatchCriOwnerAcquire, OwnerAcquire)
CRI_HOOK(DarkwatchCriOwnerGet, OwnerGet)
CRI_HOOK(DarkwatchCriOwnerDestroy, OwnerDestroy)
CRI_HOOK(DarkwatchCriChunkBegin, ChunkBegin)
CRI_HOOK(DarkwatchCriChunkFirst, ChunkFirst)
CRI_HOOK(DarkwatchCriChunkSecond, ChunkSecond)
CRI_HOOK(DarkwatchCriChunkEnd, ChunkEnd)
CRI_HOOK(DarkwatchCriDivide, Divide)
CRI_HOOK(DarkwatchCriCompare, Compare)
CRI_HOOK(DarkwatchCriWorkerBegin, WorkerBegin)
CRI_HOOK(DarkwatchCriWorkerEnd, WorkerEnd)
CRI_HOOK(DarkwatchCriDrainBegin, DrainBegin)
CRI_HOOK(DarkwatchCriDrainEnd, DrainEnd)
CRI_HOOK(DarkwatchCriHandshakeBegin, HandshakeBegin)
CRI_HOOK(DarkwatchCriHandshakeEnd, HandshakeEnd)
CRI_HOOK(DarkwatchCriWorkerAcknowledge, WorkerAcknowledge)
CRI_HOOK(DarkwatchCriWorkerSuspend, WorkerSuspend)
CRI_HOOK(DarkwatchCriDecoderCallback, DecoderCallback)
CRI_HOOK(DarkwatchCriDecoderCleared, DecoderCleared)
CRI_HOOK(DarkwatchCriDecoderPublished, DecoderPublished)
#undef CRI_HOOK
