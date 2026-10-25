#pragma once
#include <cstdint>
namespace input { struct Pad; }
void DarkwatchGraphicsInit();
void DarkwatchGraphicsWindow(void* window);
void DarkwatchGraphicsUi(double fps);
void DarkwatchGraphicsPad(int port, input::Pad& pad);
// Guest draw hook: refresh co-op before its first native draw, without consuming actions.
void DarkwatchCoopSetupRefresh(uint8_t* base);
bool DarkwatchGraphicsVisible();
// Called only after validating the original frontend owner on the guest thread.
void DarkwatchCharactersOpen(uint32_t owner);
void DarkwatchDesktopQuitOpen(uint32_t owner);
