#include <cstring>
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include "xdk/d3d8.h"
#include "prompt_owner.h"

X86_EXTERN_FUNC(__imp__sub_0021B0D1);
X86_EXTERN_FUNC(__imp__sub_001EC5F4);
X86_EXTERN_FUNC(__imp__sub_000EF592);
X86_EXTERN_FUNC(__imp__sub_00326CD1);
X86_EXTERN_FUNC(__imp__sub_001F16EF);
X86_EXTERN_FUNC(__imp__sub_00132B60);
X86_EXTERN_FUNC(__imp__sub_00130D70);

namespace {
bool UiSpan(const uint8_t* base, uint64_t address, uint32_t size) {
    if (!base || !address || address + size > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < address + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t UiRead(const uint8_t* base, uint32_t address) {
    uint32_t value; std::memcpy(&value, base + address, 4); return value;
}
bool CameraArgument(const X86Context& ctx, const uint8_t* base) {
    return UiSpan(base, ctx.esp, 8) && UiSpan(base, UiRead(base, ctx.esp + 4), 0x38);
}
void Present(X86Context& ctx, uint8_t* base, X86Func& original, bool valid, bool overlay = true) {
    if (!valid) {
        original(ctx, base);
        return;
    }
    // Effects sample the previous guest front buffer; keep native UI out of it.
    std::lock_guard lock(d3d::Lock());
    auto& layer = d3d::State().presentation_overlay;
    struct Restore { bool& value; bool previous; ~Restore() { value = previous; } } restore{layer, layer};
    layer = overlay;
    original(ctx, base);
}
} // namespace

X86_FUNC(sub_00132B60) {
    const bool ui_alpha = d3d::State().presentation_overlay &&
        UiSpan(base, ctx.esp, 12) && UiRead(base, ctx.esp + 4) == 12;
    __imp__sub_00132B60(ctx, base);
    if (!ui_alpha || !UiSpan(base, 0x4AE5A8, 8) || !UiSpan(base, 0x4DE56C, 4) ||
        ctx.esp < 32 || !UiSpan(base, uint64_t(ctx.esp) - 32, 32)) return;

    // Material passes can override the low-level blend cache without changing
    // RenderWare's logical alpha flags. Its repeated UI alpha request then
    // returns early, leaving the first HUD bitmap opaque. Reconcile only that
    // explicit UI request through the original coherent render-state setter.
    const uint32_t blend = UiRead(base, 0x4AE5A8) != 0 || UiRead(base, 0x4AE5AC) != 0;
    if (UiRead(base, 0x4DE56C) == blend) return;
    uint8_t previous[32];
    std::memcpy(previous, base + ctx.esp - sizeof(previous), sizeof(previous));
    struct Restore {
        uint8_t* target; const uint8_t* saved;
        ~Restore() { std::memcpy(target, saved, 32); }
    } restore{base + ctx.esp - sizeof(previous), previous};
    X86Context call = ctx;
    call.esp -= 12;
    const uint32_t args[]{UiRead(base, ctx.esp - 4), 0x3B, blend};
    std::memcpy(base + call.esp, args, sizeof(args));
    __imp__sub_00130D70(call, base);
}

X86_FUNC(sub_0021B0D1) {
    Present(ctx, base, __imp__sub_0021B0D1,
        UiSpan(base, ctx.ecx, 0x48) && UiRead(base, ctx.ecx) == 0x43FB40 && UiSpan(base, ctx.esp, 8));
}

X86_FUNC(sub_001EC5F4) {
    bool valid = UiSpan(base, ctx.ecx, 0x48) && CameraArgument(ctx, base);
    bool overlay = true;
    if (valid) {
        const uint32_t table = UiRead(base, ctx.ecx);
        valid = UiSpan(base, table, 0x48) &&
            (UiRead(base, table + 0x30) == 0x1EC5F4 ||
             (table == 0x427740 && UiRead(base, table + 0x30) == 0xD955F) ||
             (table == 0x43FB40 && UiRead(base, table + 0x30) == 0x21B0D1));
        // LoadingRect multiplies the scene's colors; keep its whole loading root native.
        overlay = table != 0x42A4C0;
    }
    // This original orthographic draw covers HUD children and registered menu roots.
    // Leave the later D955F world-effect dispatch outside the scope.
    darkwatch::prompt_owner::Scope owner(base, valid ? ctx.ecx : 0);
    Present(ctx, base, __imp__sub_001EC5F4, valid, overlay);
}

X86_FUNC(sub_000EF592) {
    // The modal dimmer precedes its menu roots; both must remain above the HUD.
    Present(ctx, base, __imp__sub_000EF592,
        CameraArgument(ctx, base) && UiSpan(base, 0x4AD810, 16));
}

X86_FUNC(sub_00326CD1) {
    Present(ctx, base, __imp__sub_00326CD1,
        UiSpan(base, ctx.ecx, 0x3C) && UiRead(base, ctx.ecx) == 0x478244 && CameraArgument(ctx, base));
}

X86_FUNC(sub_001F16EF) {
    // Only the late fade belongs above UI; the early 1F16E1 variant stays native.
    Present(ctx, base, __imp__sub_001F16EF,
        UiSpan(base, ctx.ecx, 0x5C) && UiRead(base, ctx.ecx) == 0x43CBAC && CameraArgument(ctx, base));
}
