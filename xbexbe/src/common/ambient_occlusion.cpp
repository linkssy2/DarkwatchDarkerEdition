#include "ambient_occlusion.h"
#include <cstring>
#include "app/app.h"
#include "cpu/x86_context.h"
#include "graphics_camera.h"
#include "kernel/memory.h"
#include "xdk/d3d8.h"

void DarkwatchAmbientOcclusionWorldPass(X86Context& ctx, uint8_t* base) {
    if (!app::Snapshot().ambient_occlusion || !base || !ctx.ebp ||
        uint64_t(ctx.ebp) + 12 > (uint64_t(1) << 32)) return;
    for (uint64_t page = ctx.ebp & ~(uint64_t(mem::kPage) - 1);
         page < uint64_t(ctx.ebp) + 12; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return;
    uint32_t caller, camera;
    std::memcpy(&caller, base + ctx.ebp + 4, 4);
    std::memcpy(&camera, base + ctx.ebp + 8, 4);
    // Only the per-view world pass, before late blended batches and weapon depth clear.
    if (caller != 0x1D7E1E) return;
    std::lock_guard lock(d3d::Lock());
    const auto& state = d3d::State();
    if (state.presentation_overlay ||
        !DarkwatchWorldProjectionMatches(base, camera, state.transforms[3])) return;
    d3d::ApplyAmbientOcclusion(state.transforms[3]);
}
