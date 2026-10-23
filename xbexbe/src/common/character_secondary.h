#pragma once
#include <cstdint>
struct X86Context;

void DarkwatchCharacterSecondary(X86Context& ctx, uint8_t* base);
void DarkwatchCharacterSecondaryReset();
