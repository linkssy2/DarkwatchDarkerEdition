#pragma once
#include "hd_ui_filter.h"
#include "hd_ui_pack.h"
#include "hd_ui_font_cells.h"

namespace darkwatch::hd_ui {
namespace font_detail {
struct Point { float x, y; };
struct Edge { Point a, b; };

// An alpha-derived vector boundary, not a replacement alphabet. The original
// cell's peak retains intentionally faint glyphs. Saddles use the bilinear
// asymptotic decision; holes follow this coverage contour, not a guessed font.
inline std::vector<Edge> Contour(uint32_t width, std::span<const uint8_t> pixels,
                                 FontCell cell, uint8_t peak, float level=.5f) {
    std::vector<Edge> edges;
    if (!peak) return edges;
    const float iso = float(peak) * std::max(level,.000001f);
    const int left=int(std::floor(cell.x0)),top=int(std::floor(cell.y0));
    const int right=int(std::ceil(cell.x1)),bottom=int(std::ceil(cell.y1));
    auto alpha = [&](int x, int y) -> float {
        if (x < left || x >= right || y < top || y >= bottom) return 0;
        return pixels[(size_t(y) * width + unsigned(x)) * 4 + 3];
    };
    for (int y = top-1; y < bottom; ++y) {
        for (int x = left-1; x < right; ++x) {
            const float v[4]{alpha(x,y), alpha(x+1,y), alpha(x+1,y+1), alpha(x,y+1)};
            unsigned bits = 0;
            for (unsigned i=0;i<4;++i) if(v[i]>=iso) bits |= 1u<<i;
            if (!bits || bits == 15) continue;
            const Point p[4]{{x+.5f,y+.5f},{x+1.5f,y+.5f},{x+1.5f,y+1.5f},{x+.5f,y+1.5f}};
            auto cross = [&](unsigned e) {
                const unsigned n=(e+1)&3;
                const float t=(iso-v[e])/(v[n]-v[e]);
                return Point{p[e].x+t*(p[n].x-p[e].x),p[e].y+t*(p[n].y-p[e].y)};
            };
            auto add = [&](unsigned a,unsigned b) { edges.push_back({cross(a),cross(b)}); };
            switch(bits) {
            case 1: case 14: add(3,0);break;
            case 2: case 13: add(0,1);break;
            case 3: case 12: add(3,1);break;
            case 4: case 11: add(1,2);break;
            case 6: case 9: add(0,2);break;
            case 7: case 8: add(3,2);break;
            case 5: case 10:
                if ((v[0]-iso)*(v[2]-iso) >= (v[1]-iso)*(v[3]-iso)) {add(0,1);add(2,3);}
                else {add(3,0);add(1,2);}break;
            }
        }
    }
    return edges;
}

inline uint64_t DrawCell(uint32_t width, std::span<const uint8_t> source,
                        FontCell cell, std::vector<uint8_t>& output, float level=.5f) {
    uint8_t peak=0;
    for(unsigned y=unsigned(std::floor(cell.y0));y<unsigned(std::ceil(cell.y1));++y)
      for(unsigned x=unsigned(std::floor(cell.x0));x<unsigned(std::ceil(cell.x1));++x)
        peak=std::max(peak,source[(size_t(y)*width+x)*4+3]);
    const auto edges=Contour(width,source,cell,peak,level);
    const unsigned first=unsigned(cell.x0*4),last=unsigned(cell.x1*4),out_width=width*4;
    std::vector<float> coverage(last-first), crossings;
    // Eight exact horizontal interval integrations per output row. This samples
    // vector edges at the new resolution; it does not enlarge source antialiasing.
    constexpr unsigned samples=8;
    uint64_t area=0;
    for(unsigned y=unsigned(cell.y0*4);y<unsigned(cell.y1*4);++y) {
        std::fill(coverage.begin(),coverage.end(),0.f);
        for(unsigned s=0;s<samples;++s) {
            const float sy=(float(y)+(s+.5f)/samples)*.25f;
            crossings.clear();
            for(const auto& e:edges) {
                if ((e.a.y<=sy && sy<e.b.y) || (e.b.y<=sy && sy<e.a.y))
                    crossings.push_back(4*(e.a.x+(sy-e.a.y)*(e.b.x-e.a.x)/(e.b.y-e.a.y)));
            }
            std::sort(crossings.begin(),crossings.end());
            for(size_t i=0;i+1<crossings.size();i+=2) {
                const float lo=std::clamp(crossings[i],float(first),float(last));
                const float hi=std::clamp(crossings[i+1],float(first),float(last));
                for(unsigned x=unsigned(std::floor(lo));x<std::min(last,unsigned(std::ceil(hi)));++x)
                    coverage[x-first]+=std::max(0.f,std::min(hi,float(x+1))-std::max(lo,float(x)))/samples;
            }
        }
        for(unsigned x=first;x<last;++x) {
            auto* p=output.data()+(size_t(y)*out_width+x)*4;
            p[3]=detail::Byte(coverage[x-first]*peak);
            area+=p[3];
        }
    }
    return area;
}

inline void RestoreCell(uint32_t width, std::span<const uint8_t> source,
                        FontCell cell, std::vector<uint8_t>& output) {
    double source_area=0;
    for(unsigned y=unsigned(std::floor(cell.y0));y<unsigned(std::ceil(cell.y1));++y)
      for(unsigned x=unsigned(std::floor(cell.x0));x<unsigned(std::ceil(cell.x1));++x) {
        const double wx=std::min(cell.x1,float(x+1))-std::max(cell.x0,float(x));
        const double wy=std::min(cell.y1,float(y+1))-std::max(cell.y0,float(y));
        source_area+=wx*wy*source[(size_t(y)*width+x)*4+3];
    }
    const double target=source_area*16;
    float lo=0,hi=1,best=.5f,above=.5f;
    double error=std::numeric_limits<double>::max();
    uint64_t above_area=std::numeric_limits<uint64_t>::max();
    // Match the original integrated coverage; a fixed 50% contour can inflate
    // stroke weight. This derives a bounded silhouette, not an unknown font.
    for(unsigned i=0;i<13;++i) {
        const float level=(lo+hi)*.5f;
        const uint64_t area=DrawCell(width,source,cell,output,level);
        const double difference=std::abs(double(area)-target);
        if(difference<error){error=difference;best=level;}
        if(area>=target && area<above_area){above_area=area;above=level;}
        if(area>target)lo=level;else hi=level;
    }
    const uint64_t area=DrawCell(width,source,cell,output,
        above_area!=std::numeric_limits<uint64_t>::max()?above:best);
    // A constant-alpha patch can make the contour area jump at one level. Keep
    // the closest covering contour and lower its opacity, never inflate weight.
    if(area>target) {
        const double ratio=target/area;
        for(unsigned y=unsigned(cell.y0*4);y<unsigned(cell.y1*4);++y)
          for(unsigned x=unsigned(cell.x0*4);x<unsigned(cell.x1*4);++x) {
            auto& a=output[(size_t(y)*width*4+x)*4+3];
            a=detail::Byte(float(a*ratio));
        }
    }
}

// The two heading sheets bake their metallic bevel into grayscale RGB inside
// a black outline. Rescan its light coverage, then retain half the original RGB
// shading so the result keeps its authored directional bevel rather than a flat
// white face. Alpha and glyph layout are independent and remain unchanged.
inline bool RestoreHeadingRgb(const hd::Asset& asset,
                              std::span<const uint8_t> source,
                              const FontCells& font,
                              std::vector<uint8_t>& output) {
    if(asset.offset!=93423668u && asset.offset!=93457588u)return false;
    uint8_t low=255,high=0;
    for(size_t i=0;i<source.size();i+=4)if(source[i+3]) {
        if(source[i]!=source[i+1] || source[i+1]!=source[i+2])return false;
        low=std::min(low,source[i]);high=std::max(high,source[i]);
    }
    if(high<=low)return false;
    std::vector<uint8_t> face(source.size(),0),layer(output.size(),0);
    for(size_t i=0;i<source.size();i+=4)
        face[i+3]=source[i+3] ? uint8_t(source[i]-low) : 0;
    for(const auto& cell:font.cells)RestoreCell(asset.width,face,cell,layer);
    for(const auto& cell:font.cells)
      for(unsigned y=unsigned(cell.y0*4);y<unsigned(cell.y1*4);++y)
        for(unsigned x=unsigned(cell.x0*4);x<unsigned(cell.x1*4);++x) {
            const size_t i=(size_t(y)*asset.width*4+x)*4;
            const uint8_t gray=uint8_t((unsigned(output[i])+low+layer[i+3]+1)/2);
            output[i]=output[i+1]=output[i+2]=gray;
        }
    return true;
}
} // namespace font_detail

// Only exact known non-glow font records. Original cell positions, UVs and
// metrics stay fixed. Alpha is scan-converted from its subpixel contours. The
// two grayscale heading sheets also refine their original beveled face; other
// RGB comes from the original art. These are not recovered source outlines.
inline bool ReconstructFont(const hd::Asset& asset, std::span<const uint8_t> pixels,
                            std::vector<uint8_t>& output) {
    const auto* font=FindFontCells(asset.offset);
    if(!font || asset.width!=font->width || asset.height!=font->height ||
       pixels.size()!=uint64_t(asset.width)*asset.height*4) return false;
    std::vector<uint8_t> source(pixels.begin(),pixels.end());
    auto result=Upscale4x(asset.width,asset.height,source);
    if(result.empty())return false;
    for(const auto& cell:font->cells)font_detail::RestoreCell(asset.width,pixels,cell,result);
    font_detail::RestoreHeadingRgb(asset,pixels,*font,result);
    for(size_t i=0;i<result.size();i+=4)if(!result[i+3])result[i]=result[i+1]=result[i+2]=0;
    output.swap(result);return true;
}

inline uint32_t FontCoreForGlow(uint32_t offset) {
    return offset==93772084u ? 93705396u : 0;
}

// Only the proven active Standard pair. Its authored red halo/alpha stays in
// place; only monochrome cream-core cells get the paired vector coverage.
// Palette quantization makes intermediate color interpolation an approximation.
inline bool ReconstructFontGlow(const hd::Asset& asset, std::span<const uint8_t> glow,
                                std::span<const uint8_t> regular,
                                std::vector<uint8_t>& output) {
    const uint32_t core_offset=FontCoreForGlow(asset.offset);
    const auto* font=FindFontCells(core_offset);
    if(!font || asset.width!=font->width || asset.height!=font->height ||
       regular.size()!=uint64_t(asset.width)*asset.height*4 || glow.size()!=regular.size())return false;
    hd::Asset core_asset=asset;core_asset.offset=core_offset;
    std::vector<uint8_t> core,old_core=Upscale4x(asset.width,asset.height,{regular.begin(),regular.end()});
    if(old_core.empty() || !ReconstructFont(core_asset,regular,core))return false;
    auto result=Upscale4x(asset.width,asset.height,{glow.begin(),glow.end()});
    if(result.empty())return false;
    unsigned accepted=0;
    for(const auto& cell:font->cells) {
        std::array<uint8_t,3> ink{},halo{},halo_max{};bool has_ink=false,has_halo=false,valid=true;
        for(unsigned y=unsigned(std::floor(cell.y0));y<unsigned(std::ceil(cell.y1));++y)
          for(unsigned x=unsigned(std::floor(cell.x0));x<unsigned(std::ceil(cell.x1));++x) {
            const size_t i=(size_t(y)*asset.width+x)*4;
            const std::array<uint8_t,3> rgb{regular[i],regular[i+1],regular[i+2]};
            const std::array<uint8_t,3> g{glow[i],glow[i+1],glow[i+2]};
            if(regular[i+3]) {
                if(!has_ink){ink=rgb;has_ink=true;}
                valid &= rgb==ink && ink[0]==ink[1] && ink[1]==ink[2] && glow[i+3]==255;
                if(regular[i+3]==255)valid &= g==ink;
            } else if(glow[i+3]>=16) {
                if(!has_halo){halo=halo_max=g;has_halo=true;}
                for(unsigned c=0;c<3;++c){halo[c]=std::min(halo[c],g[c]);halo_max[c]=std::max(halo_max[c],g[c]);}
            }
        }
        // This pinned P8 pair has up to four levels of palette contamination
        // at the halo/core boundary; larger color variation is not this proof.
        for(unsigned c=0;c<3;++c)valid &= halo_max[c]-halo[c]<=4;
        if(!valid || !has_ink || !has_halo)continue;
        ++accepted;
        for(unsigned y=unsigned(cell.y0*4);y<unsigned(cell.y1*4);++y)
          for(unsigned x=unsigned(cell.x0*4);x<unsigned(cell.x1*4);++x) {
            const size_t i=(size_t(y)*asset.width*4+x)*4;
            if(!old_core[i+3] && !core[i+3])continue;
            for(unsigned c=0;c<3;++c)
                result[i+c]=result[i+3] ? detail::Byte(halo[c]+(float(ink[c])-halo[c])*core[i+3]/255.f) : 0;
        }
    }
    if(!accepted)return false;
    output.swap(result);return true;
}
} // namespace darkwatch::hd_ui
