#pragma once
// Network co-op video: H.264 through Media Foundation's Microsoft encoder and decoder,
// low-latency, no B-frames, Annex B byte stream. Shared by the host and the guest client.
// Each Encoder/Decoder belongs to one thread, which must have called Startup().
#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

namespace darkwatch::coop::video {

bool Startup();   // COM (multithreaded) and Media Foundation for the calling thread
void Shutdown();

// BT.601 limited range. Width and height are even; bgra rows are `pitch` bytes apart.
void BgraToNv12(const uint8_t* bgra, uint32_t pitch, uint32_t width, uint32_t height, std::vector<uint8_t>& nv12);
// nv12 holds `rows` luma rows of `stride` bytes, then the interleaved chroma rows.
void Nv12ToBgra(const uint8_t* nv12, uint32_t stride, uint32_t rows, uint32_t width, uint32_t height,
                std::vector<uint8_t>& bgra);

using EncodedFrame = std::function<void(const uint8_t* data, size_t size, bool key)>;
using DecodedFrame = std::function<void(const uint8_t* bgra, uint32_t width, uint32_t height)>;

class Encoder {
public:
    static std::unique_ptr<Encoder> Create(uint32_t width, uint32_t height, uint32_t fps, uint32_t bitrate);
    virtual ~Encoder() = default;
    // One NV12 frame of the created size; `out` receives each access unit it completes.
    virtual bool Encode(const std::vector<uint8_t>& nv12, bool force_key, const EncodedFrame& out) = 0;
};

class Decoder {
public:
    static std::unique_ptr<Decoder> Create();
    virtual ~Decoder() = default;
    // One access unit; `out` receives each frame it completes, cropped to the picture.
    virtual bool Decode(const uint8_t* data, size_t size, const DecodedFrame& out) = 0;
};

} // namespace darkwatch::coop::video
