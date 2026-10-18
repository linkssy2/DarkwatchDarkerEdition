#pragma once
#include <cstdint>
struct X86Context;
void DarkwatchMenuRenderBegin(X86Context& ctx, uint8_t* base);
void DarkwatchMenuRow(X86Context& ctx, uint8_t* base);
void DarkwatchMenuRenderEnd(X86Context& ctx, uint8_t* base);
void DarkwatchMenuInput(X86Context& ctx, uint8_t* base);
void DarkwatchMenuUi(double fps);
// Guest-thread only, after changing the native row list or its geometry.
void DarkwatchInvalidateMenuSnapshot();
// Guest-thread only. Invalidates original footer layout after prompt glyph metrics change.
void DarkwatchRefreshMenuBars(uint8_t* base, uint64_t revision);
