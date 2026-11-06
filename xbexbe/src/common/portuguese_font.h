#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <span>
#include <vector>

namespace darkwatch::portuguese_font {
struct Image { unsigned width=0,height=0; std::vector<uint8_t> bgra; };
struct Cell { float x0,y0,x1,y1; };
struct Rect { unsigned x=0,y=0,width=0,height=0; };
inline bool Bounds(unsigned width,unsigned height,Cell cell,Rect& out) {
    if(!std::isfinite(cell.x0)||!std::isfinite(cell.y0)||!std::isfinite(cell.x1)||!std::isfinite(cell.y1)||
       cell.x0<0||cell.y0<0||cell.x1<=cell.x0||cell.y1<=cell.y0||cell.x1>width||cell.y1>height)return false;
    out={unsigned(std::floor(cell.x0)),unsigned(std::floor(cell.y0)),
         unsigned(std::ceil(cell.x1))-unsigned(std::floor(cell.x0)),
         unsigned(std::ceil(cell.y1))-unsigned(std::floor(cell.y0))};
    return out.width&&out.height&&out.width<=512&&out.height<=512;
}
inline unsigned InkTop(unsigned stride,std::span<const uint8_t> pixels,Rect r) {
    for(unsigned y=0;y<r.height;++y)for(unsigned x=0;x<r.width;++x)
        if(pixels[((r.y+y)*stride+r.x+x)*4+3]>=224)return y;
    return r.height;
}
// Derive only the missing A/O tilde letters from this exact original font.
// The unaccented letter, its bearings and its baseline remain byte-identical.
// A non-glow companion isolates the authored N-tilde mark for glow sheets.
inline bool Compose(unsigned width,unsigned height,std::span<const uint8_t> pixels,
                    std::span<const uint8_t> core,Cell letter,Cell n,Cell n_tilde,Image& out) {
    if(pixels.size()!=uint64_t(width)*height*4||core.size()!=pixels.size())return false;
    Rect a{},b{},c{};
    if(!Bounds(width,height,letter,a)||!Bounds(width,height,n,b)||!Bounds(width,height,n_tilde,c)||
       a.height!=b.height||b.height!=c.height)return false;
    const unsigned n_top=InkTop(width,core,b),a_top=InkTop(width,core,a);
    if(n_top<2||n_top>=b.height||a_top>=a.height)return false;
    const int dx=(int(a.width)-int(c.width))/2,dy=int(a_top)-int(n_top);
    Image result{a.width,a.height,std::vector<uint8_t>(size_t(a.width)*a.height*4)};
    for(unsigned y=0;y<a.height;++y)
        std::memcpy(result.bgra.data()+size_t(y)*a.width*4,
                    pixels.data()+((a.y+y)*width+a.x)*4,size_t(a.width)*4);
    bool mark=false;
    for(unsigned y=0;y<n_top;++y)for(unsigned x=0;x<c.width;++x) {
        const int tx=int(x)+dx,ty=int(y)+dy;
        if(tx<0||ty<0||tx>=int(a.width)||ty>=int(a_top))continue;
        const size_t src=((c.y+y)*width+c.x+x)*4;
        if(!pixels[src+3])continue;
        mark|=core[src+3]>=16;
        auto* dest=result.bgra.data()+(size_t(ty)*a.width+unsigned(tx))*4;
        // Choose the more opaque original texel where glow skirts overlap.
        // Adding alpha would brighten the existing letter's halo.
        if(pixels[src+3]>dest[3])std::memcpy(dest,pixels.data()+src,4);
    }
    if(!mark)return false;
    out=std::move(result);return true;
}
// Title has no authored accents. Borrow only the mark from the original Large
// heading face, retaining Title's letter, native cell, advance and baseline.
inline bool ComposeHeading(unsigned width,unsigned height,std::span<const uint8_t> pixels,Cell letter,
                           unsigned donor_width,unsigned donor_height,std::span<const uint8_t> donor,
                           Cell plain,Cell accented,bool below,Image& out) {
    if(pixels.size()!=uint64_t(width)*height*4||donor.size()!=uint64_t(donor_width)*donor_height*4)return false;
    Rect a{},b{},c{};
    if(!Bounds(width,height,letter,a)||!Bounds(donor_width,donor_height,plain,b)||
       !Bounds(donor_width,donor_height,accented,c)||b.height!=c.height)return false;
    auto edge=[&](unsigned stride,std::span<const uint8_t> p,Rect r) {
        if(!below)return InkTop(stride,p,r);
        for(unsigned y=r.height;y;--y)for(unsigned x=0;x<r.width;++x)
            if(p[((r.y+y-1)*stride+r.x+x)*4+3]>=224)return y;
        return r.height;
    };
    const unsigned start=below?edge(donor_width,donor,b):0,end=below?c.height:edge(donor_width,donor,b);
    const int dx=(int(a.width)-int(c.width))/2,dy=int(edge(width,pixels,a))-int(below?start:end);
    if(start>=end||end-start>a.height||dy+int(start)<0||dy+int(end)>int(a.height))return false;
    Image result{a.width,a.height,std::vector<uint8_t>(size_t(a.width)*a.height*4)};
    for(unsigned y=0;y<a.height;++y)std::memcpy(result.bgra.data()+size_t(y)*a.width*4,
        pixels.data()+((a.y+y)*width+a.x)*4,size_t(a.width)*4);
    bool mark=false;
    for(unsigned y=start;y<end;++y)for(unsigned x=0;x<c.width;++x) {
        const int tx=int(x)+dx;if(tx<0||tx>=int(a.width))continue;
        const auto* source=donor.data()+((c.y+y)*donor_width+c.x+x)*4;
        mark|=source[3]>=224;
        auto* dest=result.bgra.data()+(size_t(int(y)+dy)*a.width+unsigned(tx))*4;
        if(source[3]>dest[3])std::memcpy(dest,source,4);
    }
    if(!mark)return false;
    out=std::move(result);return true;
}
} // namespace darkwatch::portuguese_font
