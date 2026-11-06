#pragma once
#include "character_selection.h"
#include <cstdint>
struct X86Context;

#ifndef XBE_RELEASE
void DarkwatchOnlineCharactersBegin(uint32_t session, uint32_t game, uint32_t local, unsigned ordinal);
void DarkwatchOnlineCharactersTick(const X86Context&, uint8_t* base, uint32_t object);
bool DarkwatchOnlineCharactersReady();
bool DarkwatchOnlineCharacterChoices(const X86Context&, const uint8_t*, uint32_t game,
    std::array<darkwatch::settings::Character, 2>&, unsigned& local);
#endif
