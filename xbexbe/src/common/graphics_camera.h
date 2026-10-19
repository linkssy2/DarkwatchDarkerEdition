#pragma once
#include <cstdint>

struct X86Context;
// Fullscreen single-player camera creation; aspect changes require a level reload/restart.
void DarkwatchConfigurePlayerCamera(X86Context& ctx, uint8_t* base);
// Original player camera update: apply the view scale through its existing FOV setter.
void DarkwatchUpdatePlayerView(X86Context& ctx, uint8_t* base);
// Temporarily use the weapon preference inside the original first-person draw.
void DarkwatchBeginWeaponView(X86Context& ctx, uint8_t* base);
void DarkwatchEndWeaponView(X86Context& ctx, uint8_t* base);
