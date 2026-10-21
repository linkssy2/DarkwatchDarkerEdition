#pragma once
#include <cstdint>
struct X86Context;
bool DarkwatchHideCinematicBorder(X86Context& ctx, uint8_t* base);
bool DarkwatchHideSubtitleBackground(X86Context& ctx, uint8_t* base);
