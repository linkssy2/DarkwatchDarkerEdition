#pragma once
#include <cstdint>
struct X86Context;

// Original handheld fire query, immediately after its player aim response.
void DarkwatchThirdPersonShotAim(X86Context& ctx, uint8_t* base);
