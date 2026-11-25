#include "hd_ui.h"
#include "hd_ui_pack.h"
#include "graphics_view.h"
#include "app/app.h"
#include "cpu/x86_context.h"
#include "gpu/texture.h"
#include "kernel/memory.h"
#include "core/log.h"
#include <algorithm>
#include <cmath>
#include <cstring>

namespace {
bool Span(uint8_t* base, uint64_t address, uint32_t bytes) {
    if (!base || !address || address + bytes > (uint64_t(1) << 32)) return false;
    for (auto page = address & ~(uint64_t(mem::kPage)-1); page < address + bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
}

void DarkwatchPublisherQuad(X86Context& ctx, uint8_t* base) {
    if (!darkwatch::HdStartupActive() || ctx.ebp < 0x24 ||
        !Span(base,ctx.ebp-0x24,112) || !Span(base,ctx.esi,0x28) ||
        !Span(base,0x4DF098,4) || !Span(base,0x4AE5BC,4)) return;
    const auto read=[&](uint32_t p){uint32_t v;std::memcpy(&v,base+p,4);return v;};
    const uint32_t raster=read(ctx.esi+0x24), extension=read(0x4DF098);
    // Native 131FDF..131FEB stages this raster's D3D header at 4DEB50.
    // d3d::State still describes the preceding draw until the pending state flushes.
    if (!raster || read(0x4AE5BC)!=raster || extension<0x20 || extension>0x1000 ||
        !Span(base,uint64_t(raster)+extension,4)) return;
    const uint32_t header=read(raster+extension);
    if (!Span(base,header,20)) return;
    gpu::TextureDesc texture;
    if (!gpu::Describe(header,texture) || texture.format != 12 ||
        texture.width != 512 || texture.height != 128 || texture.levels != 1 ||
        texture.depth != 1 || texture.cube || texture.linear ||
        !Span(base,texture.data,32768) ||
        darkwatch::hd::Hash({base+texture.data,32768}) != 0x617ec337768305acull) return;
    float vertices[4][7];
    std::memcpy(vertices,base+ctx.ebp-0x24,sizeof(vertices));
    for (const auto& v:vertices)
        if (!std::isfinite(v[0]) || !std::isfinite(v[1])) return;
    // Captured native full-UV rectangle; enlarge uniformly about its center.
    if (vertices[0][0]!=vertices[2][0] || vertices[1][0]!=vertices[3][0] ||
        vertices[0][1]!=vertices[1][1] || vertices[2][1]!=vertices[3][1]) return;
    constexpr float uv[4][2]{{0,0},{1,0},{0,1},{1,1}};
    for (unsigned i=0;i<4;++i)
        if (vertices[i][5]!=uv[i][0] || vertices[i][6]!=uv[i][1]) return;
    const float height=(vertices[2][1]-vertices[0][1])*1.5f;
    float aspect=app::RenderAspect();
    if (!std::isfinite(aspect) || aspect<=0 || height<=0 ||
        vertices[1][0]<=vertices[0][0]) return;
    if (aspect>4.f/3.f)
        aspect=darkwatch::view::Snapshot().original_ui_aspect ? 4.f/3.f : 16.f/9.f;
    // EDI is the drawing camera's raster (1ED857..1ED85B).
    if (!Span(base,ctx.edi,0x14)) return;
    const uint32_t w=read(ctx.edi+0xC),h=read(ctx.edi+0x10);
    if (!w || !h || w>16384 || h>16384) return;
    const float width=height*4.f*float(w)/float(h)/aspect;
    const float center=(vertices[0][0]+vertices[1][0])*.5f;
    const float center_y=(vertices[0][1]+vertices[2][1])*.5f;
    if (!std::isfinite(width) || width<=0) return;
#ifndef XBE_RELEASE
    LOG_FIRST(1,"Capcom logo: native width %.3f -> %.3f, height %.3f, presentation aspect %.5f", vertices[1][0]-vertices[0][0],width,height,aspect);
#endif
    for (unsigned i=0;i<4;++i) {
        const float position[]{center+(i%2 ? .5f : -.5f)*width,
            center_y+(i>=2 ? .5f : -.5f)*height};
        std::memcpy(base+ctx.ebp-0x24+i*28,position,sizeof(position));
    }
}
