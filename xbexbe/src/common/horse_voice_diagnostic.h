#pragma once
#include <cstdint>
struct X86Context;
namespace horse_voice {
void Begin(uint8_t* base, uint32_t event, uint32_t stack, uint32_t thread);
void End(uint8_t* base, uint32_t event, uint32_t stack, uint32_t thread);
}
void DarkwatchHorseVoiceStart(X86Context& ctx, uint8_t* base);
void DarkwatchHorseVoiceEnd(X86Context& ctx, uint8_t* base);
