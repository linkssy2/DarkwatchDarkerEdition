#pragma once
#include "hd_ui_pack.h"
#include "gpu/ext.h"
#include <array>
#include <filesystem>
#include <fstream>
#include <algorithm>
#include <unordered_map>

namespace darkwatch {
struct GameplayAsset {
    const char* file;
    uint32_t width, height, levels, format, bytes, palette;
    uint32_t hd_width, hd_height, hd_levels;
    uint64_t native_hash;
};
#include "gameplay_texture_assets.h"

// Index metadata only: decoded pack pixels load when a GPU upload needs them.
class GameplayTextures {
    std::filesystem::path directory_;
    std::unordered_multimap<uint64_t, const GameplayAsset*> index_;
    static uint64_t Key(uint32_t width, uint32_t height, uint32_t format, uint32_t levels) {
        return uint64_t(width) | uint64_t(height)<<16 | uint64_t(format)<<32 | uint64_t(levels)<<40;
    }
    static bool Header(const GameplayAsset& a, std::span<const uint8_t> data,
                       uint64_t length, size_t& pixels) {
        if (data.size() < 32 || length > 128 * 1024 * 1024) return false;
        uint32_t header[4]{};
        std::memcpy(header, data.data() + 8, sizeof(header));
        if (header[0] != a.hd_width || header[1] != a.hd_height ||
            header[2] != a.hd_levels || header[3] != a.bytes || !a.hd_levels || a.hd_levels > 32) return false;
        if (!std::memcmp(data.data(), "DWGAME02", 8)) {
            uint64_t native_hash = 0;
            std::memcpy(&native_hash, data.data() + 24, 8);
            if (native_hash != a.native_hash) return false;
            pixels = 32;
        } else if (!std::memcmp(data.data(), "DWGAME01", 8)) {
            pixels = 24 + size_t(a.palette) + a.bytes;
        } else return false;
        uint64_t expected = pixels + 8;
        for (uint32_t l = 0; l < a.hd_levels; ++l)
            expected += uint64_t(std::max(a.hd_width >> l, 1u)) * std::max(a.hd_height >> l, 1u) * 4;
        return expected == length;
    }
    bool Load(const GameplayAsset& a, const uint8_t* original, const uint32_t* palette,
              gpu::TextureReplacement& result) const {
        std::ifstream f(directory_ / a.file, std::ios::binary | std::ios::ate);
        const auto length = f.tellg();
        if (!f || length < 32 || length > 128 * 1024 * 1024) return false;
        std::vector<uint8_t> data(static_cast<size_t>(length));
        f.seekg(0);
        if (!f.read(reinterpret_cast<char*>(data.data()), std::streamsize(data.size()))) return false;
        size_t offset = 0;
        if (!Header(a, data, data.size(), offset)) return false;
        uint64_t hash = 0;
        std::memcpy(&hash, data.data() + data.size() - 8, 8);
        if (hash != hd::Hash({data.data(), data.size()-8})) return false;
        if (data[7] == '1') {
            const size_t native_bytes = size_t(a.palette) + a.bytes;
            if (hd::Hash({data.data()+24,native_bytes}) != a.native_hash ||
                (a.palette && std::memcmp(palette,data.data()+24,a.palette)) ||
                std::memcmp(original,data.data()+24+a.palette,a.bytes)) return false;
        }
        const auto w = a.hd_width, h = a.hd_height, levels = a.hd_levels;
        gpu::TextureReplacement replacement;
        replacement.id=hash; replacement.width=w; replacement.height=h;
        for(uint32_t l=0;l<levels;++l) {
            const size_t count=size_t(std::max(w>>l,1u))*std::max(h>>l,1u)*4;
            if (!hd::Range(offset,count,data.size()-8)) return false;
            std::vector<uint8_t> pixels(data.begin()+offset,data.begin()+offset+count);
            if (!l) replacement.bgra=std::move(pixels);
            else replacement.mips.push_back(std::move(pixels));
            offset+=count;
        }
        if(offset!=data.size()-8) return false;
        result=std::move(replacement);
        return true;
    }
public:
    void Open(const std::filesystem::path& directory) {
        directory_=directory; index_.clear();
        for(const auto& a:kGameplayAssets) {
            std::ifstream file(directory/a.file, std::ios::binary | std::ios::ate);
            const auto length = file.tellg();
            std::array<uint8_t,32> header{}; size_t pixels = 0;
            file.seekg(0);
            // Installation completeness is checked once; pixel checksums stay lazy.
            if (!file.read(reinterpret_cast<char*>(header.data()), header.size()) || length < 0 ||
                !Header(a, header, uint64_t(length), pixels)) { index_.clear(); return; }
            index_.emplace(Key(a.width,a.height,a.format,a.levels),&a);
        }
    }
    bool Available() const { return index_.size() == std::size(kGameplayAssets); }
    bool Replace(const gpu::TextureDesc& d, const uint8_t* original, uint32_t bytes,
                 const uint32_t* palette, gpu::TextureReplacement& out) const {
        if(!original || d.linear || d.cube || d.depth!=1 || (d.format==11 && !palette)) return false;
        const auto [begin,end]=index_.equal_range(Key(d.width,d.height,d.format,d.levels));
        if(begin==end) return false;
        uint64_t hash=14695981039346656037ull;
        if(d.format==11) for(uint8_t b:std::span(reinterpret_cast<const uint8_t*>(palette),1024)) hash=(hash^b)*1099511628211ull;
        for(uint8_t b:std::span(original,bytes)) hash=(hash^b)*1099511628211ull;
        for(auto it=begin;it!=end;++it) {
            const auto& a=*it->second;
            if(bytes==a.bytes && hash==a.native_hash && Load(a,original,palette,out)) return true;
        }
        return false;
    }
};
} // namespace darkwatch
