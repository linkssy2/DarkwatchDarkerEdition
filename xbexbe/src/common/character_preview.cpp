#include "character_preview.h"
#include "gameplay_textures.h"
#include "hd_ui_filter.h"
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <numeric>

namespace darkwatch::preview {
namespace {
constexpr uint32_t kMarker = 0x44575000, kSide = 512;
constexpr size_t kFileLimit = 96u << 20, kAtlasPixelLimit = 8u << 20;
struct Vec3 { float x, y, z; };
struct Pose { Vec3 position, normal; };
struct Vertex { ImVec2 uv; uint32_t color; };
struct Triangle { uint32_t a, b, c, texture, color; };
static_assert(sizeof(Pose) == 24 && sizeof(Vertex) == 12 && sizeof(Triangle) == 20);
struct Image { uint32_t width = 0, height = 0; std::vector<uint8_t> bgra; int cell = -1; };
struct Texture { uint64_t native_hash = 0; Image native, hd; };
struct Projected { ImVec2 position; float depth, light; };
struct Model {
    float duration = 0, center_y = 0, height = 0, radius = 0;
    uint32_t frame_count = 0;
    std::vector<Texture> textures;
    std::vector<Vertex> vertices;
    std::vector<Triangle> triangles;
    std::vector<Pose> poses;
    std::vector<Projected> projected;
    std::vector<uint32_t> order;
};
struct State { ImFontAtlas* atlas = nullptr; std::array<Model, settings::kCharacterCount> models; bool ready = false; };
State state;
struct Reader {
    std::span<const uint8_t> bytes;
    size_t position = 0;
    bool good = true;
    template<class T> T Value() {
        T result{};
        if (!good || position > bytes.size() || sizeof(T) > bytes.size() - position) { good = false; return result; }
        std::memcpy(&result, bytes.data() + position, sizeof(T)); position += sizeof(T); return result;
    }
    std::span<const uint8_t> Take(size_t count) {
        if (!good || position > bytes.size() || count > bytes.size() - position) { good = false; return {}; }
        const auto result = bytes.subspan(position, count); position += count; return result;
    }
};
bool Finite(float v) { return std::isfinite(v); }
bool Valid(const Vec3& v, float bound) { return Finite(v.x) && Finite(v.y) && Finite(v.z) &&
    std::abs(v.x) <= bound && std::abs(v.y) <= bound && std::abs(v.z) <= bound; }

// Box reduction preserves straight alpha without pulling dark RGB into edges.
void Reduce(Image& image) {
    if (image.width <= kSide && image.height <= kSide) return;
    const uint32_t divisor = std::max((image.width + kSide - 1) / kSide, (image.height + kSide - 1) / kSide);
    Image reduced{(image.width + divisor - 1) / divisor, (image.height + divisor - 1) / divisor};
    reduced.bgra.resize(size_t(reduced.width) * reduced.height * 4);
    for (uint32_t y = 0; y < reduced.height; ++y) for (uint32_t x = 0; x < reduced.width; ++x) {
        uint64_t sums[4]{}, count = 0;
        for (uint32_t sy = y * divisor; sy < std::min((y + 1) * divisor, image.height); ++sy)
            for (uint32_t sx = x * divisor; sx < std::min((x + 1) * divisor, image.width); ++sx) {
                const auto* p = image.bgra.data() + (size_t(sy) * image.width + sx) * 4;
                for (unsigned lane = 0; lane < 3; ++lane) sums[lane] += uint64_t(p[lane]) * p[3];
                sums[3] += p[3]; ++count;
            }
        auto* p = reduced.bgra.data() + (size_t(y) * reduced.width + x) * 4;
        for (unsigned lane = 0; lane < 3; ++lane) p[lane] = sums[3] ? uint8_t((sums[lane] + sums[3] / 2) / sums[3]) : 0;
        p[3] = uint8_t((sums[3] + count / 2) / count);
    }
    image = std::move(reduced);
}
bool Load(std::span<const uint8_t> bytes, std::array<Model, settings::kCharacterCount>& models) {
    if (bytes.size() < 24 || bytes.size() > kFileLimit) return false;
    uint64_t stored; std::memcpy(&stored, bytes.data() + bytes.size() - 8, 8);
    if (hd::Hash(bytes.first(bytes.size() - 8)) != stored || std::memcmp(bytes.data(), "DWCP0002", 8)) return false;
    Reader reader{bytes.first(bytes.size() - 8), 8};
    if (reader.Value<uint32_t>() != 2 || reader.Value<uint32_t>() != models.size()) return false;
    size_t atlas_pixels = 0;
    for (uint32_t id = 0; id < models.size(); ++id) {
        Model& model = models[id];
        if (reader.Value<uint32_t>() != id) return false;
        const auto vertices = reader.Value<uint32_t>(), triangles = reader.Value<uint32_t>(), textures = reader.Value<uint32_t>();
        model.frame_count = reader.Value<uint32_t>(); model.duration = reader.Value<float>();
        if (!reader.good || !vertices || vertices > 12000 || !triangles || triangles > 24000 ||
            !textures || textures > 16 || model.frame_count < 2 || model.frame_count > 120 ||
            !Finite(model.duration) || model.duration < .1f || model.duration > 10) return false;
        model.textures.resize(textures);
        for (auto& texture : model.textures) {
            auto& image = texture.native;
            image.width = reader.Value<uint32_t>(); image.height = reader.Value<uint32_t>();
            const auto format = reader.Value<uint32_t>(), palette_bytes = reader.Value<uint32_t>(), payload_bytes = reader.Value<uint32_t>();
            texture.native_hash = reader.Value<uint64_t>();
            if (!reader.good || !image.width || image.width > 4096 || !image.height || image.height > 4096 ||
                palette_bytes > 1024 || payload_bytes > (16u << 20)) return false;
            const auto palette = reader.Take(palette_bytes), payload = reader.Take(payload_bytes);
            if (!reader.good || !hd_ui::DecodeNative(image.width, image.height, format, payload, palette, image.bgra)) return false;
            Reduce(image); atlas_pixels += size_t(image.width + 4) * (image.height + 4);
            if (atlas_pixels > kAtlasPixelLimit) return false;
        }
        const size_t needed = size_t(vertices) * sizeof(Vertex) + size_t(triangles) * sizeof(Triangle) +
                              size_t(vertices) * model.frame_count * sizeof(Pose);
        if (needed > reader.bytes.size() - reader.position) return false;
        model.vertices.resize(vertices); model.triangles.resize(triangles); model.poses.resize(size_t(vertices) * model.frame_count);
        for (auto& vertex : model.vertices) {
            vertex = reader.Value<Vertex>();
            if (!Finite(vertex.uv.x) || !Finite(vertex.uv.y) || vertex.uv.x < -.0001f || vertex.uv.x > 1.0001f ||
                vertex.uv.y < -.0001f || vertex.uv.y > 1.0001f) return false;
            vertex.uv.x = std::clamp(vertex.uv.x, 0.f, 1.f); vertex.uv.y = std::clamp(vertex.uv.y, 0.f, 1.f);
        }
        for (auto& triangle : model.triangles) {
            triangle = reader.Value<Triangle>();
            if (triangle.a >= vertices || triangle.b >= vertices || triangle.c >= vertices || triangle.texture >= textures) return false;
        }
        float low = 100, high = -100;
        for (auto& pose : model.poses) {
            pose = reader.Value<Pose>();
            if (!Valid(pose.position, 100) || !Valid(pose.normal, 2)) return false;
            low = std::min(low, pose.position.y); high = std::max(high, pose.position.y);
            model.radius = std::max(model.radius, std::hypot(pose.position.x, pose.position.z));
        }
        model.height = high - low; model.center_y = (high + low) * .5f;
        if (model.height < .01f || model.radius < .001f || !reader.good) return false;
        model.projected.resize(vertices); model.order.resize(triangles);
        std::iota(model.order.begin(), model.order.end(), 0);
    }
    return reader.good && reader.position == reader.bytes.size();
}
bool CellValid(ImFontAtlas* atlas, const Image& image) {
    if (image.cell < 0 || image.cell >= atlas->CustomRects.Size) return false;
    const auto* cell = atlas->GetCustomRectByIndex(image.cell);
    return cell->GlyphID == kMarker + uint32_t(image.cell) && cell->Width == image.width + 4 && cell->Height == image.height + 4;
}
bool Owned() {
    if (!state.atlas || !ImGui::GetCurrentContext() || ImGui::GetIO().Fonts != state.atlas) return false;
    for (const auto& model : state.models) for (const auto& texture : model.textures) {
        if (!CellValid(state.atlas, texture.native) || (texture.hd.cell >= 0 && !CellValid(state.atlas, texture.hd))) return false;
    }
    return !state.models[0].textures.empty();
}
uint32_t Color(uint32_t vertex, uint32_t material, float light) {
    uint32_t result = 0;
    for (unsigned lane = 0; lane < 4; ++lane) {
        // These lit character meshes store ambient/prelight (usually black),
        // not albedo, in vertex RGB. Supply neutral preview light while retaining
        // brighter authored channels, including the spectral eye tint.
        const float prelight = float((vertex >> (lane * 8)) & 255) / 255.f;
        const float tint = lane == 3 ? prelight : std::max(prelight, light);
        const float value = tint * float((material >> (lane * 8)) & 255);
        result |= uint32_t(std::clamp(value + .5f, 0.f, 255.f)) << (lane * 8);
    }
    return result;
}
} // namespace

void Reset() { state = {}; }
bool Initialize(ImFontAtlas* atlas, const std::filesystem::path& path, const std::filesystem::path& hd_directory) {
    if (state.atlas == atlas && Owned()) return true;
    if (!atlas || atlas->Locked || atlas->TexID) return false;
    Reset();
    try {
        std::ifstream file(path, std::ios::binary | std::ios::ate);
        const auto length = file.tellg();
        if (!file || length < 24 || length > kFileLimit) return false;
        std::vector<uint8_t> bytes(static_cast<size_t>(length)); file.seekg(0);
        std::array<Model, settings::kCharacterCount> models;
        if (!file.read(reinterpret_cast<char*>(bytes.data()), bytes.size()) || !Load(bytes, models)) return false;
        size_t pixels = 0;
        for (auto& model : models) for (auto& texture : model.textures) {
            gpu::TextureReplacement replacement;
            if (!hd_directory.empty() && texture.native_hash &&
                GameplayTextures::LoadPreviewByNativeHash(hd_directory, texture.native_hash, replacement)) {
                texture.hd = {replacement.width, replacement.height, std::move(replacement.bgra)};
                Reduce(texture.hd);
            }
            pixels += size_t(texture.native.width + 4) * (texture.native.height + 4);
            if (!texture.hd.bgra.empty()) pixels += size_t(texture.hd.width + 4) * (texture.hd.height + 4);
            if (pixels > kAtlasPixelLimit) return false;
        }
        state.models = std::move(models); state.atlas = atlas;
        atlas->TexDesiredWidth = std::max(atlas->TexDesiredWidth, 4096);
        for (auto& model : state.models) for (auto& texture : model.textures) for (auto* image : {&texture.native, &texture.hd}) {
            if (image->bgra.empty()) continue;
            image->cell = atlas->AddCustomRectRegular(image->width + 4, image->height + 4);
            atlas->GetCustomRectByIndex(image->cell)->GlyphID = kMarker + uint32_t(image->cell);
        }
        return true;
    } catch (const std::exception&) { Reset(); return false; }
}
bool Finalize() {
    if (!Owned() || state.atlas->Locked || state.atlas->TexID) return false;
    unsigned char* pixels = nullptr; int width = 0, height = 0;
    state.atlas->GetTexDataAsRGBA32(&pixels, &width, &height);
    if (!pixels || width <= 0 || height <= 0) return false;
    for (auto& model : state.models) for (auto& texture : model.textures) for (auto* image : {&texture.native, &texture.hd}) {
        if (image->cell < 0) continue;
        const auto* cell = state.atlas->GetCustomRectByIndex(image->cell);
        if (!cell->IsPacked() || cell->X + cell->Width > width || cell->Y + cell->Height > height) return false;
        for (unsigned y = 0; y < cell->Height; ++y) for (unsigned x = 0; x < cell->Width; ++x) {
            const auto sx = unsigned(std::clamp(int(x) - 2, 0, int(image->width) - 1));
            const auto sy = unsigned(std::clamp(int(y) - 2, 0, int(image->height) - 1));
            const auto* s = image->bgra.data() + (size_t(sy) * image->width + sx) * 4;
            auto* d = pixels + (size_t(cell->Y + y) * width + cell->X + x) * 4;
            d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; d[3] = s[3];
        }
    }
    state.atlas->TexPixelsUseColors = true; state.ready = true; return true;
}
bool Draw(settings::Character character, ImVec2 minimum, ImVec2 maximum, double elapsed_seconds, bool hd_enabled) {
    const auto id = unsigned(character);
    if (!state.ready || !Owned() || !state.atlas->TexID || id >= state.models.size() ||
        !Finite(minimum.x) || !Finite(minimum.y) || !Finite(maximum.x) || !Finite(maximum.y) ||
        maximum.x <= minimum.x || maximum.y <= minimum.y || !std::isfinite(elapsed_seconds)) return false;
    Model& model = state.models[id];
    const double time = std::max(0., elapsed_seconds);
    const float sample = float(std::fmod(time, model.duration) * model.frame_count / model.duration);
    const auto first = std::min(uint32_t(sample), model.frame_count - 1), second = (first + 1) % model.frame_count;
    const float blend = sample - first;
    const float angle = float(std::fmod(time, 20.) * 6.283185307179586 / 20.);
    const float cosine = std::cos(angle), sine = std::sin(angle);
    const float scale = .9f * std::min((maximum.x - minimum.x) / (2 * model.radius), (maximum.y - minimum.y) / model.height);
    const ImVec2 center{(minimum.x + maximum.x) * .5f, (minimum.y + maximum.y) * .5f};
    for (size_t i = 0; i < model.vertices.size(); ++i) {
        const auto& a = model.poses[size_t(first) * model.vertices.size() + i];
        const auto& b = model.poses[size_t(second) * model.vertices.size() + i];
        auto lerp = [blend](float x, float y) { return x + (y - x) * blend; };
        const float x = lerp(a.position.x, b.position.x), y = lerp(a.position.y, b.position.y), z = lerp(a.position.z, b.position.z);
        const float nx = lerp(a.normal.x, b.normal.x), ny = lerp(a.normal.y, b.normal.y), nz = lerp(a.normal.z, b.normal.z);
        const float normal_length = std::sqrt(nx * nx + ny * ny + nz * nz);
        const float facing = normal_length > .00001f ? ((nx * cosine + nz * sine) * -.3f + ny * .5f + (-nx * sine + nz * cosine) * .8124f) / normal_length : 0;
        model.projected[i] = {{center.x + (x * cosine + z * sine) * scale, center.y - (y - model.center_y) * scale},
                              -x * sine + z * cosine, .72f + .28f * std::max(0.f, facing)};
    }
    auto depth = [&](uint32_t i) { const auto& t = model.triangles[i]; return model.projected[t.a].depth + model.projected[t.b].depth + model.projected[t.c].depth; };
    std::sort(model.order.begin(), model.order.end(), [&](uint32_t a, uint32_t b) { const auto da = depth(a), db = depth(b); return da == db ? a < b : da < db; });
    auto* draw = ImGui::GetWindowDrawList();
    draw->PushClipRect(minimum, maximum, true); draw->PushTextureID(state.atlas->TexID);
    for (const auto index : model.order) {
        const auto& triangle = model.triangles[index]; const auto& texture = model.textures[triangle.texture];
        const auto& image = hd_enabled && texture.hd.cell >= 0 ? texture.hd : texture.native;
        const auto* cell = state.atlas->GetCustomRectByIndex(image.cell);
        const float u = float(cell->X + 2) / state.atlas->TexWidth, v = float(cell->Y + 2) / state.atlas->TexHeight;
        const float du = float(image.width) / state.atlas->TexWidth, dv = float(image.height) / state.atlas->TexHeight;
        draw->PrimReserve(3, 3);
        for (const auto i : {triangle.a, triangle.b, triangle.c}) {
            const auto& vertex = model.vertices[i]; const auto& projected = model.projected[i];
            draw->PrimVtx(projected.position, {u + vertex.uv.x * du, v + vertex.uv.y * dv}, Color(vertex.color, triangle.color, projected.light));
        }
    }
    draw->PopTextureID(); draw->PopClipRect(); return true;
}
} // namespace darkwatch::preview
