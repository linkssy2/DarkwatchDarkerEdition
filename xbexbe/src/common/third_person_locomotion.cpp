#include "graphics_camera.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_0006BE61);

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
bool Facing(const X86Context& ctx, uint8_t* base, std::array<float, 3>& facing) {
    const uint32_t driver = ctx.ecx;
    if (driver < 0x1E8 || !Span(base, driver - 0x1E8, 0x2C4) || !Span(base, ctx.esp, 28)) return false;
    const uint32_t control = driver - 0x1E8;
    const uint32_t actor = Read(base, control + 0xC);
    const uint32_t animation = Read(base, driver + 0xD8);
    const uint32_t mode = Read(base, driver + 0x6C);
    // This helper is shared by non-player animation drivers. Admit only the
    // live personal camera and its own ChazControl/AnimationComponent pair.
    if (Read(base, control) != 0x41F878 || (mode != 1 && mode != 2) ||
        !Span(base, animation, 0x88) || Read(base, animation) != 0x41D258 ||
        Read(base, animation + 0xC) != actor || !(Read(base, animation + 0x84) & 8) ||
        Read(base, ctx.esp + 8) != control + 0x170 ||
        !DarkwatchThirdPersonPlayer(ctx, base, actor, control)) return false;
    float dt;
    std::array<float, 3> aim;
    std::memcpy(&dt, base + ctx.esp + 4, sizeof(dt));
    std::memcpy(aim.data(), base + control + 0x170, sizeof(aim));
    std::memcpy(facing.data(), base + driver + 0x18, sizeof(facing));
    if (!std::isfinite(dt) || dt <= 0 || dt > .25f) return false;
    for (unsigned i = 0; i < 3; ++i)
        if (!std::isfinite(aim[i]) || !std::isfinite(facing[i])) return false;
    const float aim_length = std::hypot(aim[0], aim[2]);
    const float body_length = std::hypot(facing[0], facing[2]);
    if (aim_length < .01f || body_length < .9f || body_length > 1.1f) return false;
    const float current = std::atan2(facing[0], facing[2]);
    const float target = std::atan2(aim[0], aim[2]);
    const float delta = std::remainder(target - current, 6.28318530718f);
    // Keep a short, continuous turn, independent of render frequency. Native
    // aim poses supply the remaining torso turn while the feet catch up.
    const float yaw = current + delta * -std::expm1(-dt / .06f);
    facing = {std::sin(yaw), 0.f, std::cos(yaw)};
    return true;
}
}

X86_FUNC(sub_0006BE61) {
    std::array<float, 3> facing;
    if (!Facing(ctx, base, facing)) { __imp__sub_0006BE61(ctx, base); return; }
    const uint32_t driver = ctx.ecx;
    const uint8_t turning = base[driver + 0x68];
    // 6BE61 normally turns toward movement, retaining a half-turn target and
    // dead zone. That can strand the third-person arms outside the native
    // +/-90-degree aim range. Keep its gait selection, phase matching and
    // gameplay inputs intact; replace only this visual facing decision.
    base[driver + 0x68] = 0;
    __imp__sub_0006BE61(ctx, base);
    base[driver + 0x68] = turning;
    std::memcpy(base + driver + 0x18, facing.data(), sizeof(facing));
    std::memcpy(base + driver + 0x24, facing.data(), sizeof(facing));
    base[driver + 0x64] = 0;
    // The original caller consumes EAX == driver+18 to update the actor's
    // orientation. No player velocity, position, aim ray or event is replaced.
}
