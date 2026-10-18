#pragma once
#include <cstdint>

namespace darkwatch::sound_pool {
inline constexpr uint32_t kCount = 6;
inline constexpr uint32_t kOriginalOffset = 0xB4C;
inline constexpr uint32_t kOffset = 0xC20;
inline constexpr uint32_t kManagerSize = kOffset + kCount * 0x20;
inline constexpr uint32_t kStreamCount = 5 + (kCount - 3);
inline constexpr uint32_t kVoiceCount = 160 + (kCount - 3);
static_assert(57 + kCount <= 64);
static_assert(kVoiceCount - kStreamCount == 155);
}
