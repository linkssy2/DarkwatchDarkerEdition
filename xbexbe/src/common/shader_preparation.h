#pragma once
#include <cstdint>
struct X86Context;

namespace darkwatch {
// Setup-only: 0 is ready, 1 needs the isolated boot, -1 is an error.
int PrepareShaders();
}
void DarkwatchPrepareShaders(X86Context& ctx, uint8_t* base);
