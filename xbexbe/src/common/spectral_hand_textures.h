#pragma once
#include "gameplay_textures.h"
#include <cmath>
#include <limits>

namespace darkwatch {
// Only the locally derived hand atlas can match these aliases. The optional
// pack's shared NPC body texture is loaded as a source, never modified in place.
// Open runs at initialization; replacement/cache access belongs to the render thread.
class SpectralHandTextures {
    struct Alias { uint32_t width, height, levels, format, bytes, palette; uint64_t corrected, original; };
    struct Pair { std::array<float,8> uv; };
    struct Rect { float x0,y0,x1,y1; };
    struct RGB { float b=0,g=0,r=0; };
    struct Sample { std::array<uint32_t,4> index; std::array<float,4> weight; };
    struct Foot { uint32_t target; float weight; Sample own, other; };
    struct Pixel { uint32_t index; float divisor=0, protection=1; RGB delta; };
    std::array<Alias,2> aliases_{};
    std::array<gpu::TextureReplacement,2> cache_{};
    std::vector<Pair> pairs_;
    std::vector<Rect> protected_;
    uint64_t hash_=0;

    template<class T> static T Read(const std::vector<uint8_t>& data,size_t offset) {
        T value{}; std::memcpy(&value,data.data()+offset,sizeof(value)); return value;
    }
    static bool Dimension(uint32_t n) { return n && n<=4096 && !(n&(n-1)); }
    static Sample At(double u,double v,uint32_t w,uint32_t h) {
        const double x=u*w-.5,y=v*h-.5,fx=std::floor(x),fy=std::floor(y);
        const auto wrap=[](int64_t n,uint32_t size){return uint32_t((n%size+size)%size);};
        const uint32_t x0=wrap(int64_t(fx),w),x1=(x0+1)%w,y0=wrap(int64_t(fy),h),y1=(y0+1)%h;
        const double a=x-fx,b=y-fy;
        return {{y0*w+x0,y0*w+x1,y1*w+x0,y1*w+x1},
                {float((1-a)*(1-b)),float(a*(1-b)),float((1-a)*b),float(a*b)}};
    }
    static RGB Sampled(const std::vector<RGB>& pixels,const Sample& at) {
        RGB out;
        for(unsigned i=0;i<4;++i) {
            const auto& p=pixels[at.index[i]]; const float w=at.weight[i];
            out.b+=p.b*w; out.g+=p.g*w; out.r+=p.r*w;
        }
        return out;
    }
    float Protection(uint32_t index,uint32_t w,uint32_t h) const {
        const double u=(index%w+.5)/w,v=(index/w+.5)/h;
        double strength=1;
        for(const auto& r:protected_) {
            const double distance=512*std::max({double(r.x0)-u,u-r.x1,double(r.y0)-v,v-r.y1,0.});
            strength=std::min(strength,std::clamp((distance-1)/4,0.,1.));
            if(!strength)break;
        }
        return float(strength);
    }
    bool Repair(std::vector<uint8_t>& image,uint32_t w,uint32_t h) const {
        const uint64_t count=uint64_t(w)*h;
        if(!w||!h||w>4096||h>4096||count>16*1024*1024||image.size()!=count*4)return false;
        const double radius=std::max(2.,w/64.);
        std::vector<Foot> footprints;
        std::vector<Pixel> active;
        std::vector<uint32_t> lookup(size_t(count),UINT32_MAX);
        for(const auto& pair:pairs_)for(unsigned side=0;side<2;++side) {
            const float* a=pair.uv.data()+4*side; const float* b=pair.uv.data()+4*(1-side);
            const double ax=a[0]*double(w)-.5,ay=a[1]*double(h)-.5;
            const double dx=(a[2]-double(a[0]))*w,dy=(a[3]-double(a[1]))*h,norm=dx*dx+dy*dy;
            if(norm<1e-12)continue;
            const int left=std::max(0,int(std::floor(std::min(ax,ax+dx)-radius)));
            const int right=std::min(int(w)-1,int(std::ceil(std::max(ax,ax+dx)+radius)));
            const int top=std::max(0,int(std::floor(std::min(ay,ay+dy)-radius)));
            const int bottom=std::min(int(h)-1,int(std::ceil(std::max(ay,ay+dy)+radius)));
            for(int y=top;y<=bottom;++y)for(int x=left;x<=right;++x) {
                const double t=std::clamp(((x-ax)*dx+(y-ay)*dy)/norm,0.,1.);
                const double distance=std::hypot(x-ax-t*dx,y-ay-t*dy);
                if(distance>=radius)continue;
                // Bound malformed/overlapping descriptors before temporary storage grows.
                if(footprints.size()>=2*1024*1024)return false;
                const uint32_t index=uint32_t(y)*w+uint32_t(x);
                auto& target=lookup[index];
                if(target==UINT32_MAX) {
                    target=uint32_t(active.size()); active.push_back({index,0,Protection(index,w,h),{}});
                }
                const float weight=float(.5+.5*std::cos(3.14159265358979323846*distance/radius));
                active[target].divisor+=weight;
                footprints.push_back({target,weight,
                    At(a[0]+t*(a[2]-double(a[0])),a[1]+t*(a[3]-double(a[1])),w,h),
                    At(b[0]+t*(b[2]-double(b[0])),b[1]+t*(b[3]-double(b[1])),w,h)});
            }
        }
        if(active.empty())return true;
        std::vector<RGB> pixels(size_t(count),RGB{});
        for(size_t i=0;i<count;++i)pixels[i]={float(image[i*4]),float(image[i*4+1]),float(image[i*4+2])};
        for(auto& p:active)p.divisor=std::max(p.divisor,1.f);
        for(unsigned iteration=0;iteration<12;++iteration) {
            for(auto& p:active)p.delta={};
            for(const auto& f:footprints) {
                const auto own=Sampled(pixels,f.own),other=Sampled(pixels,f.other);
                auto& d=active[f.target].delta; const float k=.5f*f.weight;
                d.b+=(other.b-own.b)*k; d.g+=(other.g-own.g)*k; d.r+=(other.r-own.r)*k;
            }
            for(const auto& p:active) {
                auto& rgb=pixels[p.index]; const float k=.8f*p.protection/p.divisor;
                rgb.b=std::clamp(rgb.b+k*p.delta.b,0.f,255.f);
                rgb.g=std::clamp(rgb.g+k*p.delta.g,0.f,255.f);
                rgb.r=std::clamp(rgb.r+k*p.delta.r,0.f,255.f);
            }
        }
        // Preserve alpha and every texel outside the correction band exactly.
        for(const auto& p:active) {
            const auto& c=pixels[p.index]; auto* out=image.data()+size_t(p.index)*4;
            out[0]=uint8_t(std::floor(c.b+.5f)); out[1]=uint8_t(std::floor(c.g+.5f)); out[2]=uint8_t(std::floor(c.r+.5f));
        }
        return true;
    }
    bool PrepareAlias(size_t i,const GameplayTextures& gameplay) {
        if(cache_[i].id)return true;
        gpu::TextureReplacement result;
        const auto& a=aliases_[i];
        if(!gameplay.LoadByNativeHash(a.original,result)||result.mips.size()>12)return false;
        if(!Repair(result.bgra,result.width,result.height))return false;
        for(size_t l=0;l<result.mips.size();++l)
            if(!Repair(result.mips[l],std::max(result.width>>(l+1),1u),std::max(result.height>>(l+1),1u)))return false;
        const uint64_t sourceId=result.id;
        const std::array<uint64_t,3> identity{sourceId,hash_,a.corrected};
        result.id=hd::Hash({reinterpret_cast<const uint8_t*>(identity.data()),sizeof(identity)});
        if(!result.id||result.id==sourceId)result.id=sourceId==1?2:1;
        cache_[i]=std::move(result);return true;
    }
public:
    bool Open(const std::filesystem::path& path,uint64_t offset,uint32_t bytes,uint64_t expected) {
        hash_=0; pairs_.clear(); protected_.clear(); cache_={}; aliases_={};
        if(!expected||bytes<120||bytes>128*1024)return false;
        std::ifstream f(path,std::ios::binary|std::ios::ate); const auto length=f.tellg();
        if(!f||length<0||offset>uint64_t(length)||bytes>uint64_t(length)-offset)return false;
        std::vector<uint8_t> data(bytes); f.seekg(std::streamoff(offset));
        if(!f.read(reinterpret_cast<char*>(data.data()),bytes)||hd::Hash(data)!=expected||
           std::memcmp(data.data(),"DWHSEAM1",8)||Read<uint32_t>(data,8)!=1||Read<uint32_t>(data,12)!=2||
           Read<uint32_t>(data,24)!=12||Read<uint32_t>(data,28)!=0)return false;
        const auto pairs=Read<uint32_t>(data,16),rects=Read<uint32_t>(data,20);
        if(!pairs||pairs>1024||rects>2048||bytes!=120ull+uint64_t(pairs)*32+uint64_t(rects)*16||
           Read<uint64_t>(data,bytes-8)!=hd::Hash({data.data(),bytes-8}))return false;
        std::array<Alias,2> aliases;
        for(unsigned i=0;i<2;++i) {
            auto& a=aliases[i]; const size_t at=32+i*40;
            a={Read<uint32_t>(data,at),Read<uint32_t>(data,at+4),Read<uint32_t>(data,at+8),
               Read<uint32_t>(data,at+12),Read<uint32_t>(data,at+16),Read<uint32_t>(data,at+20),
               Read<uint64_t>(data,at+24),Read<uint64_t>(data,at+32)};
            if(!Dimension(a.width)||!Dimension(a.height)||a.levels!=1||a.format!=7||a.palette||
               a.bytes!=uint64_t(a.width)*a.height*4||!a.corrected||!a.original||a.corrected==a.original)return false;
        }
        if(aliases[0].corrected==aliases[1].corrected||aliases[0].original==aliases[1].original)return false;
        const auto coordinate=[](float v){return std::isfinite(v)&&v>=0&&v<=1;};
        std::vector<Pair> edges(pairs); std::vector<Rect> protectedRects(rects);
        for(unsigned i=0;i<pairs;++i) {
            std::memcpy(edges[i].uv.data(),data.data()+112+i*32,32);
            for(float v:edges[i].uv)if(!coordinate(v))return false;
        }
        for(unsigned i=0;i<rects;++i) {
            auto& r=protectedRects[i];const size_t at=112+pairs*32+i*16;
            r={Read<float>(data,at),Read<float>(data,at+4),Read<float>(data,at+8),Read<float>(data,at+12)};
            if(!coordinate(r.x0)||!coordinate(r.y0)||!coordinate(r.x1)||!coordinate(r.y1)||r.x0>r.x1||r.y0>r.y1)return false;
        }
        aliases_=aliases; pairs_=std::move(edges); protected_=std::move(protectedRects); hash_=expected; return true;
    }
    // Repair once during loading, before the first visible draw or HD toggle.
    bool Prepare(const GameplayTextures& gameplay) {
        if(!hash_||!gameplay.Available())return false;
        bool ready=true;
        for(size_t i=0;i<aliases_.size();++i) {
            try { if(!PrepareAlias(i,gameplay))ready=false; }
            catch(const std::exception&) { ready=false; }
        }
        return ready;
    }
    bool Replace(const gpu::TextureDesc& d,const uint8_t* original,uint32_t bytes,const uint32_t* palette,
                 const GameplayTextures& gameplay,gpu::TextureReplacement& out) {
        if(!hash_||!original||palette||d.linear||d.cube||d.depth!=1||!gameplay.Available())return false;
        for(size_t i=0;i<aliases_.size();++i) {
            const auto& a=aliases_[i];
            if(d.width!=a.width||d.height!=a.height||d.levels!=a.levels||d.format!=a.format||bytes!=a.bytes)continue;
            if(hd::Hash({original,bytes})!=a.corrected)continue;
            if(!PrepareAlias(i,gameplay))return false;
            out=cache_[i];return true;
        }
        return false;
    }
};
} // namespace darkwatch
