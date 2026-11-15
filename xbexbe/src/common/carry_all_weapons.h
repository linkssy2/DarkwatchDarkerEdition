#pragma once
#include <cstdint>
#include <array>

// Returns the original preset's switch action, or -1 while switching is unsafe.
int DarkwatchWeaponCycleAction(unsigned input_port);
void DarkwatchQueueWeaponCycle(unsigned input_port, int direction);
void DarkwatchResetWeaponChoices();
struct DarkwatchWeaponChoices { uint32_t mask=0, current=0, actor=0; bool solo=false; std::array<float,4> viewport{0,0,1,1}; };
DarkwatchWeaponChoices DarkwatchGetWeaponChoices(unsigned input_port);
bool DarkwatchQueueWeaponSelection(unsigned input_port, unsigned identity);
