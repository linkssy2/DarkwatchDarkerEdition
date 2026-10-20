#include "common/coop_stream.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <thread>
#include <utility>
#include <vector>
#include "common/coop.h"
#include "common/coop_video.h"
#include "common/coop_view.h"
#include "app/app.h"
#include "core/log.h"
#include "gpu/ext.h"
#include "kernel/memory.h"

using Microsoft::WRL::ComPtr;

namespace darkwatch::coop::stream {
namespace {

constexpr uint32_t kFps = 60;
// Readback slots: one being written by the GPU, one waiting, one being read, and a spare.
constexpr uint32_t kRing = 4;
constexpr DXGI_FORMAT kBgra = DXGI_FORMAT_B8G8R8A8_UNORM;

// Render thread only, except `busy`, which the encoder clears once it has read a slot.
struct Gpu {
    ComPtr<ID3D12Resource> texture;
    D3D12_RESOURCE_STATES texture_state = D3D12_RESOURCE_STATE_COPY_SOURCE;
    ComPtr<ID3D12DescriptorHeap> rtv;
    ComPtr<ID3D12Resource> readback[kRing];
    uint32_t width = 0, height = 0, pitch = 0;
    uint32_t generation = 0;  // which set of readback buffers a job's slot refers to
};
Gpu g_gpu;
std::atomic<bool> g_busy[kRing];
std::atomic<uint32_t> g_generation{0};

// A recorded copy for the encoder: it waits for the queue fence to reach `value`, then reads
// the readback buffer. Only the newest job waits; a replaced one frees its slot.
struct Job {
    ComPtr<ID3D12Resource> readback;
    ComPtr<ID3D12Fence> fence;
    uint64_t value = 0;
    uint32_t slot = 0, generation = 0, width = 0, height = 0, pitch = 0;
};
struct Handoff {
    std::mutex lock;
    std::condition_variable ready;
    Job job;
    bool fresh = false;
    uint32_t dropped = 0;  // jobs replaced before the encoder took them
};
Handoff g_handoff;
std::once_flag g_encoder_started;

void Free(const Job& job) {
    if (job.generation == g_generation.load()) g_busy[job.slot] = false;
}

void EncodeLoop() {
    if (!video::Startup()) {LOGE("coop: Media Foundation unavailable; no guest video"); return;}
    std::unique_ptr<video::Encoder> encoder;
    uint32_t width = 0, height = 0;
    std::vector<uint8_t> nv12;
    HANDLE done = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    struct {
        std::chrono::steady_clock::time_point since = std::chrono::steady_clock::now();
        std::chrono::steady_clock::duration busy{};
        uint32_t frames = 0;
        uint64_t bytes = 0;
    } stats;
    for (;;) {
        Job job;
        {
            std::unique_lock lock(g_handoff.lock);
            g_handoff.ready.wait(lock, [] {return g_handoff.fresh;});
            g_handoff.fresh = false;
            job = std::move(g_handoff.job);
        }
        // The copy is ready as soon as the GPU passes this frame, usually within a few ms.
        if (job.fence->GetCompletedValue() < job.value) {
            job.fence->SetEventOnCompletion(job.value, done);
            if (WaitForSingleObject(done, 1000) != WAIT_OBJECT_0) {Free(job); continue;}
        }
        if (width != job.width || height != job.height) {
            width = job.width; height = job.height;
            const uint32_t kbps = Snapshot().video_kbps;
            encoder = video::Encoder::Create(width, height, kFps, kbps * 1000);
            if (!encoder) LOGE("coop: H.264 encoder unavailable for %ux%u", width, height);
            else LOGR("coop: streaming the guest view at %ux%u, %u kbit/s", width, height, kbps);
            TakeKeyRequest();
        }
        const auto started = std::chrono::steady_clock::now();
        void* mapped = nullptr;
        const D3D12_RANGE range{0, size_t(job.pitch) * job.height};
        const bool read = encoder && SUCCEEDED(job.readback->Map(0, &range, &mapped));
        if (read) {
            video::BgraToNv12(static_cast<const uint8_t*>(mapped), job.pitch, width, height, nv12);
            const D3D12_RANGE none{0, 0};
            job.readback->Unmap(0, &none);
        }
        Free(job);
        if (!read) continue;
        const bool key = TakeKeyRequest();
        if (!encoder->Encode(nv12, key, [&](const uint8_t* data, size_t size, bool is_key) {SendVideo(data, size, is_key); stats.bytes += size;}))
            LOG_FIRST(4, "coop: H.264 encode failed");
        const auto now = std::chrono::steady_clock::now();
        stats.busy += now - started;
        ++stats.frames;
        if (now - stats.since >= std::chrono::seconds(10)) {
            // Whether the host keeps up: a busy encoder drops frames instead of falling behind.
            uint32_t dropped = 0;
            {std::lock_guard lock(g_handoff.lock); dropped = std::exchange(g_handoff.dropped, 0);}
            const double seconds = std::chrono::duration<double>(now - stats.since).count();
            LOGR("coop: guest video %.1f fps, %.1f ms per frame, %.0f kbit/s, %u frames dropped",
                 stats.frames / seconds, std::chrono::duration<double, std::milli>(stats.busy).count() / std::max(1u, stats.frames),
                 stats.bytes * 8 / seconds / 1000, dropped);
            stats = {};
            stats.since = now;
        }
    }
}

bool Ensure(gpu::Context& c, uint32_t width, uint32_t height) {
    if (g_gpu.texture && g_gpu.width == width && g_gpu.height == height) return true;
    Gpu fresh;
    ID3D12Device* device = c.Device();
    D3D12_HEAP_PROPERTIES heap{D3D12_HEAP_TYPE_DEFAULT};
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width; desc.Height = height; desc.DepthOrArraySize = 1; desc.MipLevels = 1;
    desc.Format = kBgra; desc.SampleDesc.Count = 1;
    desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, fresh.texture_state, nullptr,
                                               IID_PPV_ARGS(&fresh.texture)))) return false;
    D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 1};
    if (FAILED(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&fresh.rtv)))) return false;
    device->CreateRenderTargetView(fresh.texture.Get(), nullptr, fresh.rtv->GetCPUDescriptorHandleForHeapStart());
    fresh.pitch = (width * 4 + D3D12_TEXTURE_DATA_PITCH_ALIGNMENT - 1) & ~(D3D12_TEXTURE_DATA_PITCH_ALIGNMENT - 1);
    D3D12_HEAP_PROPERTIES read_heap{D3D12_HEAP_TYPE_READBACK};
    D3D12_RESOURCE_DESC buffer{};
    buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    buffer.Width = uint64_t(fresh.pitch) * height; buffer.Height = 1; buffer.DepthOrArraySize = 1; buffer.MipLevels = 1;
    buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    for (auto& r : fresh.readback)
        if (FAILED(device->CreateCommittedResource(&read_heap, D3D12_HEAP_FLAG_NONE, &buffer, D3D12_RESOURCE_STATE_COPY_DEST,
                                                   nullptr, IID_PPV_ARGS(&r)))) return false;
    fresh.width = width; fresh.height = height;
    // In-flight copies may still read the old resources; the renderer frees them later.
    if (g_gpu.texture) c.Release(g_gpu.texture);
    for (auto& r : g_gpu.readback) if (r) c.Release(r);
    // Jobs on the old buffers keep them alive and no longer free slots of the new ones.
    fresh.generation = g_generation.load() + 1;
    for (auto& busy : g_busy) busy = false;
    g_generation = fresh.generation;
    g_gpu = std::move(fresh);
    return true;
}

} // namespace

void Presenting(gpu::Context& c, gpu::Target* front) {
    const uint64_t present = c.Presents();
    if (!GuestActive()) return;
    const uint32_t pixels = GuestFramePixels();
    // The guest sees the host's presented frame whenever its own view is not the picture:
    // menus and loading before a level, the in-game Pause menu, and in-level cinematics or
    // movies, which draw only the main view and leave the guest's camera idle.
    static uint64_t draws = 0, drawn_at = 0;
    static bool was_host = false;
    if (const uint64_t seen = GuestCameraDraws(); seen != draws) {draws = seen; drawn_at = present;}
    const bool idle = !pixels || Paused() || present - drawn_at > 3;
    if (std::exchange(was_host, idle) != idle)
        LOGR("coop: guest sees %s", idle ? (!pixels ? "the host's frame (no guest view)" : Paused() ? "the host's frame (paused)" :
                                            "the host's frame (guest camera idle)") : "its own view");
    gpu::Target* target = idle ? front : c.ColorTarget(pixels);
    if (!target || !target->w || !target->h) {LOG_FIRST(2, "coop: guest target %08X not drawn yet", pixels); return;}
    D3D12_RESOURCE_STATES* state = nullptr;
    DXGI_FORMAT format = kBgra;
    ID3D12Resource* source = c.Readable(*target, state, format);
    if (!source) return;
    // The window shows every view at 16:9 with widescreen, else 4:3; the guest sees the same.
    const uint32_t height = Snapshot().video_height;
    const uint32_t width = app::Widescreen() ? height * 16 / 9 : height * 4 / 3;
    if (!Ensure(c, width, height)) {LOG_FIRST(1, "coop: guest video resources failed"); return;}
    // The camera texture may be larger than the raster the view draws into.
    uint32_t used_w = 0, used_h = 0;
    GuestFrameSize(used_w, used_h);
    const float uv[4]{0, 0, !idle && target->gw && used_w ? std::min(1.0f, float(used_w) / target->gw) : 1.0f,
                      !idle && target->gh && used_h ? std::min(1.0f, float(used_h) / target->gh) : 1.0f};
    static uint64_t logged = 0;
    const uint64_t shape = uint64_t(target->gw) << 48 | uint64_t(target->gh) << 32 | uint64_t(target->w) << 16 | target->h;
    if (!idle && std::exchange(logged, shape) != shape) {
        const uint32_t texture = GuestFrameTexture();
        const uint8_t* base = mem::Base();
        auto word = [&](uint32_t offset) {uint32_t v = 0; if (texture && mem::IsCommitted((texture + offset) & ~(mem::kPage - 1u))) std::memcpy(&v, base + texture + offset, 4); return v;};
        LOGR("coop: guest target %ux%u guest, %ux%u host at %08X, raster %ux%u, encoding %ux%u; D3D %08X: %08X %08X %08X %08X %08X",
             target->gw, target->gh, target->w, target->h, pixels, used_w, used_h, width, height, texture,
             word(0), word(4), word(8), word(12), word(16));
    }
    std::call_once(g_encoder_started, [] {std::thread(EncodeLoop).detach();});
    c.Transition(source, *state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
    c.Transition(g_gpu.texture.Get(), g_gpu.texture_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
    c.BlitTo(g_gpu.rtv->GetCPUDescriptorHandleForHeapStart(), g_gpu.width, g_gpu.height, source, format, uv);
    c.Transition(g_gpu.texture.Get(), g_gpu.texture_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
    uint32_t slot = 0;
    while (slot < kRing && g_busy[slot].load()) ++slot;
    if (slot == kRing) {  // the encoder holds every slot: skip this frame
        std::lock_guard lock(g_handoff.lock);
        ++g_handoff.dropped;
        c.Unbind();
        return;
    }
    D3D12_TEXTURE_COPY_LOCATION dst{};
    dst.pResource = g_gpu.readback[slot].Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint.Footprint = {kBgra, g_gpu.width, g_gpu.height, 1, g_gpu.pitch};
    D3D12_TEXTURE_COPY_LOCATION src{};
    src.pResource = g_gpu.texture.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    c.List()->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    g_busy[slot] = true;
    Job job{g_gpu.readback[slot], c.QueueFence(), c.RecordedFenceValue(), slot, g_gpu.generation,
            g_gpu.width, g_gpu.height, g_gpu.pitch};
    {
        std::lock_guard lock(g_handoff.lock);
        if (g_handoff.fresh) {Free(g_handoff.job); ++g_handoff.dropped;}
        g_handoff.job = std::move(job);
        g_handoff.fresh = true;
    }
    g_handoff.ready.notify_one();
    c.Unbind();
}

} // namespace darkwatch::coop::stream
