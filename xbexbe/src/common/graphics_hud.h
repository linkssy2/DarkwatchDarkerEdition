#pragma once
#include <cstdint>
struct X86Context;
void DarkwatchHudQuad(X86Context& ctx, uint8_t* base);
void DarkwatchHudFont(X86Context& ctx, uint8_t* base);
void DarkwatchCoopHudMargins(X86Context& ctx, uint8_t* base);
// The current native HUD draw's horizontal artwork correction, or 1 outside it.
float DarkwatchHudHorizontalScale(uint8_t* base, uint32_t camera);
// Thread-safe snapshot of the last validated gameplay HUD viewport.
bool DarkwatchHudSplitView();
bool DarkwatchHideGameplayHud(X86Context& ctx, uint8_t* base);
