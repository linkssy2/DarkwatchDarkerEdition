#pragma once
#include <cstdint>
#include <array>
#include "core/input.h"
// Poll on the guest input path; renderer sees only the copied wheel state.
unsigned DarkwatchWeaponWheelInput(int port, input::Pad& pad);
bool DarkwatchWeaponWheelOpen();
bool DarkwatchWeaponWheelBlocksLook(uint64_t generation);
void DarkwatchWeaponWheelDraw();
std::array<float,4> DarkwatchWeaponWheelViewport();
