#pragma once
#include "core/input.h"
#include <cstdint>
struct X86Context;
void DarkwatchCorpseGrabInput(int port, input::Pad& pad, uint32_t actor, int action);
void DarkwatchCorpseGrabTick(const X86Context& ctx, uint8_t* base);
void DarkwatchResetCorpseGrab();
