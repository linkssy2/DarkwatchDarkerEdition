#pragma once
#include <cstdint>
struct X86Context;

// Called only for an admitted on-foot third-person pass, before camera offset.
// Preserves the caller's CPU context and stack scratch; native action state advances.
void DarkwatchPrepareThirdPersonHands(const X86Context& ctx, uint8_t* base, uint32_t personal);
