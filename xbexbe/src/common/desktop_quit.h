#pragma once
#include <cstdint>
struct X86Context;
namespace darkwatch {
// Guest-thread only: append owned character/exit rows to the original menu.
bool EnsureDesktopQuitEntry(uint8_t* base);
uint32_t CharacterMenuOwner(const uint8_t* base);
bool ConfirmDesktopQuit(uint8_t* base, uint32_t owner);
}
void DarkwatchMainMenuInitialize(X86Context& ctx, uint8_t* base);
bool DarkwatchDesktopQuit(X86Context& ctx, uint8_t* base);
