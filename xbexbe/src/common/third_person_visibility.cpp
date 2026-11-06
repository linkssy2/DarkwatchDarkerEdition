#include "graphics_camera.h"
#include "third_person_visibility.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <array>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_000BCBB7);
X86_EXTERN_FUNC(__imp__sub_000BCBE3);
X86_EXTERN_FUNC(__imp__sub_000DEDD0);

namespace {
bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || !size || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Field(const uint8_t* base, uint32_t object, uint32_t offset, T& value) {
    if (!object || !Span(base, uint64_t(object) + offset, sizeof(value))) return false;
    std::memcpy(&value, base + uint64_t(object) + offset, sizeof(value));
    return true;
}
uint32_t OwnedComponent(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    uint32_t list = 0, result = 0;
    uint16_t count = 0;
    if (!Field(base, actor, 0x60, count) || !count || count > 128 ||
        !Field(base, actor, 0x64, list) || !Span(base, list, count * 8)) return 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t component = 0, type = 0, owner = 0;
        if (!Field(base, list, i * 8 + 4, component) ||
            !Field(base, component, 0, type) || type != wanted ||
            !Field(base, component, 0xC, owner) || owner != actor) continue;
        if (result) return 0;
        result = component;
    }
    return result;
}
}

void DarkwatchPrepareThirdPersonHands(const X86Context& ctx, uint8_t* base, uint32_t personal) {
    uint32_t actor = 0;
    if (!Field(base, personal, 0x18C, actor)) return;
    const uint32_t inventory = OwnedComponent(base, actor, 0x41F29C);
    if (!inventory || !Span(base, uint64_t(inventory) + 0x90, 4)) return;

    uint32_t hands = 0, parent_ref = 0, parent = 0, resource = 0, entries = 0, clump = 0, frame = 0;
    uint16_t count = 0;
    if (!Field(base, inventory, 0x54, hands) || !Field(base, hands, 0x78, parent_ref) ||
        !Field(base, parent_ref, 0, parent) || parent != actor) return;
    const uint32_t model = OwnedComponent(base, hands, 0x4228D4);
    const uint32_t animation = OwnedComponent(base, hands, 0x41D258);
    if (!model || !animation || !Span(base, model, 0xC0) || !Span(base, animation, 0xA0) ||
        !Field(base, model, 0x30, resource) || !resource ||
        !Field(base, resource, 0xC, count) || !count || count > 4096 ||
        !Field(base, resource, 0x10, entries) || !Span(base, entries, count * 12) ||
        !Field(base, entries, 4, clump) || !Field(base, clump, 4, frame) || !Span(base, frame, 0xA4) ||
        ctx.esp < 16384 || !Span(base, uint64_t(ctx.esp) - 16384, 16384)) return;

    // Native 94C98 refreshes this two-update lifetime on personal-camera pre.
    // 97F38 counts it down; 9482C/94849 then use it to select the hands' action
    // animations, which own reload-ammo and melee-hit events. Retain that work
    // while the first-person meshes stay hidden and weapons stay world-attached.
    const uint32_t lifetime = 2;
    std::memcpy(base + uint64_t(inventory) + 0x90, &lifetime, sizeof(lifetime));


    // AECAE normally runs with the hands-only 15D flag enabled. It updates the
    // hidden skeleton and sends native frame message 50; 6A958 deduplicates it,
    // and 69662 rearms the clock consumed by 69370. Hiding the mesh must not stop
    // that cycle: reload-ammo and melee-hit callbacks belong to these tracks.
    // Run before the camera is displaced so callbacks retain the native aim ray.
    uint32_t saved_visible;
    std::memcpy(&saved_visible, base + model + 0x38, 4);
    std::array<uint8_t, 16384> saved_stack;
    std::memcpy(saved_stack.data(), base + ctx.esp - saved_stack.size(), saved_stack.size());
    struct Restore {
        uint8_t* flag; uint8_t* stack; uint32_t visible;
        const std::array<uint8_t, 16384>& saved;
        ~Restore() {std::memcpy(flag, &visible, 4); std::memcpy(stack, saved.data(), saved.size());}
    } restore{base + model + 0x38, base + ctx.esp - saved_stack.size(), saved_visible, saved_stack};
    const uint32_t visible = 1;
    std::memcpy(base + model + 0x38, &visible, 4);
    X86Context call = ctx;
    call.ecx = model;
    call.esp -= 64;
    const uint32_t args[]{0x1E89D2, 0}; // original update ignores its message argument
    std::memcpy(base + call.esp, args, sizeof(args));
    x86_icall(call, base, 0xAECAE);
}

// Personal-camera virtual +10 hides the owner with message 15D. Native follow
// cameras leave it visible; do the same only after a valid render scope begins.
X86_FUNC(sub_000BCBB7) {
    if (DarkwatchBeginThirdPersonRender(ctx, base, ctx.ecx)) {
        ctx.esp += 4;
        return;
    }
    __imp__sub_000BCBB7(ctx, base);
}

X86_FUNC(sub_000BCBE3) {
    DarkwatchEndThirdPersonRender(ctx, base, ctx.ecx);
    // Keep the original post-render visibility reset for every camera pass.
    __imp__sub_000BCBE3(ctx, base);
}

X86_FUNC(sub_000DEDD0) {
    // Suppress only the matching first-person hands/weapon draw. Its manager
    // still restores projection, clipping and camera state after this call.
    const uint64_t argument = uint64_t(ctx.esp) + 4;
    if (base && argument + 4 <= (uint64_t(1) << 32) &&
        mem::IsCommitted(uint32_t(argument) & ~(mem::kPage - 1)) &&
        mem::IsCommitted(uint32_t(argument + 3) & ~(mem::kPage - 1))) {
        uint32_t camera;
        std::memcpy(&camera, base + argument, sizeof(camera));
        if (DarkwatchThirdPersonRenderActive(base, camera)) {
            ctx.esp += 8; // original ret 4
            return;
        }
    }
    __imp__sub_000DEDD0(ctx, base);
}
