#pragma once
#include <cstdint>

struct X86Context;

void DarkwatchScaleReticle(X86Context& ctx, uint8_t* base);
// Final quad boundary: recolors only the native reticle, retaining vertex alpha.
void DarkwatchReticleColor(X86Context& ctx, uint8_t* base);
