// Read-only, opt-in witnesses for the original repeated skin-palette producer.
// The release translation retains its original weak entry points unchanged.
#ifndef XBE_RELEASE
#include <array>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <utility>
#include "core/diag.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"

extern "C" void __imp__sub_00260510(X86Context&, uint8_t*);
extern "C" void __imp__sub_00260D40(X86Context&, uint8_t*);

namespace {
constexpr size_t kBones = 64, kActors = 32, kPairs = 8;
constexpr uint32_t kMissing = 0xFFFFFFFF;
struct Matrix {
    bool readable = false;
    std::array<uint32_t, 16> words{};
};
struct Frame {
    uint32_t address = 0, root = kMissing, root_flags = kMissing;
    Matrix local, world;
};
struct Bone {
    uint32_t index = kMissing;
    Matrix inverse, pose;
    Frame frame;
};
struct Pose {
    bool valid = false;
    uint32_t hierarchy = kMissing, flags = kMissing, poses = kMissing, nodes = kMissing;
    uint32_t inverse = kMissing, count = 0, inverse_mask = kMissing;
    Frame atomic_frame;
    std::array<Bone, kBones> bones{};
};
struct Setup {
    uint32_t atomic = 0, caller = kMissing;
    uint64_t sequence = 0;
    Frame before, after;
};
struct Record {
    uint64_t sequence = 0, milliseconds = 0;
    uint32_t caller = kMissing, thread = 0, atomic = 0, skin = 0, output = 0;
    uint32_t fcw = 0, mxcsr = 0, simulation_clock_bits = kMissing;
    bool output_readable = false, projection_readable = false;
    std::array<uint32_t, 20> projection{};
    std::array<uint32_t, kBones * 12> palette{};
    Setup setup;
    Pose before, after;
};
struct Actor { unsigned emitted = 0; Record record; };
thread_local std::array<Actor, kActors> g_actors;
thread_local size_t g_next_actor = 0;
thread_local uint64_t g_sequence = 0;
thread_local Setup g_setup;
std::mutex g_output_lock;
std::atomic<unsigned> g_pairs{0};

bool Enabled() {
    static const bool enabled = std::getenv("XBE_SKIN_PALETTE_TRACE") != nullptr;
    return enabled && !diag::CaptureDir().empty() && g_pairs.load(std::memory_order_relaxed) < kPairs;
}
bool Span(const uint8_t* base, uint64_t address, size_t bytes) {
    if (!base || !address || !bytes || bytes > 16384 || address + bytes > (uint64_t(1) << 32)) return false;
    for (uint64_t p = address & ~(uint64_t(mem::kPage) - 1); p < address + bytes; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
bool Copy(const uint8_t* base, uint64_t address, void* destination, size_t bytes) {
    if (!Span(base, address, bytes)) return false;
    std::memcpy(destination, base + address, bytes); return true;
}
uint32_t Read(const uint8_t* base, uint64_t address) {
    uint32_t value = kMissing;
    Copy(base, address, &value, sizeof(value)); return value;
}
uint32_t Field(const uint8_t* base, uint32_t address, uint32_t offset) {
    return address && address != kMissing ? Read(base, uint64_t(address) + offset) : kMissing;
}
Matrix ReadMatrix(const uint8_t* base, uint64_t address) {
    Matrix result;
    result.readable = Copy(base, address, result.words.data(), sizeof(result.words)); return result;
}
Frame ReadFrame(const uint8_t* base, uint32_t address) {
    Frame result; result.address = address;
    if (!address || address == kMissing) return result;
    result.root = Field(base, address, 0xA0);
    if (result.root && result.root != kMissing && Span(base, uint64_t(result.root) + 3, 1))
        result.root_flags = base[uint64_t(result.root) + 3];
    // Native 10D1E0 returns frame+50, synchronizing root when its byte+3 bit0 is set.
    result.local = ReadMatrix(base, uint64_t(address) + 0x10);
    result.world = ReadMatrix(base, uint64_t(address) + 0x50);
    return result;
}
Pose Capture(const uint8_t* base, uint32_t atomic, uint32_t skin) {
    Pose result;
    const auto offset = Read(base, 0x4BA834);
    if (!atomic || !skin || offset == kMissing || offset > 0x1000) return result;
    result.hierarchy = Field(base, atomic, offset);
    result.atomic_frame = ReadFrame(base, Field(base, atomic, 4));
    result.flags = Field(base, result.hierarchy, 0);
    result.poses = Field(base, result.hierarchy, 8);
    result.nodes = Field(base, result.hierarchy, 0x10);
    result.inverse = Field(base, skin, 0xC);
    result.count = Field(base, skin, 0x81C);
    const auto globals = Read(base, 0x4ADAA0);
    if (globals != kMissing) result.inverse_mask = Read(base, uint64_t(globals) + 0x4DF1A4);
    if (!result.hierarchy || result.hierarchy == kMissing || result.flags == kMissing ||
        result.count == 0 || result.count > kBones) return result;
    for (size_t i = 0; i < result.count; ++i) {
        auto& bone = result.bones[i];
        bone.index = Read(base, uint64_t(skin) + 0x1C + i * 4);
        if (bone.index >= 256) return result;
        if (result.inverse && result.inverse != kMissing)
            bone.inverse = ReadMatrix(base, uint64_t(result.inverse) + uint64_t(bone.index) * 64);
        if (result.poses && result.poses != kMissing)
            bone.pose = ReadMatrix(base, uint64_t(result.poses) + uint64_t(bone.index) * 64);
        if (result.nodes && result.nodes != kMissing)
            bone.frame = ReadFrame(base, Read(base, uint64_t(result.nodes) + uint64_t(bone.index) * 16 + 12));
    }
    result.valid = true; return result;
}
template<size_t N> void Words(std::ostream& out, const std::array<uint32_t, N>& words, size_t count = N) {
    out << '[';
    for (size_t i = 0; i < count; ++i) { if (i) out << ','; out << words[i]; }
    out << ']';
}
void Json(std::ostream& out, const Matrix& matrix) {
    if (!matrix.readable) out << "null"; else Words(out, matrix.words);
}
void Json(std::ostream& out, const Frame& frame) {
    out << "{\"address\":" << frame.address << ",\"root\":" << frame.root
        << ",\"root_flags\":" << frame.root_flags << ",\"local\":";
    Json(out, frame.local); out << ",\"world\":"; Json(out, frame.world); out << '}';
}
void Json(std::ostream& out, const Pose& pose) {
    out << "{\"valid\":" << unsigned(pose.valid) << ",\"hierarchy\":" << pose.hierarchy
        << ",\"flags\":" << pose.flags << ",\"poses\":" << pose.poses << ",\"nodes\":" << pose.nodes
        << ",\"inverse\":" << pose.inverse << ",\"count\":" << pose.count
        << ",\"inverse_mask\":" << pose.inverse_mask << ",\"atomic_frame\":";
    Json(out, pose.atomic_frame); out << ",\"bones\":[";
    for (size_t i = 0; pose.valid && i < pose.count; ++i) {
        if (i) out << ',';
        const auto& bone = pose.bones[i];
        out << "{\"index\":" << bone.index << ",\"inverse\":"; Json(out, bone.inverse);
        out << ",\"pose\":"; Json(out, bone.pose); out << ",\"frame\":"; Json(out, bone.frame); out << '}';
    }
    out << "]}";
}
void Json(std::ostream& out, const Record& record) {
    out << "{\"sequence\":" << record.sequence << ",\"milliseconds\":" << record.milliseconds
        << ",\"caller\":" << record.caller << ",\"thread\":" << record.thread
        << ",\"atomic\":" << record.atomic << ",\"skin\":" << record.skin << ",\"output\":" << record.output
        << ",\"fcw\":" << record.fcw << ",\"mxcsr\":" << record.mxcsr
        << ",\"simulation_clock_bits\":" << record.simulation_clock_bits << ",\"projection\":";
    Words(out, record.projection);
    out << ",\"setup\":{\"atomic\":" << record.setup.atomic << ",\"caller\":" << record.setup.caller
        << ",\"sequence\":" << record.setup.sequence << ",\"before\":";
    Json(out, record.setup.before); out << ",\"after\":"; Json(out, record.setup.after); out << '}';
    out << ",\"before\":"; Json(out, record.before); out << ",\"after\":"; Json(out, record.after);
    out << ",\"palette\":"; Words(out, record.palette, record.before.count * 12); out << '}';
}
void Observe(Record&& current) {
    if (!current.before.valid || !current.after.valid || !current.output_readable || !current.projection_readable ||
        current.before.hierarchy != current.after.hierarchy || current.before.count != current.after.count) return;
    Actor* actor = nullptr;
    for (auto& candidate : g_actors)
        if (candidate.record.atomic == current.atomic && candidate.record.skin == current.skin) { actor = &candidate; break; }
    if (!actor) { actor = &g_actors[g_next_actor++ % kActors]; *actor = {}; }
    const auto& previous = actor->record;
    // This is a candidate repeated pass, not a claimed synchronized GPU frame.
    // Both raw observations remain in the receipt so animation/identity changes
    // are distinguishable from repeated-transform rounding or frame synchronization.
    if (actor->emitted < 2 && previous.output && previous.output != current.output &&
        previous.before.hierarchy == current.before.hierarchy && previous.before.count == current.before.count &&
        current.milliseconds - previous.milliseconds < 100 && previous.projection == current.projection &&
        current.simulation_clock_bits != kMissing && previous.simulation_clock_bits == current.simulation_clock_bits &&
        std::memcmp(previous.palette.data(), current.palette.data(), current.before.count * 48)) {
        std::lock_guard lock(g_output_lock);
        if (g_pairs.load(std::memory_order_relaxed) < kPairs) {
            const auto pair = g_pairs.fetch_add(1, std::memory_order_relaxed) + 1;
            ++actor->emitted;
            try {
                std::error_code ec;
                std::filesystem::create_directories(diag::CaptureDir(), ec);
                std::ofstream out(diag::CaptureDir() / "skin-palette.jsonl", std::ios::app);
                if (out) {
                    out << "{\"schema\":1,\"candidate_pair\":" << pair << ",\"before\":"; Json(out, previous);
                    out << ",\"after\":"; Json(out, current); out << "}\n";
                    out.flush();
                    LOGW("Skin palette trace pair=%u atomic=%08X skin=%08X constants=%08X/%08X written=%u",
                         pair, current.atomic, current.skin, previous.output, current.output, unsigned(bool(out)));
                } else LOGW("Skin palette trace pair=%u could not open skin-palette.jsonl", pair);
            } catch (...) {
                LOGW("Skin palette trace pair=%u could not write diagnostic file", pair);
            }
        }
    }
    actor->record = std::move(current);
}
}  // namespace

extern "C" void sub_00260510(X86Context& ctx, uint8_t* base) {
    if (!Enabled()) { __imp__sub_00260510(ctx, base); return; }
    Setup setup;
    setup.atomic = Read(base, uint64_t(ctx.esp) + 16); setup.caller = Read(base, ctx.esp);
    setup.sequence = ++g_sequence;
    setup.before = ReadFrame(base, Field(base, setup.atomic, 4));
    __imp__sub_00260510(ctx, base);
    setup.after = ReadFrame(base, Field(base, setup.atomic, 4));
    g_setup = setup;
}
extern "C" void sub_00260D40(X86Context& ctx, uint8_t* base) {
    if (!Enabled()) { __imp__sub_00260D40(ctx, base); return; }
    Record record;
    record.sequence = ++g_sequence;
    record.milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
    record.caller = Read(base, ctx.esp); record.thread = ctx.thread_handle;
    record.output = Read(base, uint64_t(ctx.esp) + 4); record.atomic = Read(base, uint64_t(ctx.esp) + 8);
    record.skin = Read(base, uint64_t(ctx.esp) + 12); record.fcw = ctx.fcw; record.mxcsr = ctx.mxcsr;
    // A simulation clock observation, deliberately not labelled a render frame ID.
    record.simulation_clock_bits = Read(base, 0x4B7AE4);
    if (g_setup.atomic == record.atomic && g_setup.sequence + 1 == record.sequence) record.setup = g_setup;
    record.before = Capture(base, record.atomic, record.skin);
    record.projection_readable = Copy(base, 0x4BA870, record.projection.data(), sizeof(record.projection));
    __imp__sub_00260D40(ctx, base);
    record.after = Capture(base, record.atomic, record.skin);
    if (record.before.valid) record.output_readable = Copy(base, record.output, record.palette.data(), record.before.count * 48);
    Observe(std::move(record));
}
#endif
