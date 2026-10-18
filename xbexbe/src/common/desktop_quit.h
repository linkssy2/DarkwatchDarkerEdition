#pragma once
#include <cstdint>
struct X86Context;
namespace darkwatch {
// Guest-thread only: append one owned row to the original retail main menu.
bool EnsureDesktopQuitEntry(uint8_t* base);
}
bool DarkwatchDesktopQuit(X86Context& ctx, uint8_t* base);
