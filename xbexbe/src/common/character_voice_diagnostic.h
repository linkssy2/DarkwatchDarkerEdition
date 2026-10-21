#pragma once
#include <cstdint>
struct X86Context;

void DarkwatchCharacterVoiceQuery(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceQueryResult(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceSpeaker(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceLocal(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceDispatch(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceCreated(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceMelee(X86Context&, uint8_t*);
