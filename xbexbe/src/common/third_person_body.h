#pragma once
#include <cstdint>
struct X86Context;
// Refresh native arm-aim poses after the current personal-camera update.
void DarkwatchThirdPersonBodyAim(const X86Context& ctx, uint8_t* base, uint32_t actor);
