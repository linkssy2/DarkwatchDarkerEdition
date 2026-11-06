#pragma once
#include <cstdint>
struct X86Context;

#ifdef XBE_RELEASE
inline void DarkwatchCharacterVoiceQuery(X86Context&, uint8_t*) {}
inline void DarkwatchCharacterVoiceQueryResult(X86Context&, uint8_t*) {}
inline void DarkwatchCharacterVoiceSpeaker(X86Context&, uint8_t*) {}
inline void DarkwatchCharacterVoiceLocal(X86Context&, uint8_t*) {}
inline void DarkwatchCharacterVoiceDispatch(X86Context&, uint8_t*) {}
inline void DarkwatchCharacterVoiceCreated(X86Context&, uint8_t*) {}
inline void DarkwatchCharacterVoiceMelee(X86Context&, uint8_t*) {}
inline void DarkwatchCharacterVoiceThrow(X86Context&, uint8_t*, uint32_t weapon_component, uint32_t owner) {}
#else
void DarkwatchCharacterVoiceQuery(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceQueryResult(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceSpeaker(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceLocal(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceDispatch(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceCreated(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceMelee(X86Context&, uint8_t*);
void DarkwatchCharacterVoiceThrow(X86Context&, uint8_t*, uint32_t weapon_component, uint32_t owner);
#endif
