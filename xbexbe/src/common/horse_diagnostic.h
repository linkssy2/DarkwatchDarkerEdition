#pragma once
#include <cstdint>
struct X86Context;

void DarkwatchHorseBegin(X86Context&, uint8_t*);
void DarkwatchHorseEnd(X86Context&, uint8_t*);
void DarkwatchHorseReject57(X86Context&, uint8_t*);
void DarkwatchHorseReject3(X86Context&, uint8_t*);
void DarkwatchHorseReject2(X86Context&, uint8_t*);
