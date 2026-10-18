#pragma once
#include <cstdint>
namespace input { struct Pad; }
void DarkwatchGraphicsInit();
void DarkwatchGraphicsWindow(void* window);
void DarkwatchGraphicsUi(double fps);
void DarkwatchGraphicsPad(int port, input::Pad& pad);
bool DarkwatchGraphicsVisible();
