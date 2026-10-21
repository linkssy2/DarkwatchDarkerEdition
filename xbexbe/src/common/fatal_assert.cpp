#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <cstring>
#include "cpu/x86_context.h"
#include "core/log.h"

void DarkwatchFatalAssert(X86Context& ctx, uint8_t* base) {
    // Original CRT INT3: report its completed assertion text; the trap still runs.
    if (!base || ctx.eax != 5 || ctx.ebp < 0x238 || ctx.esp != ctx.ebp - 0x238 ||
        ctx.ecx != ctx.ebp - 0x10) return;
    auto read = [&](uint64_t address, void* out, SIZE_T size) {
        SIZE_T copied = 0;
        return address && address + size <= (uint64_t(1) << 32) &&
            ReadProcessMemory(GetCurrentProcess(), base + address, out, size, &copied) && copied == size;
    };
    uint32_t frame[4]{}; // caller, expression, file, line; beyond the CRT's local buffer.
    if (read(uint64_t(ctx.ebp) + 4, frame, sizeof(frame)))
        LOGE("  assertion caller %08X line %u", frame[0], frame[3]);
    struct { uint16_t length, capacity; uint32_t text; } message{};
    char text[0x21C]{};
    if (!read(ctx.ecx, &message, sizeof(message)) || message.text != ctx.ebp - 0x22C ||
        message.length < 17 || message.length >= sizeof(text) || message.capacity != message.length + 1 ||
        !read(message.text, text, SIZE_T(message.length) + 1) || text[message.length] ||
        std::memcmp(text, "Assertion failed!", 17)) return;
    for (unsigned i = 0; i < message.length; ++i) {
        const auto c = static_cast<unsigned char>(text[i]);
        if (c < 32 || c > 126) text[i] = c == '\n' || c == '\r' ? ' ' : '?';
    }
    LOGE("  guest assertion: %s", text);
}
