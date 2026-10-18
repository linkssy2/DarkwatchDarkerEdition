#pragma once
#include <cstdint>
#include <cstring>
#include <span>

namespace darkwatch::hd {
struct Asset {
    const char* name;
    uint32_t offset, bytes, width, height, format, payload_bytes, palette_bytes;
    bool always;
    uint64_t native_hash, payload_hash, palette_hash;
};
struct PackHeader {
    char magic[8];
    uint32_t version, count;
    uint64_t bytes;
};
struct PackEntry {
    uint64_t native_offset, pixels_offset, pixels_hash;
};
static_assert(sizeof(PackHeader) == 24 && sizeof(PackEntry) == 24);
inline uint64_t Hash(std::span<const uint8_t> bytes) {
    uint64_t value = 14695981039346656037ull;
    for (uint8_t b : bytes) value = (value ^ b) * 1099511628211ull;
    return value;
}
inline bool Range(uint64_t offset, uint64_t bytes, uint64_t size) {
    return offset <= size && bytes <= size - offset;
}
inline uint64_t PixelBytes(const Asset& asset) {
    return uint64_t(asset.width) * asset.height * 16 * 4;
}
// The file contains only the pinned still/UI resources, never movie frames.
inline bool ValidatePack(std::span<const uint8_t> data, std::span<const Asset> assets) {
    PackHeader header{};
    if (data.size() < sizeof(header)) return false;
    std::memcpy(&header, data.data(), sizeof(header));
    if (std::memcmp(header.magic, "DWHDU002", 8) || header.version != 2 ||
        header.count != assets.size() || header.bytes != data.size() || header.bytes > (1ull << 30)) return false;
    uint64_t next = sizeof(header) + assets.size() * sizeof(PackEntry);
    if (next > data.size()) return false;
    for (size_t i = 0; i < assets.size(); ++i) {
        const auto& a = assets[i];
        PackEntry entry{};
        std::memcpy(&entry, data.data() + sizeof(header) + i * sizeof(entry), sizeof(entry));
        if (entry.native_offset != next || !Range(next, a.bytes, data.size()) ||
            Hash(data.subspan(size_t(next), a.bytes)) != a.native_hash) return false;
        next += a.bytes;
        // No approved restored artwork: retain the exact original at runtime.
        if (!entry.pixels_offset && !entry.pixels_hash) continue;
        if (entry.pixels_offset != next || !Range(next, PixelBytes(a), data.size()) || !entry.pixels_hash) return false;
        next += PixelBytes(a);
    }
    return next == data.size();
}
} // namespace darkwatch::hd
