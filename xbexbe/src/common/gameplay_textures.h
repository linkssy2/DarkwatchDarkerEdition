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
    uint32_t pack_revision = 1;
};
#include "gameplay_texture_assets.h"
struct GameplayAlias {
    uint64_t target_native_hash;
    uint32_t width, height, levels, format, bytes;
    uint64_t native_hash;
};
#include "gameplay_texture_aliases.h"

// Index metadata only: decoded pack pixels load when a GPU upload needs them.
class GameplayTextures {
    std::filesystem::path directory_;
    std::unordered_multimap<uint64_t, const GameplayAsset*> index_;
    struct AliasMatch { const GameplayAlias* identity; const GameplayAsset* asset; };
    std::unordered_multimap<uint64_t, AliasMatch> aliases_;
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
        // Pack v1 mapped grille RGB to six blood decals; retain originals for these exact files.
        switch (hash) {
        case 0x1df864062beaf83full: case 0x2e0cf7a8c407e4ccull: // bloodstain, base
        case 0xd31ccba86361254bull: case 0xf696dd35268b687full: // bloodstain, distance
        case 0x56fc1dd1a8f49fe4ull: case 0x605d2900fc98b8aeull: // arterial, base
        case 0xc21786724088f17full: case 0xeb211f2e428b2f0dull: // arterial, distance
        case 0x3c8432ed906cef7dull: case 0xbc1dee29427f24b4ull: // blood, base
        case 0x7c7dc03b58236015ull: case 0x197dd929ef18d104ull: // blood, distance
            return false;
        }
        if (data[7] == '1') {
            const size_t native_bytes = size_t(a.palette) + a.bytes;
            if (hd::Hash({data.data()+24,native_bytes}) != a.native_hash ||
                (original && ((a.palette && (!palette || std::memcmp(palette,data.data()+24,a.palette))) ||
                 std::memcmp(original,data.data()+24+a.palette,a.bytes)))) return false;
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
    // The menu needs only its few allowlisted materials. Validate those files
    // with the normal loader, without scanning the entire pack a second time.
    static bool LoadPreviewByNativeHash(const std::filesystem::path& directory,
                                       uint64_t hash, gpu::TextureReplacement& out) {
        GameplayTextures preview;
        preview.directory_ = directory;
        for (const auto& asset : kGameplayAssets)
            if (asset.native_hash == hash && preview.Load(asset, nullptr, nullptr, out)) return true;
        return false;
    }
    void Open(const std::filesystem::path& directory) {
        directory_=directory; index_.clear(); aliases_.clear();
        std::array<size_t,3> required{}, present{};
        for(const auto& a:kGameplayAssets) {
            if (a.pack_revision < 1 || a.pack_revision > required.size()) { index_.clear(); return; }
            ++required[a.pack_revision - 1];
            // A released generation remains valid when all later additions are absent.
            if (a.pack_revision > 1) {
                std::error_code error;
                const bool exists = std::filesystem::exists(directory/a.file, error);
                if (error) { index_.clear(); return; }
                if (!exists) continue;
            }
            std::ifstream file(directory/a.file, std::ios::binary | std::ios::ate);
            const auto length = file.tellg();
            std::array<uint8_t,32> header{}; size_t pixels = 0;
            file.seekg(0);
            // Installation completeness is checked once; pixel checksums stay lazy.
            if (!file.read(reinterpret_cast<char*>(header.data()), header.size()) || length < 0 ||
                !Header(a, header, uint64_t(length), pixels)) { index_.clear(); return; }
            index_.emplace(Key(a.width,a.height,a.format,a.levels),&a);
            ++present[a.pack_revision - 1];
        }
        if (!required[0]) { index_.clear(); return; }
        bool absent = false;
        for (size_t revision = 0; revision < required.size(); ++revision) {
            if (!present[revision]) absent = true;
            else if (absent || present[revision] != required[revision]) {
                index_.clear(); return;
            }
        }
        // Co-op can load the authored smaller dictionary for the same material.
        for (const auto& alias : kGameplayAliases)
            for (const auto& entry : index_)
                if (entry.second->native_hash == alias.target_native_hash) {
                    aliases_.emplace(Key(alias.width,alias.height,alias.format,alias.levels),
                                     AliasMatch{&alias,entry.second});
                    break;
                }
    }
    bool Available() const { return !index_.empty(); }
    // Derived hand textures reuse the verified optional pack before local seam repair.
    bool LoadByNativeHash(uint64_t hash, gpu::TextureReplacement& out) const {
        if (!Available()) return false;
        for (const auto& a : kGameplayAssets)
            if (a.native_hash == hash && Load(a, nullptr, nullptr, out)) return true;
        return false;
    }
    bool Replace(const gpu::TextureDesc& d, const uint8_t* original, uint32_t bytes,
                 const uint32_t* palette, gpu::TextureReplacement& out) const {
        if(!original || d.linear || d.cube || d.depth!=1 || (d.format==11 && !palette)) return false;
        const auto [begin,end]=index_.equal_range(Key(d.width,d.height,d.format,d.levels));
        const auto [alias_begin,alias_end]=aliases_.equal_range(Key(d.width,d.height,d.format,d.levels));
        if(begin==end && alias_begin==alias_end) return false;
        uint64_t hash=14695981039346656037ull;
        if(d.format==11) for(uint8_t b:std::span(reinterpret_cast<const uint8_t*>(palette),1024)) hash=(hash^b)*1099511628211ull;
        for(uint8_t b:std::span(original,bytes)) hash=(hash^b)*1099511628211ull;
        for(auto it=begin;it!=end;++it) {
            const auto& a=*it->second;
            if(bytes==a.bytes && hash==a.native_hash && Load(a,original,palette,out)) return true;
        }
        for(auto it=alias_begin;it!=alias_end;++it) {
            const auto& match=it->second;
            if(bytes==match.identity->bytes && hash==match.identity->native_hash &&
               Load(*match.asset,nullptr,nullptr,out)) return true;
        }
        return false;
    }
};
} // namespace darkwatch
