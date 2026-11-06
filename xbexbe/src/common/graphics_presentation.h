#pragma once
#include <cstdint>

namespace darkwatch::presentation {
// Only full frontend pages and loading screens use the optional original canvas.
bool OriginalRoot(const uint8_t* base, uint32_t root);
}
