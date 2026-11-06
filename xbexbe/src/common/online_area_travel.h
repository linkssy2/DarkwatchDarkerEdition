#pragma once
#include <cstdint>
struct X86Context;
#ifndef XBE_RELEASE
void DarkwatchOnlineAreaBegin(uint32_t session, uint32_t game, unsigned ordinal);
void DarkwatchOnlineAreaWrite(uint32_t* words);
void DarkwatchOnlineAreaReceive(const uint32_t* words);
bool DarkwatchOnlineAreaTick(const X86Context&, uint8_t* base);
#endif
