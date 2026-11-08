#include "graphics_camera.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_000A9082);
X86_EXTERN_FUNC(__imp__sub_000A929B);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(T));
    return true;
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t type) {
    uint16_t count = 0;
    uint32_t list = 0, found = 0;
    if (!Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, count * 8)) return 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component = 0, vtable = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, component) || !Read(base, component, vtable)) return 0;
        if (vtable != type) continue;
        if (found || !Read(base, uint64_t(component) + 0xC, owner) || owner != actor) return 0;
        found = component;
    }
    return found;
}
uint32_t DeathActor(const uint8_t* base, uint32_t state) {
    uint32_t vtable = 0, control = 0, actor = 0;
    if (!Read(base, state, vtable) || vtable != 0x422158 ||
        !Read(base, uint64_t(state) + 0x40, control) || !Read(base, control, vtable) || vtable != 0x41F878 ||
        !Read(base, uint64_t(control) + 0xC, actor) ||
        Component(base, actor, 0x41F878) != control || !Component(base, actor, 0x4227A4)) return 0;
    return actor;
}
bool Stack(const X86Context& ctx, const uint8_t* base) {
    return base == kernel::g_base && ctx.esp >= 0x10000 &&
        Span(base, uint64_t(ctx.esp) - 0x10000, 0x10010);
}
bool Ragdoll(const uint8_t* base, uint32_t actor, uint32_t& impl) {
    const auto animation = Component(base, actor, 0x41D258);
    uint32_t wrapper = 0, vtable = 0, owner = 0, skeleton = 0, controller = 0;
    uint8_t flags = 0;
    return animation && Read(base, uint64_t(animation) + 0x84, flags) && (flags & 8) &&
        Read(base, uint64_t(animation) + 0x60, controller) && Span(base, controller, 4) &&
        Read(base, uint64_t(animation) + 0x90, wrapper) && Read(base, wrapper, vtable) && vtable == 0x41D4AC &&
        Read(base, uint64_t(wrapper) + 4, impl) && Span(base, impl, 0x1B0) &&
        Read(base, uint64_t(impl) + 0x12C, owner) && owner == actor &&
        Read(base, impl, skeleton) && Span(base, skeleton, 0x18);
}
void ActivateDeathBody(const X86Context& entry, uint8_t* base, uint32_t actor) {
    uint32_t impl = 0;
    uint8_t active = 0;
    if (!Ragdoll(base, actor, impl) || !Read(base, uint64_t(impl) + 0xC1, active)) return;
    X86Context call = entry;
    if (!active) {
        // Same actor message as RagdollStateCommand::Start (9F53E). This keeps
        // the selected model's own native rig, hit impulse and bone mapping.
        const auto message = (entry.esp - 0x100) & ~15u;
        std::array<uint8_t, 12> saved;
        std::memcpy(saved.data(), base + message, saved.size());
        const uint32_t activate[]{0x41E948, 0x12, 1};
        std::memcpy(base + message, activate, sizeof(activate));
        call.esp = message - 0x20;
        call.ecx = actor;
        kernel::CallGuest(call, 0x216560, {message});
        std::memcpy(base + message, saved.data(), saved.size());
    }
    if (!Ragdoll(base, actor, impl) || !Read(base, uint64_t(impl) + 0xC1, active) || !active) return;
    const auto control = Component(base, actor, 0x41F878);
    uint32_t controller = 0, physics = 0, phantom = 0, world = 0, filter = 0;
    if (!control || !Read(base, uint64_t(control) + 0xF4, controller) || !Read(base, controller, physics) ||
        !Read(base, uint64_t(physics) + 0x9C, phantom) || !Read(base, uint64_t(physics) + 0xA4, world) ||
        !Span(base, world, 4) || !Read(base, uint64_t(phantom) + 0x28, filter) || filter == 2) return;
    // Original Chaz death does this only in competitive multiplayer (9C8BC).
    // The dead on-foot body must not remain inside a live standing capsule.
    call.ecx = controller;
    kernel::CallGuest(call, 0x83695, {2});
}
}

X86_FUNC(sub_000A9082) {
    const auto actor = DeathActor(base, ctx.ecx);
    const auto entry = ctx;
    uint32_t rig = 0;
    const bool external = actor && Stack(ctx, base) && Ragdoll(base, actor, rig) &&
        DarkwatchBeginThirdPersonDeath(ctx, base, actor);
    // Preserve the original timer, death effects, respawn controls and game-over
    // transition. Only an already selected third-person camera adds the body.
    __imp__sub_000A9082(ctx, base);
    if (external) ActivateDeathBody(entry, base, actor);
}

X86_FUNC(sub_000A929B) {
    const auto actor = DeathActor(base, ctx.ecx);
    if (actor && base == kernel::g_base) DarkwatchEndThirdPersonDeath(base, actor);
    __imp__sub_000A929B(ctx, base);
}
