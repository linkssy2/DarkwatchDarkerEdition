#include "third_person_aim.h"
#include "graphics_camera.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>

namespace {
bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || !size || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t address) {
    uint32_t value;
    std::memcpy(&value, base + address, sizeof(value));
    return value;
}
}

void DarkwatchThirdPersonShotAim(X86Context& ctx, uint8_t* base) {
    // 1DCF5 aligns its stack, reserves 354 bytes and saves three registers.
    // At 1DD2F, its stack-local 1B0 response is complete. Do not change a global
    // control vector: the other viewport, targeting and authored cameras own it.
    if (ctx.ebp < 0x360 || ctx.esp != (ctx.ebp & ~15u) - 0x360 ||
        !Span(base, ctx.esp, 0x90) || !Span(base, uint64_t(ctx.ebx) + 0x58, 4) ||
        Read(base, ctx.esp + 0x58) != 0x41E948 || Read(base, ctx.esp + 0x5C) != 0x1B0 ||
        Read(base, ctx.esp + 0x78) != 1) return;
    const uint32_t actor = Read(base, ctx.ebx + 0x58);
    if (!actor || Read(base, ctx.esp + 0x38) != actor) return;
    std::array<float, 3> origin{}, direction{}, target{};
    std::memcpy(origin.data(), base + ctx.esp + 0x60, sizeof(origin));
    std::memcpy(direction.data(), base + ctx.esp + 0x6C, sizeof(direction));
    float original_length = 0;
    for (unsigned i = 0; i < 3; ++i) {
        if (!std::isfinite(origin[i]) || !std::isfinite(direction[i])) return;
        original_length += direction[i] * direction[i];
    }
    uint32_t target_actor = 0;
    if (!std::isfinite(original_length) || std::abs(original_length - 1.f) > .02f ||
        !DarkwatchThirdPersonAimTarget(ctx, base, actor, ctx.ebx, target, &target_actor)) return;
    std::array<float, 3> delta{};
    float length_squared = 0, along = 0;
    for (unsigned i = 0; i < 3; ++i) {
        delta[i] = target[i] - origin[i];
        if (!std::isfinite(delta[i])) return;
        length_squared += delta[i] * delta[i];
        along += delta[i] * direction[i];
    }
    if (!std::isfinite(length_squared) || !std::isfinite(along) ||
        length_squared < .0001f || along <= .01f) return;
    const float inverse_length = 1.f / std::sqrt(length_squared);
    for (float& value : delta) value *= inverse_length;
    std::memcpy(base + ctx.esp + 0x6C, delta.data(), sizeof(delta));
    // Keep the native eye origin and all collision/muzzle-convergence work.
    // Retain native assistance only for the same unobstructed target. An old
    // control-ray selection must not redirect this shot to another actor.
    if (!target_actor || target_actor != Read(base, ctx.esp + 0x8C)) {
        const uint32_t no_assist[2]{};
        std::memcpy(base + ctx.esp + 0x88, no_assist, sizeof(no_assist));
    }
}
