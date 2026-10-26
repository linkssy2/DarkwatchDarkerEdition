#pragma once
#include <cstdint>

struct X86Context;
// Original single-player/two-player camera creation; other layouts are untouched.
void DarkwatchConfigurePlayerCamera(X86Context& ctx, uint8_t* base);
// Original player camera update: apply the view scale through its existing FOV setter.
void DarkwatchUpdatePlayerView(X86Context& ctx, uint8_t* base);
// Temporarily use the weapon preference inside the original first-person draw.
void DarkwatchBeginWeaponView(X86Context& ctx, uint8_t* base);
void DarkwatchEndWeaponView(X86Context& ctx, uint8_t* base);
// Preserve the authored screen-relative Blood Frenzy framing at custom world FOV.
void DarkwatchBeginPowerView(X86Context& ctx, uint8_t* base);
void DarkwatchEndPowerView(X86Context& ctx, uint8_t* base);
void DarkwatchPowerViewProjection(X86Context& ctx, uint8_t* base);
