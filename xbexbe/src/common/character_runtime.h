#pragma once
#include <cstdint>
struct X86Context;

void DarkwatchCharacterResourceHeap(X86Context& ctx, uint8_t* base);
void DarkwatchStringHeap(X86Context& ctx, uint8_t* base);
void DarkwatchReferenceMapHeap(X86Context& ctx, uint8_t* base);
void DarkwatchCharacterMissionBegin(X86Context& ctx, uint8_t* base);
void DarkwatchCharacterMissionEnd(X86Context& ctx, uint8_t* base);
void DarkwatchCharacterFile(X86Context& ctx, uint8_t* base);
void DarkwatchCharacterSpawn(X86Context& ctx, uint8_t* base);
bool DarkwatchCharacterPrepareOnline(const X86Context& ctx, uint8_t* base);
bool DarkwatchCharacterModelAlias(X86Context& ctx, uint8_t* base);
bool DarkwatchCharacterCostume(X86Context& ctx, uint8_t* base);
unsigned DarkwatchCharacterUnavailablePlayers();
bool DarkwatchCharacterIsCassidyPlayer(const uint8_t* base, uint32_t actor);
bool DarkwatchCharacterIsTalaPlayer(const uint8_t* base, uint32_t actor);

// Content hashes and the native audio-bank owner are checked independently.
bool DarkwatchCharacterContentReady();
bool DarkwatchCharacterAudioReady(uint8_t* base, const char** failure = nullptr, bool tala = false);
bool DarkwatchAudioBankBudget(X86Context& ctx, uint8_t* base);
void DarkwatchCharacterInitialize(X86Context& ctx, uint8_t* base);
