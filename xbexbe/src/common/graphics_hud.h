#pragma once
#include <cstdint>
struct X86Context;
void DarkwatchHudQuad(X86Context& ctx, uint8_t* base);
void DarkwatchHudFont(X86Context& ctx, uint8_t* base);
void DarkwatchCoopHudMargins(X86Context& ctx, uint8_t* base);
// Thread-safe snapshot of the last validated gameplay HUD viewport.
bool DarkwatchHudSplitView();
