#pragma once

// Returns the original preset's switch action, or -1 while switching is unsafe.
int DarkwatchWeaponCycleAction(unsigned input_port);
void DarkwatchQueueWeaponCycle(unsigned input_port, int direction);
