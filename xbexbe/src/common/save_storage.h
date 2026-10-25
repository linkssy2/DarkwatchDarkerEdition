#pragma once

#include <cstdint>
#include <cstddef>
#include <filesystem>
#include <span>
#include <vector>

namespace darkwatch::saves {

inline constexpr size_t kMaxPayloadBytes = 0x40000;
inline constexpr size_t kSignatureBytes = 20;
inline constexpr size_t kMaxFileBytes = kMaxPayloadBytes + kSignatureBytes;

// One or two native FORP5 profiles, followed by the runtime's shared HMAC.
bool Valid(std::span<const uint8_t> data);
// A missing main file is never restored, so deleting a save stays intentional.
bool Read(const std::filesystem::path& path, std::vector<uint8_t>& data, bool* recovered = nullptr);
bool Write(const std::filesystem::path& path, std::span<const uint8_t> data);

} // namespace darkwatch::saves
