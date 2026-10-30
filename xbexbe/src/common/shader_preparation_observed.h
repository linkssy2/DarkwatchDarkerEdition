#pragma once
#include <cstdint>

// Retained draw captures qualify only these additional layouts/programs.
// Original instructions remain in the player's verified executable.
namespace darkwatch::shaderprep {
struct ObservedBuilderLayout { uint32_t descriptor; uint16_t regs; uint64_t decode; };
inline constexpr ObservedBuilderLayout kObservedBuilderLayouts[] = {
    {0x80010102u, 0x001F, 0},
    {0x80020102u, 0x001F, 0},
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
};
struct PixelShaderRecipe { bool programmable; uint32_t ff[2][9]; uint8_t kind0, rect0, kind1; uint32_t proj, quad; };
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
};
}  // namespace darkwatch::shaderprep
