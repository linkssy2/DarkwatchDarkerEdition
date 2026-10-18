#include "common/menu_cursor.h"
#include "app/app.h"
#include "kernel/disc.h"
#include <imgui.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <fstream>

namespace darkwatch {
namespace {
constexpr uint64_t kBadgeOffset = 103344436; // Native header preceding the original 64x64 "badge" texture.
constexpr size_t kHeaderBytes = 92, kBlockBytes = 4096;
using BadgeBytes = std::array<uint8_t, kHeaderBytes + kBlockBytes>;
using BadgePixels = std::array<uint8_t, 64 * 64 * 4>;
ImFontAtlas* g_atlas = nullptr;
int g_rectangle = -1;
ImVec2 g_uv_min, g_uv_max;

uint16_t U16(const uint8_t* p) { return uint16_t(p[0] | uint16_t(p[1]) << 8); }
uint32_t U32(const uint8_t* p) { return uint32_t(U16(p)) | uint32_t(U16(p + 2)) << 16; }

bool ReadBadge(BadgeBytes& bytes) {
    if (const auto* disc = kernel::MountedDisc()) {
        const auto* file = disc->Find("packfile.pck");
        return file && !file->dir && uint64_t(file->size) >= kBadgeOffset + bytes.size() &&
               disc->Read(*file, kBadgeOffset, bytes.data(), uint32_t(bytes.size())) == bytes.size();
    }
    // GameInfo.loaded precedes MountDefaults. Match the existing FindAssets ancestor search,
    // without reopening the XBE or reading the whole package just to obtain this small image.
    for (auto dir = app::ExeDir(); !dir.empty();) {
        std::ifstream file(dir / "assets" / "packfile.pck", std::ios::binary);
        if (file) {
            file.seekg(std::streamoff(kBadgeOffset));
            return bool(file.read(reinterpret_cast<char*>(bytes.data()), std::streamsize(bytes.size())));
        }
        auto parent = dir.parent_path();
        if (parent == dir) break;
        dir = std::move(parent);
    }
    return false;
}

bool DecodeBadge(const BadgeBytes& bytes, BadgePixels& pixels) {
    const auto* p = bytes.data();
    if (U32(p) != 5 || std::memcmp(p + 8, "badge\0", 6) || U16(p + 80) != 64 ||
        U16(p + 82) != 64 || p[84] != 32 || p[85] != 1 || p[87] != 15 || U32(p + 88) != kBlockBytes)
        return false;
    // Pin the complete native header and BC3 payload, never substitute similarly named art.
    uint64_t hash = 14695981039346656037ull;
    for (uint8_t byte : bytes) hash = (hash ^ byte) * 1099511628211ull;
    if (hash != 0x07D52DA3A5035CBAull) return false;
    for (unsigned block = 0; block < 256; ++block) {
        const uint8_t* src = p + kHeaderBytes + block * 16;
        uint8_t alpha[8]{src[0], src[1]};
        if (alpha[0] > alpha[1]) {
            for (unsigned i = 1; i < 7; ++i) alpha[i + 1] = uint8_t(((7 - i) * alpha[0] + i * alpha[1]) / 7);
        } else {
            for (unsigned i = 1; i < 5; ++i) alpha[i + 1] = uint8_t(((5 - i) * alpha[0] + i * alpha[1]) / 5);
            alpha[6] = 0; alpha[7] = 255;
        }
        uint64_t abits = 0;
        for (unsigned i = 0; i < 6; ++i) abits |= uint64_t(src[2 + i]) << (8 * i);
        uint8_t color[4][3]{};
        for (unsigned i = 0; i < 2; ++i) {
            const uint16_t c = U16(src + 8 + i * 2);
            color[i][0] = uint8_t((c >> 11) * 255 / 31);
            color[i][1] = uint8_t(((c >> 5) & 63) * 255 / 63);
            color[i][2] = uint8_t((c & 31) * 255 / 31);
        }
        for (unsigned c = 0; c < 3; ++c) {
            color[2][c] = uint8_t((2 * color[0][c] + color[1][c]) / 3);
            color[3][c] = uint8_t((color[0][c] + 2 * color[1][c]) / 3);
        }
        uint32_t cbits = U32(src + 12);
        for (unsigned i = 0; i < 16; ++i) {
            const unsigned pixel = ((block / 16 * 4 + i / 4) * 64 + block % 16 * 4 + i % 4) * 4;
            std::memcpy(pixels.data() + pixel, color[(cbits >> (i * 2)) & 3], 3);
            pixels[pixel + 3] = alpha[(abits >> (i * 3)) & 7];
        }
    }
    return true;
}
} // namespace

bool InitializeMenuCursor() {
    std::lock_guard lock(app::UiLock());
    if (!ImGui::GetCurrentContext()) return false;
    auto* atlas = ImGui::GetIO().Fonts;
    if (atlas == g_atlas && g_rectangle >= 0 && g_rectangle < atlas->CustomRects.Size && atlas->IsBuilt()) return true;
    g_atlas = nullptr; g_rectangle = -1;
    if (atlas->Locked || atlas->TexID) return false; // Never rebuild an atlas already in use by the renderer.
    BadgeBytes bytes{}; BadgePixels pixels{};
    if (!ReadBadge(bytes) || !DecodeBadge(bytes, pixels)) return false;
    const int rectangle = atlas->AddCustomRectRegular(64, 64);
    unsigned char* texture = nullptr;
    int width = 0, height = 0;
    atlas->GetTexDataAsRGBA32(&texture, &width, &height);
    const auto* rect = atlas->GetCustomRectByIndex(rectangle);
    if (!texture || !rect->IsPacked() || rect->X + 64 > width || rect->Y + 64 > height) return false;
    for (unsigned y = 0; y < 64; ++y)
        std::memcpy(texture + ((rect->Y + y) * width + rect->X) * 4, pixels.data() + y * 256, 256);
    atlas->TexPixelsUseColors = true;
    atlas->CalcCustomRectUV(rect, &g_uv_min, &g_uv_max);
    g_atlas = atlas; g_rectangle = rectangle;
    return true;
}

void DrawMenuCursor() {
    if (!ImGui::GetCurrentContext()) return;
    const auto& io = ImGui::GetIO();
    const ImVec2 p = io.MousePos;
    if (!ImGui::IsMousePosValid(&p) || p.x < 0 || p.y < 0 || p.x >= io.DisplaySize.x || p.y >= io.DisplaySize.y) return;
    const float scale = std::clamp(io.DisplaySize.y / 720.f, 1.f, 2.f);
    auto point = [&](float x, float y) { return ImVec2(p.x + x * scale, p.y + y * scale); };
    auto* draw = ImGui::GetForegroundDrawList();
    if (io.Fonts == g_atlas && g_rectangle >= 0 && io.Fonts->TexID)
        draw->AddImage(io.Fonts->TexID, point(6, 6), point(38, 38), g_uv_min, g_uv_max);
    // The tip gives the insignia an unambiguous hotspot and remains visible if original art is unavailable.
    draw->AddTriangleFilled(point(-1, -1), point(1, 15), point(11, 9), IM_COL32(12, 10, 10, 255));
    draw->AddTriangleFilled(point(0, 0), point(2, 12), point(9, 8), IM_COL32(225, 216, 198, 255));
    draw->AddTriangleFilled(point(2, 4), point(3, 9), point(6, 7), IM_COL32(139, 29, 24, 255));
}
} // namespace darkwatch
