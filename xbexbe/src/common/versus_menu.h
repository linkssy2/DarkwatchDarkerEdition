#pragma once
#include "core/input.h"
#include <cstdint>
void DarkwatchVersusRefresh(uint8_t* base);
bool DarkwatchVersusVisible();
bool DarkwatchVersusPad(int port, input::Pad& pad);
void DarkwatchVersusDraw();
bool DarkwatchHideVersusContent(uint32_t page);
