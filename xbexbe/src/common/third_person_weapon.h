#pragma once
#include "cpu/x86_context.h"

// Draw-local mechanical part adjustment; leaves native pose and action clocks intact.
void DarkwatchWeaponSkinPalette(X86Context& ctx, uint8_t* base);
