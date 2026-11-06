#pragma once
#include <cstdint>

// Retained draw captures and exact runtime cache keys qualify these recipes.
// Original instructions remain in the player's verified executable.
namespace darkwatch::shaderprep {
struct ObservedBuilderLayout { uint32_t descriptor; uint16_t regs; uint64_t decode; };
inline constexpr ObservedBuilderLayout kObservedBuilderLayouts[] = {
    {0x80010102u, 0x001F, 0},
    {0x80020102u, 0x001F, 0},
    // Observed packed ATTR0..6 declaration; do not expand the full catalogue.
    {0x80000104u, 0x007F, 0x4200},
    {0x80000204u, 0x007F, 0x4200},
    {0x80010104u, 0x007F, 0x4200},
    {0x80020104u, 0x007F, 0x4200},
    {0x80030104u, 0x007F, 0x4200},
    {0x80040104u, 0x007F, 0x4200},
};
// Six mode-4 programs qualified through the original assembler/linker, with only
// their observed packed layout. No original instruction words are shipped.
struct ObservedBuilderProgram { uint32_t descriptor; const char* sha256; uint16_t regs; uint64_t decode; };
inline constexpr ObservedBuilderProgram kObservedBuilderPrograms[] = {
    {0x84000104u, "db0aad2e9b0894b2c277ecbcad11d7979f17d13be1ea5f5441a502b934e29d61", 0x007F, 0x4200},
    {0x84000204u, "f34951d7e994dccaf8eb6828f5b63b6e153d55ad18afc6a18bb69845a514ce58", 0x007F, 0x4200},
    {0x84010104u, "74442c5ab05674b4d97c58523d8c1685cdf1bacfc488a08cddcb02155d6f7df1", 0x007F, 0x4200},
    {0x84020104u, "ffa3df2180e8d6d8278efd7bd9196cf22a495d06d1e141e6892c3d53d28ef3f4", 0x007F, 0x4200},
    {0x84030104u, "81c3ee151ae4640461d6527f8381c2773cea58a921f1de035e0d645fd4e38ab4", 0x007F, 0x4200},
    {0x84040104u, "d0adcdf6a40341baa2196c60717609491aea6989114fbfa1cb726106032ce211", 0x007F, 0x4200},
};
struct StaticShaderRecipe { uint32_t address; const char* sha256; uint16_t regs; uint64_t decode; bool quad = false; };
inline constexpr StaticShaderRecipe kStaticShaderRecipes[] = {
    {0x004316D8u, "5be545b817309885270ed9c8d948d0f396cdedf260cf190677123a17bec992c3", 0x0007, 0},
    {0x0043171Cu, "d54d7ce556679625ed2dcf119c7cbd1c02563aa1290c35396158eaa6fd44cac9", 0x0003, 0},
    {0x004960F0u, "0ae31b588c0056e7f9d552d93d57af35de897bc35cd908b163196259eea5d0aa", 0x000F, 0},
    {0x00496268u, "76f294a7a02405dc08cf83ebc87f935f06298ae6644bd2e50fec23dace8520ff", 0x000F, 0},
    {0x004316D8u, "5be545b817309885270ed9c8d948d0f396cdedf260cf190677123a17bec992c3", 0x0007, 0, true},
    {0x0043171Cu, "d54d7ce556679625ed2dcf119c7cbd1c02563aa1290c35396158eaa6fd44cac9", 0x0003, 0, true},
};
struct FixedShaderRecipe { uint16_t regs; uint64_t decode; uint32_t light, types, tex[4]; bool quad = false; };
inline constexpr FixedShaderRecipe kFixedShaderRecipes[] = {
    {0x0205, 0x400, 0x1, 0x157, {0x0, 0x1, 0x2, 0x3}},
    {0x0209, 0x0, 0x0, 0x0, {0x2200, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x1, 0x57, {0x0, 0x1, 0x2, 0x3}},
    {0x0209, 0x0, 0x0, 0x0, {0x0, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x1, 0x17, {0x0, 0x1, 0x2, 0x3}},
    {0x020D, 0x400, 0x4001, 0x17, {0x0, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x1, 0x7, {0x0, 0x211, 0x2, 0x3}},
    {0x0205, 0x400, 0x1, 0x7, {0x0, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x1, 0x17, {0x0, 0x211, 0x2, 0x3}},
    {0x020D, 0x400, 0x4001, 0x7, {0x0, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x1, 0x3, {0x0, 0x1, 0x2, 0x3}},
    {0x020D, 0x400, 0x4001, 0x3, {0x0, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x0, 0x0, {0x0, 0x1, 0x2, 0x3}},
    {0x0209, 0x0, 0x0, 0x0, {0x0, 0x1, 0x2, 0x3}, true},
    {0x0205, 0x400, 0x1, 0x0, {0x0, 0x1, 0x2, 0x3}},
    {0x020D, 0x400, 0x4001, 0x0, {0x0, 0x1, 0x2, 0x3}},
    {0x0009, 0x0, 0x0, 0x0, {0x0, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x0, 0x0, {0x210, 0x1, 0x2, 0x3}},
    {0x0209, 0x0, 0x4001, 0x0, {0x0, 0x1, 0x2, 0x3}},
    {0x0205, 0x400, 0x1, 0xF, {0x0, 0x1, 0x2, 0x3}},
    {0x020D, 0x400, 0x4001, 0xF, {0x0, 0x1, 0x2, 0x3}},
    {0x020D, 0x400, 0x4001, 0x57, {0x0, 0x1, 0x2, 0x3}},
    {0x020D, 0x400, 0x4001, 0x157, {0x0, 0x1, 0x2, 0x3}},
};
struct PixelShaderRecipe { bool programmable; uint32_t ff[2][9]; uint8_t kind0, rect0, kind1; uint32_t proj, quad; uint8_t flags0 = 0; };
inline constexpr PixelShaderRecipe kPixelShaderRecipes[] = {
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {23, 2, 3, 1, 2, 1, 0, 0, 0}}, 1, 0, 1, 3, 0},
    {true, {{0, 0, 0, 0, 0, 0, 0, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 0, 0, 1, 0},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 0, 0, 1, 0},
    {true, {{0, 0, 0, 0, 0, 0, 0, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 1, 0, 1, 0},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {4, 3, 1, 0, 4, 3, 1, 0, 0}}, 0, 0, 0, 0, 0},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 0, 0, 1, 1},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 0, 0, 0, 0},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {23, 2, 3, 1, 2, 1, 0, 0, 0}}, 1, 0, 1, 0, 0},
    {false, {{2, 0, 2, 0, 2, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 0, 0, 0, 0, 0},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {4, 3, 1, 0, 4, 3, 1, 0, 0}}, 1, 0, 0, 0, 0},
    {false, {{2, 0, 2, 0, 2, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 0, 0, 0, 0, 1},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 0, 0, 0, 1},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 1, 0, 1, 1},
    {false, {{4, 0, 2, 0, 4, 0, 2, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 1, 0, 1, 1, 4},
    {false, {{2, 0, 2, 0, 2, 0, 2, 0, 0}, {4, 3, 1, 0, 4, 3, 1, 0, 0}}, 0, 0, 0, 0, 0},
    {false, {{4, 3, 2, 0, 2, 2, 0, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}}, 1, 0, 0, 0, 0},
};
}  // namespace darkwatch::shaderprep
