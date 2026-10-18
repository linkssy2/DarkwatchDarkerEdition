#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <new>
#include <span>
#include <vector>

namespace darkwatch::hd_ui {
namespace detail {
inline bool Extent(uint32_t w, uint32_t h, size_t& bytes) {
    // Four-times output must remain within the D3D12 2D texture limit.
    if (!w || !h || w > 4096 || h > 4096) return false;
    const uint64_t size = uint64_t(w) * h * 4;
    if (size > std::numeric_limits<size_t>::max()) return false;
    bytes = size_t(size); return true;
}
inline uint16_t U16(const uint8_t* p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
inline uint32_t U32(const uint8_t* p) { return uint32_t(U16(p)) | uint32_t(U16(p+2)) << 16; }
inline std::array<uint8_t,3> Bgr565(uint16_t c) {
    return {uint8_t((c & 31) * 255 / 31), uint8_t(((c >> 5) & 63) * 255 / 63), uint8_t((c >> 11) * 255 / 31)};
}
inline float Cubic(float a, float b, float c, float d, float t) {
    const float value = b + 0.5f*t*((c-a) + t*((2*a-5*b+4*c-d) + t*(3*(b-c)+d-a)));
    // Limit to the two bracketing samples: no negative coverage, ringing, or
    // opacity spreading across a transparent atlas gutter from distant taps.
    return std::clamp(value, std::min(b,c), std::max(b,c));
}
inline uint8_t Byte(float f) { return uint8_t(std::clamp(std::floor(f+0.5f),0.f,255.f)); }
} // namespace detail

// Original Xbox native formats:0=P8 Morton indices with BGRA palette,
//12=BC1,15=BC3. Output is straight-alpha BGRA. BC interpolation uses the
// retained deterministic integer-floor reference, not a GPU rounding claim.
inline bool DecodeNative(uint32_t width, uint32_t height, uint32_t format,
                         std::span<const uint8_t> payload, std::span<const uint8_t> palette,
                         std::vector<uint8_t>& bgra) {
    size_t bytes=0;
    if (!detail::Extent(width,height,bytes)) return false;
    const bool indexed=format==0, bc3=format==15;
    if (indexed) {
        if ((width&(width-1)) || (height&(height-1)) || palette.size()!=1024 || payload.size()!=bytes/4) return false;
    } else {
        if ((format!=12 && !bc3) || !palette.empty() ||
            payload.size()!=uint64_t((width+3)/4)*((height+3)/4)*(bc3?16:8)) return false;
    }
    std::vector<uint8_t> result;
    try { result.resize(bytes); } catch (const std::bad_alloc&) { return false; }
    if (indexed) {
        for (uint32_t y=0;y<height;++y) for (uint32_t x=0;x<width;++x) {
            uint32_t address=0,target=1;
            for (uint32_t source=1;source<width || source<height;source<<=1) {
                if (source<width) { if(x&source)address|=target;target<<=1; }
                if (source<height) { if(y&source)address|=target;target<<=1; }
            }
            std::copy_n(palette.data()+4*payload[address],4,result.data()+(size_t(y)*width+x)*4);
        }
    } else {
        const uint32_t blocks_x=(width+3)/4,blocks_y=(height+3)/4;
        for (uint32_t by=0;by<blocks_y;++by) for (uint32_t bx=0;bx<blocks_x;++bx) {
            const auto* block=payload.data()+(size_t(by)*blocks_x+bx)*(bc3?16:8);
            std::array<uint8_t,8> alpha{};uint64_t alpha_bits=0;
            if (bc3) {
                alpha[0]=block[0];alpha[1]=block[1];
                if (alpha[0]>alpha[1]) for(unsigned i=1;i<7;++i)alpha[i+1]=uint8_t(((7-i)*alpha[0]+i*alpha[1])/7);
                else {for(unsigned i=1;i<5;++i)alpha[i+1]=uint8_t(((5-i)*alpha[0]+i*alpha[1])/5);alpha[6]=0;alpha[7]=255;}
                for(unsigned i=0;i<6;++i)alpha_bits|=uint64_t(block[2+i])<<(8*i);
            }
            const auto* rgb=block+(bc3?8:0);
            const uint16_t c0=detail::U16(rgb),c1=detail::U16(rgb+2);
            const uint32_t bits=detail::U32(rgb+4);
            std::array<std::array<uint8_t,3>,4> colors{detail::Bgr565(c0),detail::Bgr565(c1),{}, {}};
            for(unsigned c=0;c<3;++c) {
                if(bc3 || c0>c1) {colors[2][c]=uint8_t((2*colors[0][c]+colors[1][c])/3);colors[3][c]=uint8_t((colors[0][c]+2*colors[1][c])/3);}
                else colors[2][c]=uint8_t((colors[0][c]+colors[1][c])/2);
            }
            for(unsigned i=0;i<16;++i) {
                const uint32_t x=bx*4+i%4,y=by*4+i/4;
                if(x>=width || y>=height)continue;
                const unsigned index=(bits>>(i*2))&3;auto* p=result.data()+(size_t(y)*width+x)*4;
                std::copy_n(colors[index].data(),3,p);
                p[3]=bc3?alpha[(alpha_bits>>(i*3))&7]:uint8_t(c0<=c1 && index==3?0:255);
            }
        }
    }
    bgra.swap(result);return true;
}

// Existing atlas layout and UVs stay unchanged. The cubic is limited in each
// axis; fully transparent central neighborhoods remain transparent. It cannot
// isolate touching atlas cells without cell metadata, just as linear sampling
// cannot. No sharpening, thresholding, glyph redraw, or added mip levels.
inline std::vector<uint8_t> Upscale4x(uint32_t width, uint32_t height, const std::vector<uint8_t>& bgra) {
    size_t bytes=0;
    if(!detail::Extent(width,height,bytes) || bgra.size()!=bytes || bytes>std::numeric_limits<size_t>::max()/16)return {};
    using Pixel=std::array<float,4>;
    const uint32_t out_width=width*4,out_height=height*4;
    std::vector<uint8_t> output;
    std::array<std::vector<Pixel>,4> rows;
    try {output.resize(bytes*16);for(auto& row:rows)row.resize(out_width);}catch(const std::bad_alloc&){return {};}
    std::array<int,4> loaded{-1,-1,-1,-1};
    auto load=[&](int y)->const std::vector<Pixel>& {
        auto& row=rows[unsigned(y)%4];
        if(loaded[unsigned(y)%4]==y)return row;
        loaded[unsigned(y)%4]=y;
        for(uint32_t x=0;x<out_width;++x) {
            const float source=(float(x)+.5f)*.25f-.5f;const int first=int(std::floor(source));const float t=source-first;
            Pixel samples[4];
            for(int k=0;k<4;++k) {
                const int sx=std::clamp(first+k-1,0,int(width)-1);
                const auto* p=bgra.data()+(size_t(y)*width+unsigned(sx))*4;
                for(unsigned c=0;c<3;++c)samples[k][c]=float(p[c])*p[3]/255.f;
                samples[k][3]=p[3];
            }
            for(unsigned c=0;c<4;++c)row[x][c]=detail::Cubic(samples[0][c],samples[1][c],samples[2][c],samples[3][c],t);
        }
        return row;
    };
    for(uint32_t y=0;y<out_height;++y) {
        const float source=(float(y)+.5f)*.25f-.5f;const int first=int(std::floor(source));const float t=source-first;
        std::array<const std::vector<Pixel>*,4> samples;
        for(int k=0;k<4;++k)samples[k]=&load(std::clamp(first+k-1,0,int(height)-1));
        for(uint32_t x=0;x<out_width;++x) {
            Pixel p;for(unsigned c=0;c<4;++c)p[c]=detail::Cubic((*samples[0])[x][c],(*samples[1])[x][c],(*samples[2])[x][c],(*samples[3])[x][c],t);
            auto* out=output.data()+(size_t(y)*out_width+x)*4;out[3]=detail::Byte(p[3]);
            for(unsigned c=0;c<3;++c)out[c]=out[3]?detail::Byte(std::clamp(p[c],0.f,p[3])*255.f/p[3]):0;
        }
    }
    return output;
}
} // namespace darkwatch::hd_ui
