#pragma once
#include "hd_ui_assets.h"
#include "hd_ui_filter.h"
#include <imgui.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <vector>

namespace darkwatch::skin {
struct Fonts { ImFont* body = nullptr; ImFont* title = nullptr; };
namespace detail {
struct Image { unsigned width = 0, height = 0; std::vector<uint8_t> bgra; };
struct Region { int rectangle = -1; Image image; ImVec2 uv0{}, uv1{}; };
struct Letter { Region region; ImFont* font; unsigned code; float x, y, width, height, advance; bool colored; };
struct State {
    ImFontAtlas* atlas = nullptr;
    Fonts fonts;
    std::array<Region, 3> art;
    std::vector<Letter> letters;
    bool ready = false;
};
inline State state;
inline bool Read(std::ifstream& f, uint64_t offset, void* out, size_t bytes) {
    if (offset > (1ull << 30) || bytes > (64u << 20)) return false;
    f.clear(); f.seekg(std::streamoff(offset));
    return bool(f.read(static_cast<char*>(out), std::streamsize(bytes)));
}
struct Pack {
    std::ifstream file;
    std::array<hd::PackEntry, std::size(hd::kAssets)> entries{};
    bool valid = false;
    explicit Pack(const std::filesystem::path& path) : file(path, std::ios::binary) {
        hd::PackHeader h{};
        if (!Read(file, 0, &h, sizeof(h))) return;
        file.seekg(0, std::ios::end); const auto size = file.tellg();
        if (size < 0 || std::memcmp(h.magic, "DWHDU002", 8) || h.version != 2 ||
            h.count != entries.size() || h.bytes != uint64_t(size) || h.bytes > (1ull << 30) ||
            !Read(file, sizeof(h), entries.data(), sizeof(entries))) return;
        uint64_t next = sizeof(h) + sizeof(entries);
        for (size_t i = 0; i < entries.size(); ++i) {
            const auto& a = hd::kAssets[i]; const auto& e = entries[i];
            if (e.native_offset != next || !hd::Range(next, a.bytes, h.bytes)) return;
            next += a.bytes;
            if (!e.pixels_offset && !e.pixels_hash) continue;
            if (e.pixels_offset != next || !e.pixels_hash || !hd::Range(next, hd::PixelBytes(a), h.bytes)) return;
            next += hd::PixelBytes(a);
        }
        valid = next == h.bytes;
    }
};
inline bool Load(Pack& pack, std::ifstream& original, uint32_t offset, Image& out) {
    const auto it = std::find_if(std::begin(hd::kAssets), std::end(hd::kAssets),
                                 [offset](const auto& a) { return a.offset == offset; });
    if (it == std::end(hd::kAssets)) return false;
    const auto& a = *it; const auto i = size_t(it - std::begin(hd::kAssets));
    std::vector<uint8_t> native(a.bytes);
    const bool packed = pack.valid && Read(pack.file, pack.entries[i].native_offset, native.data(), native.size()) &&
                        hd::Hash(native) == a.native_hash;
    if (!packed && (!Read(original, a.offset, native.data(), native.size()) || hd::Hash(native) != a.native_hash)) return false;
    if (packed && pack.entries[i].pixels_offset) {
        std::vector<uint8_t> pixels(size_t(hd::PixelBytes(a)));
        if (Read(pack.file, pack.entries[i].pixels_offset, pixels.data(), pixels.size()) && hd::Hash(pixels) == pack.entries[i].pixels_hash) {
            out = {a.width * 4, a.height * 4, std::move(pixels)}; return true;
        }
    }
    std::vector<uint8_t> pixels;
    if (!hd_ui::DecodeNative(a.width, a.height, a.format == 11 ? 0 : a.format,
                            {native.data() + 92 + a.palette_bytes, a.payload_bytes},
                            {native.data() + 92, a.palette_bytes}, pixels)) return false;
    out = {a.width, a.height, std::move(pixels)}; return true;
}
inline uint32_t U32(const uint8_t* p) { uint32_t v; std::memcpy(&v, p, 4); return v; }
inline float Float(const uint8_t* p) { float v; std::memcpy(&v, p, 4); return v; }
struct Metadata { std::vector<uint8_t> bytes; unsigned extended = 0, count = 0; float spacing = 0; };
inline bool Meta(std::ifstream& original, uint32_t offset, uint32_t bytes, uint64_t hash, Metadata& out) {
    out.bytes.resize(bytes);
    if (!Read(original, offset, out.bytes.data(), bytes) || hd::Hash(out.bytes) != hash) return false;
    out.count = U32(out.bytes.data() + 28); out.extended = U32(out.bytes.data() + 32);
    out.spacing = Float(out.bytes.data() + 12);
    return out.count && out.count <= 128 && out.extended <= 128 &&
        292ull + out.extended * 2 + out.count * 21 + 36 == bytes && std::isfinite(out.spacing);
}
inline const uint8_t* Glyph(const Metadata& meta, unsigned code) {
    int16_t index;
    const unsigned first = U32(meta.bytes.data() + 24);
    if (code >= 128 && (code < first || code - first >= meta.extended)) return nullptr;
    const unsigned offset = code < 128 ? meta.extended + code : code - first;
    std::memcpy(&index, meta.bytes.data() + 36 + offset * 2, 2);
    return index >= 0 && unsigned(index) < meta.count ? meta.bytes.data() + 292 + meta.extended * 2 + index * 21 : nullptr;
}
// Copy the prepared native cell before removing its transparent bearings.
inline bool LetterImage(const Image& source, const uint8_t* glyph, Image& out) {
    const float x0 = Float(glyph) * source.width, y0 = Float(glyph + 4) * source.height;
    const float x1 = Float(glyph + 8) * source.width, y1 = Float(glyph + 12) * source.height;
    if (!std::isfinite(x0) || !std::isfinite(y0) || !std::isfinite(x1) || !std::isfinite(y1) ||
        x0 < 0 || y0 < 0 || x1 <= x0 || y1 <= y0 || x1 > source.width + 2 || y1 > source.height + 2) return false;
    const int left = int(std::floor(x0)), top = int(std::floor(y0));
    out.width = unsigned(std::ceil(x1) - left); out.height = unsigned(std::ceil(y1) - top);
    if (!out.width || !out.height || out.width > 512 || out.height > 512) return false;
    out.bgra.assign(size_t(out.width) * out.height * 4, 0);
    for (unsigned y = 0; y < out.height && top + y < source.height; ++y)
        for (unsigned x = 0; x < out.width && left + x < source.width; ++x)
            std::memcpy(out.bgra.data() + (y * out.width + x) * 4,
                        source.bgra.data() + ((top + y) * source.width + left + x) * 4, 4);
    return true;
}
struct Bounds { unsigned left, top, right = 0, bottom = 0; bool Empty() const { return right <= left || bottom <= top; } };
inline Bounds Ink(const Image& image, unsigned threshold) {
    Bounds b{image.width, image.height};
    for (unsigned y = 0; y < image.height; ++y) for (unsigned x = 0; x < image.width; ++x)
        if (image.bgra[(y * image.width + x) * 4 + 3] >= threshold) {
            b.left = std::min(b.left, x); b.top = std::min(b.top, y);
            b.right = std::max(b.right, x + 1); b.bottom = std::max(b.bottom, y + 1);
        }
    return b;
}
struct Metrics { float scale, bearing, padding, top; unsigned cell_height; };
inline Metrics Measure(const Image& image, const Metadata& meta, float cap) {
    Image a; if (!LetterImage(image, Glyph(meta, 'A'), a)) return {};
    const auto b = Ink(a, 16); if (b.Empty()) return {};
    return {cap / (b.bottom - b.top), float(b.left), float(b.left + a.width - b.right), float(b.top), a.height};
}
inline void Trim(Image& image, Bounds b) {
    if (b.Empty()) { image = {1, 1, std::vector<uint8_t>(4)}; return; }
    Image out{b.right - b.left, b.bottom - b.top, {}};
    out.bgra.resize(size_t(out.width) * out.height * 4);
    for (unsigned y = 0; y < out.height; ++y)
        std::memcpy(out.bgra.data() + size_t(y) * out.width * 4,
                    image.bgra.data() + (size_t(y + b.top) * image.width + b.left) * 4, size_t(out.width) * 4);
    image = std::move(out);
}
// Use the existing premultiplied reconstruction only when the prepared cell
// would have fewer than two raster samples per displayed pixel.
inline void Density(Image& image, float logical_height) {
    if (image.height >= logical_height * 2) return;
    auto pixels = hd_ui::Upscale4x(image.width, image.height, image.bgra);
    if (!pixels.empty()) image = {image.width * 4, image.height * 4, std::move(pixels)};
}
inline ImFont* Font(ImFontAtlas* atlas, float cap, const Image& image, const Metadata& meta,
                    const Image& body_image, const Metadata& body_meta) {
    // A single fallback glyph supplies ImGui's required font source. Every
    // printable glyph is replaced below with original game artwork.
    static const ImWchar fallback[]{'?', '?', 0};
    const float line_height = cap + (cap <= 24 ? 6 : 8);
    const auto metrics = Measure(image, meta, cap), body_metrics = Measure(body_image, body_meta, cap);
    ImFontConfig config; config.SizePixels = line_height; config.GlyphRanges = fallback;
    ImFont* font = atlas->AddFontDefault(&config);
    std::vector<unsigned> codes;
    for (unsigned code = 32; code < 127; ++code) codes.push_back(code);
    for (unsigned code : {0xA1u, 0xBFu, 0xC1u, 0xC9u, 0xCDu, 0xD1u, 0xD3u, 0xDAu, 0xDCu,
                          0xE1u, 0xE9u, 0xEDu, 0xF1u, 0xF3u, 0xFAu, 0xFCu}) codes.push_back(code);
    for (unsigned code : codes) {
        const unsigned mapped = (code >= 'a' && code <= 'z') || code >= 0xE0 ? code - 32 : code;
        const Metadata* selected = &meta; const Image* pixels = &image;
        const Metrics* m = &metrics;
        const uint8_t* glyph = Glyph(meta, mapped);
        if (!glyph) { selected = &body_meta; pixels = &body_image; m = &body_metrics; glyph = Glyph(body_meta, mapped); }
        if (!glyph) glyph = Glyph(body_meta, '?');
        Letter letter{}; letter.font = font; letter.code = code;
        if (!glyph || !LetterImage(*pixels, glyph, letter.region.image)) continue;
        const auto ink = Ink(letter.region.image, 1);
        letter.advance = ((Float(glyph + 16) + selected->spacing) * m->cell_height - m->padding) * m->scale;
        if (code == ' ') letter.advance = cap * .5f;
        if (!std::isfinite(letter.advance) || letter.advance <= 0 || letter.advance > cap * 4) continue;
        letter.x = ink.Empty() ? 0 : (float(ink.left) - m->bearing) * m->scale;
        letter.y = ink.Empty() ? 0 : (float(ink.top) - m->top) * m->scale + (line_height - cap) * .5f;
        letter.width = ink.Empty() ? 0 : (ink.right - ink.left) * m->scale;
        letter.height = ink.Empty() ? 0 : (ink.bottom - ink.top) * m->scale;
        Trim(letter.region.image, ink); Density(letter.region.image, letter.height);
        for (size_t i = 0; i < letter.region.image.bgra.size(); i += 4) {
            const auto* p = letter.region.image.bgra.data() + i;
            if (p[3] && (p[0] != p[1] || p[1] != p[2])) letter.colored = true;
        }
        auto& r = letter.region;
        r.rectangle = atlas->AddCustomRectFontGlyph(font, ImWchar(code), r.image.width, r.image.height, letter.advance);
        state.letters.push_back(std::move(letter));
    }
    return font;
}
inline void Arrows(ImFontAtlas* atlas, ImFont* font, float cap) {
    const unsigned side = unsigned(std::ceil(cap * 4));
    for (unsigned direction = 0; direction < 4; ++direction) {
        Letter letter{}; letter.font = font; letter.code = 0x2190 + direction;
        letter.y = 3; letter.width = letter.height = cap; letter.advance = cap + 6;
        auto& r = letter.region; r.image = {side, side, std::vector<uint8_t>(size_t(side) * side * 4)};
        // Same arrow contour as the native keycap atlas, supersampled here at
        // the host font's density; Unicode selects geometry, never another font.
        for (unsigned y = 0; y < side; ++y) for (unsigned x = 0; x < side; ++x) {
            unsigned covered = 0;
            for (unsigned sy = 0; sy < 4; ++sy) for (unsigned sx = 0; sx < 4; ++sx) {
                float px = ((x + (sx + .5f) / 4) / side - .5f) * 18;
                float py = ((y + (sy + .5f) / 4) / side - .5f) * 18;
                if (direction == 0) { const float t = px; px = -py; py = t; }
                if (direction == 2) { const float t = px; px = py; py = -t; }
                if (direction == 3) { px = -px; py = -py; }
                covered += (py >= -9 && py <= 0 && std::abs(px) <= py + 9) ||
                           (py >= 0 && py < 9 && std::abs(px) < 3);
            }
            auto* p = r.image.bgra.data() + (y * side + x) * 4;
            p[0] = p[1] = p[2] = 255; p[3] = uint8_t(covered * 255 / 16);
        }
        r.rectangle = atlas->AddCustomRectFontGlyph(font, ImWchar(letter.code), side, side, letter.advance);
        state.letters.push_back(std::move(letter));
    }
}
inline bool Ready() { return state.ready && state.atlas && ImGui::GetCurrentContext() &&
    ImGui::GetIO().Fonts == state.atlas && state.atlas->TexID; }
} // namespace detail

// Register before InitializeMenuCursor; call Finalize after that function's
// atlas build, before the renderer first uploads it. No atlas rebuild at runtime.
inline Fonts Initialize(ImFontAtlas* atlas, const std::filesystem::path& pack_path,
                        const std::filesystem::path& original_path, float body_size = 16, float title_size = 36) {
    if (!atlas || atlas->Locked || atlas->TexID || !std::isfinite(body_size) || !std::isfinite(title_size) ||
        body_size < 12 || body_size > 40 || title_size < 18 || title_size > 72) return {};
    if (detail::state.atlas == atlas && detail::state.fonts.body &&
        atlas->Fonts.contains(detail::state.fonts.body)) return detail::state.fonts;
    detail::state = {};
    detail::Pack pack(pack_path); std::ifstream original(original_path, std::ios::binary);
    detail::Image body, title;
    detail::Metadata body_meta, title_meta;
    if (!detail::Load(pack, original, 94020788, body) || !detail::Load(pack, original, 93423668, title) ||
        !detail::Meta(original, 94200708, 2806, 0xA04471FF903BEAD8ull, body_meta) ||
        !detail::Meta(original, 93493633, 937, 0x38B7E4E87907F30Eull, title_meta)) return {};
    for (auto* image : {&body, &title}) if (image->width == 256) {
        auto large = hd_ui::Upscale4x(image->width, image->height, image->bgra);
        if (large.empty()) return {};
        *image = {image->width * 4, image->height * 4, std::move(large)};
    }
    constexpr uint32_t art[]{101214580, 101206260, 101924596};
    for (size_t i = 0; i < std::size(art); ++i)
        if (!detail::Load(pack, original, art[i], detail::state.art[i].image)) return {};
    detail::state.atlas = atlas;
    // ImGui's font-only width heuristic ignores these larger artwork cells.
    atlas->TexDesiredWidth = std::max(atlas->TexDesiredWidth, 4096);
    for (auto& r : detail::state.art) r.rectangle = atlas->AddCustomRectRegular(r.image.width, r.image.height);
    detail::state.fonts.body = detail::Font(atlas, body_size, body, body_meta, body, body_meta);
    detail::state.fonts.title = detail::Font(atlas, title_size, title, title_meta, body, body_meta);
    detail::Arrows(atlas, detail::state.fonts.body, body_size);
    return detail::state.fonts;
}

inline bool Finalize() {
    using namespace detail;
    auto* atlas = state.atlas;
    if (!atlas || atlas->Locked || atlas->TexID) return false;
    unsigned char* pixels = nullptr; int width = 0, height = 0;
    atlas->GetTexDataAsRGBA32(&pixels, &width, &height);
    if (!pixels) return false;
    auto fill = [&](Region& r) {
        if (r.rectangle < 0 || r.rectangle >= atlas->CustomRects.Size) return false;
        const auto* rect = atlas->GetCustomRectByIndex(r.rectangle);
        if (!rect->IsPacked() || rect->X + r.image.width > unsigned(width) || rect->Y + r.image.height > unsigned(height)) return false;
        for (unsigned y = 0; y < r.image.height; ++y) for (unsigned x = 0; x < r.image.width; ++x) {
            const auto* s = r.image.bgra.data() + (y * r.image.width + x) * 4;
            auto* d = pixels + ((rect->Y + y) * width + rect->X + x) * 4;
            d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; d[3] = s[3];
        }
        atlas->CalcCustomRectUV(rect, &r.uv0, &r.uv1); return true;
    };
    for (auto& r : state.art) if (!fill(r)) return false;
    for (auto& letter : state.letters) {
        if (!fill(letter.region)) return false;
        auto* glyph = const_cast<ImFontGlyph*>(letter.font->FindGlyphNoFallback(ImWchar(letter.code)));
        if (!glyph) return false;
        glyph->X0 = letter.x; glyph->Y0 = letter.y;
        glyph->X1 = letter.x + letter.width; glyph->Y1 = letter.y + letter.height;
        glyph->AdvanceX = letter.advance; glyph->Colored = letter.colored;
        letter.font->DirtyLookupTables = true;
    }
    for (auto* font : {state.fonts.body, state.fonts.title}) { font->FallbackChar = '?'; font->BuildLookupTable(); }
    atlas->TexPixelsUseColors = true; state.ready = true; return true;
}

inline void Frame(ImDrawList* draw, ImVec2 pos, ImVec2 size) {
    if (!draw || size.x <= 0 || size.y <= 0) return;
    if (!detail::Ready()) { draw->AddRectFilled(pos, {pos.x + size.x, pos.y + size.y}, IM_COL32(8, 8, 8, 245)); return; }
    const auto& r = detail::state.art[0];
    const float natural_height = size.x * r.image.height / r.image.width;
    const float fixed_scale = std::min(1.f, size.y / (natural_height * .47f));
    const float top = natural_height * .14f * fixed_scale, bottom = natural_height * .33f * fixed_scale;
    constexpr float source[]{0, .14f, .67f, 1};
    const float target[]{0, top, size.y - bottom, size.y};
    // Cover the original scene only inside the panel, leaving its authored
    // transparent exterior and skull silhouette intact.
    draw->AddRectFilled({pos.x + size.x * .07f, pos.y + top},
                        {pos.x + size.x * .97f, pos.y + size.y - bottom * .36f}, IM_COL32(0, 0, 0, 255));
    for (unsigned i = 0; i < 3; ++i) draw->AddImage(detail::state.atlas->TexID,
        {pos.x, pos.y + target[i]}, {pos.x + size.x, pos.y + target[i + 1]},
        {r.uv0.x, r.uv0.y + (r.uv1.y - r.uv0.y) * source[i]},
        {r.uv1.x, r.uv0.y + (r.uv1.y - r.uv0.y) * source[i + 1]});
}
inline void Row(ImDrawList* draw, ImVec2 a, ImVec2 b, bool selected) {
    if (!draw || b.x <= a.x || b.y <= a.y) return;
    if (!detail::Ready()) { draw->AddRectFilled(a, b, selected ? IM_COL32(115, 5, 8, 255) : IM_COL32(16, 16, 16, 255)); return; }
    const auto& r = detail::state.art[selected ? 2 : 1];
    draw->AddImage(detail::state.atlas->TexID, a, b, r.uv0, r.uv1);
}
} // namespace darkwatch::skin
