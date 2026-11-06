#include "third_person_body.h"
#include "graphics_camera.h"
#include "cpu/x86_ops.h"
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
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    if (!Span(base, actor, 0x68)) return 0;
    uint16_t count;
    std::memcpy(&count, base + actor + 0x60, sizeof(count));
    const uint32_t list = Read(base, actor + 0x64);
    if (!count || count > 128 || !Span(base, list, count * 8)) return 0;
    uint32_t result = 0;
    for (unsigned i = 0; i < count; ++i) {
        const uint32_t component = Read(base, list + i * 8 + 4);
        if (!Span(base, component, 0x10) || Read(base, component) != wanted ||
            Read(base, component + 0xC) != actor) continue;
        if (result) return 0;
        result = component;
    }
    return result;
}
}

void DarkwatchThirdPersonBodyAim(const X86Context& ctx, uint8_t* base, uint32_t actor) {
    const uint32_t control = Component(base, actor, 0x41F878);
    const uint32_t animation = Component(base, actor, 0x41D258);
    if (!control || !animation || !Span(base, control, 0x2C4) ||
        !Span(base, animation, 0xA0) || ctx.esp < 2048 ||
        !Span(base, ctx.esp - 2048, 2048)) return;
    const uint32_t driver = control + 0x1E8;
    const uint32_t mode = Read(base, driver + 0x6C);
    const uint32_t controller = Read(base, animation + 0x60);
    if ((mode != 1 && mode != 2) || Read(base, driver + 0xD8) != animation ||
        !(Read(base, animation + 0x84) & 8) || !Span(base, controller, 0x128) ||
        Read(base, controller + 0x88) != actor) return;
    std::array<float, 3> origin{}, original{}, facing{}, target{}, direction{};
    std::memcpy(origin.data(), base + control + 0x1A8, sizeof(origin));
    std::memcpy(original.data(), base + control + 0x170, sizeof(original));
    std::memcpy(facing.data(), base + driver + 0x18, sizeof(facing));
    float original_length = 0, facing_length = 0;
    for (unsigned i = 0; i < 3; ++i) {
        if (!std::isfinite(origin[i]) || !std::isfinite(original[i]) || !std::isfinite(facing[i])) return;
        original_length += original[i] * original[i];
        facing_length += facing[i] * facing[i];
    }
    if (!std::isfinite(original_length) || std::abs(original_length - 1.f) > .02f ||
        !std::isfinite(facing_length) || std::abs(facing_length - 1.f) > .02f ||
        !DarkwatchThirdPersonAimTarget(ctx, base, actor, 0, target)) return;
    float length = 0, along = 0;
    for (unsigned i = 0; i < 3; ++i) {
        direction[i] = target[i] - origin[i];
        if (!std::isfinite(direction[i])) return;
        length += direction[i] * direction[i];
        along += direction[i] * original[i];
    }
    if (!std::isfinite(length) || !std::isfinite(along) || length < .0001f || along <= .01f) return;
    const float scale = 1.f / std::sqrt(length);
    for (float& value : direction) value *= scale;

    // Run after the current camera update. Native AIMING poses move the arms;
    // neither the control ray nor the body's facing/locomotion is changed.
    std::array<uint8_t, 2048> saved;
    const uint32_t scratch = ctx.esp - uint32_t(saved.size());
    std::memcpy(saved.data(), base + scratch, saved.size());
    struct Restore {
        uint8_t* where; const std::array<uint8_t, 2048>& saved;
        ~Restore() { std::memcpy(where, saved.data(), saved.size()); }
    } restore{base + scratch, saved};
    X86Context call = ctx;
    call.esp -= 64;
    call.ecx = driver;
    const uint32_t vector = call.esp + 16;
    const uint32_t args[]{0x21606D, driver + 0x18, vector, 1};
    std::memcpy(base + call.esp, args, sizeof(args));
    std::memcpy(base + vector, direction.data(), sizeof(direction));
    x86_icall(call, base, 0x6AF7B);
    // Evaluate those weights now, including held-weapon attachments. 21CDC3
    // does not advance the animation clock or replay reload/melee events.
    call = ctx;
    call.esp -= 64;
    call.ecx = controller;
    std::memcpy(base + call.esp, args, sizeof(uint32_t));
    x86_icall(call, base, 0x21CDC3);
}
