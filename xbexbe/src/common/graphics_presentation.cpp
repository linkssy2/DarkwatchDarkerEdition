#include <cstring>
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include "xdk/d3d8.h"
#include "prompt_owner.h"
#include "graphics_presentation.h"
#include "graphics_view.h"

X86_EXTERN_FUNC(__imp__sub_0021B0D1);
X86_EXTERN_FUNC(__imp__sub_001EC5F4);
X86_EXTERN_FUNC(__imp__sub_000EF592);
X86_EXTERN_FUNC(__imp__sub_00326CD1);
X86_EXTERN_FUNC(__imp__sub_001F16EF);
X86_EXTERN_FUNC(__imp__sub_00132B60);
X86_EXTERN_FUNC(__imp__sub_00130D70);
X86_EXTERN_FUNC(__imp__sub_001ED841);
X86_EXTERN_FUNC(__imp__sub_000E4EBD);

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
bool Frontend(const uint8_t* base, uint32_t manager) {
    return manager && UiSpan(base, 0x4AD664, 4) && UiRead(base, 0x4AD664) == manager &&
        UiSpan(base, manager, 0x7C) && UiRead(base, manager + 8) <= 20;
}
void Present(X86Context& ctx, uint8_t* base, X86Func& original, bool valid, bool overlay = true,
             bool safe_area = false, bool original_aspect = false) {
    if (!valid) {
        original(ctx, base);
        return;
    }
    // Effects sample the previous guest front buffer; keep native UI out of it.
    std::lock_guard lock(d3d::Lock());
    auto& state = d3d::State();
    struct Restore {
        gpu::State& state; bool overlay, safe_area, original_aspect;
        ~Restore() {
            state.presentation_overlay = overlay; state.presentation_safe_area = safe_area;
            state.presentation_original_aspect = original_aspect;
        }
    } restore{state, state.presentation_overlay, state.presentation_safe_area, state.presentation_original_aspect};
    state.presentation_overlay = overlay;
    state.presentation_safe_area = safe_area;
    state.presentation_original_aspect = original_aspect;
    original(ctx, base);
}
} // namespace

bool darkwatch::presentation::OriginalRoot(const uint8_t* base, uint32_t root) {
    if (!darkwatch::view::Snapshot().original_ui_aspect || !UiSpan(base, root, 0x48)) return false;
    const uint32_t table = UiRead(base, root);
    if (table == 0x427740 || table == 0x43FB40) return false; // HUD and subtitles.
    if (table == 0x42A4C0) return true; // Native LoadingRect.
    if (!UiSpan(base, 0x4AD664, 4)) return false;
    const uint32_t manager = UiRead(base, 0x4AD664);
    if (!Frontend(base, manager)) return false;
    const uint32_t count = UiRead(base, manager + 8);
    for (uint32_t i = 0; i < count; ++i)
        if (UiRead(base, manager + 12 + i * 4) == root) return true;
    // A popped page remains visible while its native outgoing fade completes.
    return UiRead(base, manager + 0x5C) == root;
}

X86_FUNC(sub_000E4EBD) {
    const bool original = darkwatch::view::Snapshot().original_ui_aspect &&
        Frontend(base, ctx.ecx) && CameraArgument(ctx, base);
    // This manager draws the main-menu movie or its static fallback before the
    // registered pages. Keep it on the native target; menus remain above it.
    Present(ctx, base, __imp__sub_000E4EBD, original, false, true, true);
}

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
        UiSpan(base, ctx.ecx, 0x48) && UiRead(base, ctx.ecx) == 0x43FB40 && UiSpan(base, ctx.esp, 8), true, true);
}

X86_FUNC(sub_001EC5F4) {
    bool valid = UiSpan(base, ctx.ecx, 0x48) && CameraArgument(ctx, base);
    bool overlay = true, safe_area = false;
    if (valid) {
        const uint32_t table = UiRead(base, ctx.ecx);
        valid = UiSpan(base, table, 0x48) &&
            (UiRead(base, table + 0x30) == 0x1EC5F4 ||
             (table == 0x427740 && UiRead(base, table + 0x30) == 0xD955F) ||
             (table == 0x43FB40 && UiRead(base, table + 0x30) == 0x21B0D1));
        // LoadingRect multiplies loading text; both must keep the same native target.
        overlay = table != 0x42A4C0;
        // The HUD keeps its independently edge-anchored groups. Native menus
        // and subtitles keep their authored proportions in a centered safe area.
        safe_area = table != 0x427740;
    }
    // This original orthographic draw covers HUD children and registered menu roots.
    // Leave the later D955F world-effect dispatch outside the scope.
    darkwatch::prompt_owner::Scope owner(base, valid ? ctx.ecx : 0);
    Present(ctx, base, __imp__sub_001EC5F4, valid, overlay, safe_area,
        valid && darkwatch::presentation::OriginalRoot(base, ctx.ecx));
}

X86_FUNC(sub_001ED841) {
    // Native warnings and loading transitions dim the full display. Their
    // untextured black sprites extend beyond the centered frame/profileIcon.
    bool fade = d3d::State().presentation_safe_area && UiSpan(base, ctx.esp, 8) &&
        (UiRead(base, ctx.esp) == 0x1F00F5 || UiRead(base, ctx.esp) == 0xEEE1B ||
         UiRead(base, ctx.esp) == 0xEFCB5 || UiRead(base, ctx.esp) == 0xED75A ||
         UiRead(base, ctx.esp) == 0x1EC09C);
    if (fade) {
        const uint32_t sprite = UiRead(base, ctx.esp + 4);
        fade = UiSpan(base, sprite, 0x60) && UiSpan(base, UiRead(base, sprite + 0x20), 0x38) &&
            UiRead(base, sprite + 0x24) == 0 && (UiRead(base, sprite + 0x28) & 0xFFFFFF) == 0;
        if (fade && (UiRead(base, ctx.esp) == 0xEFCB5 || UiRead(base, ctx.esp) == 0xED75A ||
                     UiRead(base, ctx.esp) == 0x1EC09C)) {
            // Title backdrops and pause scrims cover the display; bounded panels do not.
            constexpr float full[]{0, 0, 1, 1};
            fade = std::memcmp(base + sprite, full, sizeof(full)) == 0;
        }
    }
    Present(ctx, base, __imp__sub_001ED841, fade, d3d::State().presentation_overlay);
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
