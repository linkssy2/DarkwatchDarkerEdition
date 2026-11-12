#pragma once
#include <array>
#include <cstdint>
struct X86Context;
// Refresh native arm-aim poses after the current personal-camera update.
void DarkwatchThirdPersonBodyAim(const X86Context& ctx, uint8_t* base, uint32_t actor);
// The Spectral rig shares its finger joint with the rifle's authored socket.
bool DarkwatchRifleReloadSocket(const X86Context& ctx, uint8_t* base, uint32_t actor,
                               std::array<float,16>& world);
