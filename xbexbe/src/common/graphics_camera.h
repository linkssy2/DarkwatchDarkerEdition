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
// Network co-op swapped the views: the view scale and weapon pass follow the host's
// player, whose view object (F9B1D's) and camera these are.
void DarkwatchSetHostPlayerCamera(uint32_t owner, uint32_t camera, const uint8_t* base);
