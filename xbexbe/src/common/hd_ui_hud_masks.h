#pragma once
#include "hd_ui_font.h"

namespace darkwatch::hd_ui {
struct HudMaskCell { const char* name; FontCell cell; };
// Authored hudinfo rectangles. Five working rectangles omit only proved empty
// edge strips, leaving shared gutters and the neighboring boss fill untouched.
inline constexpr HudMaskCell kHudMaskCells[]{
    {"ReticleSniperRifle", {92,197,105,210}},
    {"ReticleRifle", {83,108,106,131}},
    {"ReticleRevolver", {78,149,111,182}},
    {"ReticleShotgun", {14,143,55,184}},
    {"ReticleRocketLauncher", {8,68,63,123}},
    {"ReticleShadowPistol", {93,10,254,28}},
    {"ReticleSteamWagon", {10,223,63,246}},
    {"RocketLauncher", {123,122,148,158}},
    {"Rifle", {151,125,164,155}},
    {"Revolver", {165,125,178,160}},
    {"GatlingGun", {178,125,192,160}},
    {"Crossbow", {193,123,207,158}},
    {"Shotgun", {207,126,230,158}},
    {"ShadowPistol", {232,125,255,160}},
    {"SniperRifle", {124,160,149,192}},
    {"Pistol", {235,162,253,197}},
    {"Dynamite", {155,170,171,186}},
    {"SplitterGrenades", {172,170,188,186}},
    {"Infinity", {145,202,185,214}},
    {"DigitZero", {133,233,145,247}},
    {"DigitOne", {153,233,160,247}},
    {"DigitTwo", {167,233,179,247}},
    {"DigitThree", {184,233,197,247}},
    {"DigitFour", {201,233,214,247}},
    {"DigitFive", {133,214,145,228}},
    {"DigitSix", {150,214,162,228}},
    {"DigitSeven", {167,214,179,228}},
    {"DigitEight", {185,214,197,228}},
    {"DigitNine", {202,214,214,228}},
    {"FriendlyTeam", {4,5,23,36}},
    {"Flag", {76,69,95,89}},
    {"TeamIcon", {95,225,106,241}},
};

// This is a source-alpha contour reconstruction, not recovered vector art.
// All selected visible pixels have exactly this authored cream color. Other
// regions retain the existing 4x baseline; no UV, metrics or soft-mask edits.
inline bool ReconstructHudMasks(const hd::Asset& asset, std::span<const uint8_t> pixels,
                                std::vector<uint8_t>& output) {
    if(asset.offset!=103115060u || asset.width!=256 || asset.height!=256 ||
       asset.format!=15 || asset.native_hash!=0xbc1be62f8722530cull ||
       pixels.size()!=256u*256u*4u || hd::Hash(pixels)!=0x1e22b0cd65f7a110ull) return false;
    auto result=Upscale4x(asset.width,asset.height,{pixels.begin(),pixels.end()});
    if(result.empty())return false;
    for(const auto& entry:kHudMaskCells) {
        const auto cell=entry.cell;
        font_detail::RestoreCell(asset.width,pixels,cell,result);
        for(unsigned y=unsigned(cell.y0*4);y<unsigned(cell.y1*4);++y)
          for(unsigned x=unsigned(cell.x0*4);x<unsigned(cell.x1*4);++x) {
            auto* p=result.data()+(size_t(y)*asset.width*4+x)*4;
            p[0]=p[2]=p[3]?235:0; p[1]=p[3]?234:0;
        }
    }
    output.swap(result);return true;
}
} // namespace darkwatch::hd_ui
