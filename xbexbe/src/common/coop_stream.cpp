#include "common/coop_stream.h"
#include <algorithm>
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

constexpr uint32_t kHeight = 720, kFps = 60, kBitrate = 8'000'000;
// The renderer keeps three frames in flight and waits for the oldest before reusing its
// slot, so a copy recorded at present N has finished by present N + 3.
constexpr uint32_t kRing = 4, kLag = 3;
constexpr DXGI_FORMAT kBgra = DXGI_FORMAT_B8G8R8A8_UNORM;

// Render thread only.
struct Gpu {
    ComPtr<ID3D12Resource> texture;
    D3D12_RESOURCE_STATES texture_state = D3D12_RESOURCE_STATE_COPY_SOURCE;
    ComPtr<ID3D12DescriptorHeap> rtv;
    ComPtr<ID3D12Resource> readback[kRing];
    uint64_t written[kRing]{};  // present number + 1 of the copy each slot holds
    uint32_t width = 0, height = 0, pitch = 0;
};
Gpu g_gpu;

// Latest finished frame for the encoder; an unread frame is replaced, never queued.
struct Handoff {
    std::mutex lock;
    std::condition_variable ready;
    std::vector<uint8_t> bgra;
    uint32_t width = 0, height = 0, pitch = 0;
    bool fresh = false;
};
Handoff g_handoff;
std::once_flag g_encoder_started;

void EncodeLoop() {
    if (!video::Startup()) {LOGE("coop: Media Foundation unavailable; no guest video"); return;}
    std::unique_ptr<video::Encoder> encoder;
    uint32_t width = 0, height = 0;
    std::vector<uint8_t> bgra, nv12;
    uint32_t pitch = 0;
    for (;;) {
        {
            std::unique_lock lock(g_handoff.lock);
            g_handoff.ready.wait(lock, [] {return g_handoff.fresh;});
            g_handoff.fresh = false;
            bgra.swap(g_handoff.bgra);
            pitch = g_handoff.pitch;
            if (width != g_handoff.width || height != g_handoff.height) {
                width = g_handoff.width; height = g_handoff.height;
                encoder = video::Encoder::Create(width, height, kFps, kBitrate);
                if (!encoder) LOGE("coop: H.264 encoder unavailable for %ux%u", width, height);
                else LOGR("coop: streaming the guest view at %ux%u", width, height);
                TakeKeyRequest();
            }
        }
        if (!encoder) continue;
        video::BgraToNv12(bgra.data(), pitch, width, height, nv12);
        const bool key = TakeKeyRequest();
        if (!encoder->Encode(nv12, key, [](const uint8_t* data, size_t size, bool is_key) {SendVideo(data, size, is_key);}))
            LOG_FIRST(4, "coop: H.264 encode failed");
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
    g_gpu = std::move(fresh);
    return true;
}

// Hands the copy recorded kLag presents ago to the encoder.
void Deliver(uint64_t present) {
    if (present < kLag) return;
    const uint32_t slot = uint32_t((present - kLag) % kRing);
    if (g_gpu.written[slot] != present - kLag + 1) return;
    g_gpu.written[slot] = 0;
    void* mapped = nullptr;
    const D3D12_RANGE range{0, size_t(g_gpu.pitch) * g_gpu.height};
    if (FAILED(g_gpu.readback[slot]->Map(0, &range, &mapped))) return;
    {
        std::lock_guard lock(g_handoff.lock);
        g_handoff.bgra.assign(static_cast<const uint8_t*>(mapped), static_cast<const uint8_t*>(mapped) + range.End);
        g_handoff.width = g_gpu.width; g_handoff.height = g_gpu.height; g_handoff.pitch = g_gpu.pitch;
        g_handoff.fresh = true;
    }
    const D3D12_RANGE none{0, 0};
    g_gpu.readback[slot]->Unmap(0, &none);
    g_handoff.ready.notify_one();
}

} // namespace

void Presenting(gpu::Context& c) {
    const uint64_t present = c.Presents();
    Deliver(present);
    const uint32_t pixels = GuestFramePixels();
    if (!pixels || !GuestActive()) return;
    gpu::Target* target = c.ColorTarget(pixels);
    if (!target || !target->w || !target->h) {LOG_FIRST(2, "coop: guest target %08X not drawn yet", pixels); return;}
    D3D12_RESOURCE_STATES* state = nullptr;
    DXGI_FORMAT format = kBgra;
    ID3D12Resource* source = c.Readable(*target, state, format);
    if (!source) return;
    // The window shows every view at 16:9 with widescreen, else 4:3; the guest sees the same.
    const uint32_t width = app::Widescreen() ? kHeight * 16 / 9 : kHeight * 4 / 3;
    if (!Ensure(c, width, kHeight)) {LOG_FIRST(1, "coop: guest video resources failed"); return;}
    // The camera texture may be larger than the raster the view draws into.
    uint32_t used_w = 0, used_h = 0;
    GuestFrameSize(used_w, used_h);
    const float uv[4]{0, 0, target->gw && used_w ? std::min(1.0f, float(used_w) / target->gw) : 1.0f,
                      target->gh && used_h ? std::min(1.0f, float(used_h) / target->gh) : 1.0f};
    static uint64_t logged = 0;
    const uint64_t shape = uint64_t(target->gw) << 48 | uint64_t(target->gh) << 32 | uint64_t(target->w) << 16 | target->h;
    if (std::exchange(logged, shape) != shape) {
        const uint32_t texture = GuestFrameTexture();
        const uint8_t* base = mem::Base();
        auto word = [&](uint32_t offset) {uint32_t v = 0; if (texture && mem::IsCommitted((texture + offset) & ~(mem::kPage - 1u))) std::memcpy(&v, base + texture + offset, 4); return v;};
        LOGR("coop: guest target %ux%u guest, %ux%u host at %08X, raster %ux%u, encoding %ux%u; D3D %08X: %08X %08X %08X %08X %08X",
             target->gw, target->gh, target->w, target->h, pixels, used_w, used_h, width, kHeight, texture,
             word(0), word(4), word(8), word(12), word(16));
    }
    std::call_once(g_encoder_started, [] {std::thread(EncodeLoop).detach();});
    c.Transition(source, *state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
    c.Transition(g_gpu.texture.Get(), g_gpu.texture_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
    c.BlitTo(g_gpu.rtv->GetCPUDescriptorHandleForHeapStart(), g_gpu.width, g_gpu.height, source, format, uv);
    c.Transition(g_gpu.texture.Get(), g_gpu.texture_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
    const uint32_t slot = uint32_t(present % kRing);
    D3D12_TEXTURE_COPY_LOCATION dst{};
    dst.pResource = g_gpu.readback[slot].Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint.Footprint = {kBgra, g_gpu.width, g_gpu.height, 1, g_gpu.pitch};
    D3D12_TEXTURE_COPY_LOCATION src{};
    src.pResource = g_gpu.texture.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    c.List()->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    g_gpu.written[slot] = present + 1;
    c.Unbind();
}

} // namespace darkwatch::coop::stream
