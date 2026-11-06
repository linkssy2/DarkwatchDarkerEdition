#pragma once
#include <cstdint>
struct X86Context;
void DarkwatchResetSightMode();
void DarkwatchSightRelease(X86Context& ctx, uint8_t* base);
