#pragma once
#include <cstdint>
struct X86Context;
namespace darkwatch {
void InitializeHdUi();
bool GameplayTexturesAvailable();
}
void DarkwatchHdStartupBegin(X86Context&, uint8_t*);
void DarkwatchHdStartupEnd(X86Context&, uint8_t*);
