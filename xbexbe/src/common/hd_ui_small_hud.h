#pragma once
#include "hd_ui_font.h"

namespace darkwatch::hd_ui {
// Original monochrome MP_HUD digits. Coloured/shaded grenade silhouettes,
// frames, meters and radar retain their authored pixels with bounded filtering.
inline constexpr FontCell kMultiplayerHudMasks[]{
    {2,53,12,62}, {19,53,24,62}, {30,53,41,62}, {45,53,55,62}, {59,53,69,62},
    {2,67,12,76}, {16,67,27,76}, {30,67,42,76}, {45,67,55,76}, {58,67,69,76},
};

inline bool ReconstructSmallHud(const hd::Asset& asset, std::span<const uint8_t> pixels,
                                std::vector<uint8_t>& output) {
    const bool multiplayer = asset.offset == 103180764u && asset.width == 128 && asset.height == 128 &&
                             asset.native_hash == 0xed3643f08dcb09bdull;
    const bool glow = asset.width == 64 && asset.height == 32 &&
        ((asset.offset == 103198772u && asset.native_hash == 0x2c56d382ccbeebcfull) ||
         (asset.offset == 103266612u && asset.native_hash == 0xe92216d8c9c598deull));
    if ((!multiplayer && !glow) || asset.format != 15 ||
        pixels.size() != uint64_t(asset.width) * asset.height * 4) return false;
    const uint64_t expected = multiplayer ? 0x06b3cfecb56dd7cfull :
        asset.offset == 103198772u ? 0xa989811d30559cbdull : 0xb2a70a41039965beull;
    if (hd::Hash(pixels) != expected) return false;
    auto result = Upscale4x(asset.width, asset.height, {pixels.begin(), pixels.end()});
    if (result.empty()) return false;
    if (multiplayer) {
        for (const auto cell : kMultiplayerHudMasks) {
            font_detail::RestoreCell(asset.width, pixels, cell, result);
            for (unsigned y=unsigned(cell.y0*4); y<unsigned(cell.y1*4); ++y)
              for (unsigned x=unsigned(cell.x0*4); x<unsigned(cell.x1*4); ++x) {
                auto* p=result.data()+(size_t(y)*asset.width*4+x)*4;
                if (!p[3]) p[0]=p[1]=p[2]=0;
                else {p[0]=p[2]=235; p[1]=234;}
              }
        }
    }
    // Glow falloff is intentionally filtered, not sharpened or redrawn.
    output.swap(result);
    return true;
}
} // namespace darkwatch::hd_ui
