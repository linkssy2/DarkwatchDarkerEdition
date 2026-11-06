#pragma once
#include <cstdint>
struct X86Context;

#ifdef XBE_RELEASE
inline void DarkwatchCriCreate(X86Context&, uint8_t*) {}
inline void DarkwatchCriDestroy(X86Context&, uint8_t*) {}
inline void DarkwatchCriDestroyCleared(X86Context&, uint8_t*) {}
inline void DarkwatchCriPoolInitialize(X86Context&, uint8_t*) {}
inline void DarkwatchCriPoolRelease(X86Context&, uint8_t*) {}
inline void DarkwatchCriPoolInitializeCleared(X86Context&, uint8_t*) {}
inline void DarkwatchCriPoolReleaseCleared(X86Context&, uint8_t*) {}
inline void DarkwatchCriOwnerAcquire(X86Context&, uint8_t*) {}
inline void DarkwatchCriOwnerGet(X86Context&, uint8_t*) {}
inline void DarkwatchCriOwnerDestroy(X86Context&, uint8_t*) {}
inline void DarkwatchCriChunkBegin(X86Context&, uint8_t*) {}
inline void DarkwatchCriChunkFirst(X86Context&, uint8_t*) {}
inline void DarkwatchCriChunkSecond(X86Context&, uint8_t*) {}
inline void DarkwatchCriChunkEnd(X86Context&, uint8_t*) {}
inline void DarkwatchCriDivide(X86Context&, uint8_t*) {}
inline void DarkwatchCriCompare(X86Context&, uint8_t*) {}
inline void DarkwatchCriWorkerBegin(X86Context&, uint8_t*) {}
inline void DarkwatchCriWorkerEnd(X86Context&, uint8_t*) {}
inline void DarkwatchCriDrainBegin(X86Context&, uint8_t*) {}
inline void DarkwatchCriDrainEnd(X86Context&, uint8_t*) {}
inline void DarkwatchCriHandshakeBegin(X86Context&, uint8_t*) {}
inline void DarkwatchCriHandshakeEnd(X86Context&, uint8_t*) {}
inline void DarkwatchCriWorkerAcknowledge(X86Context&, uint8_t*) {}
inline void DarkwatchCriWorkerSuspend(X86Context&, uint8_t*) {}
inline void DarkwatchCriDecoderCallback(X86Context&, uint8_t*) {}
inline void DarkwatchCriDecoderCleared(X86Context&, uint8_t*) {}
inline void DarkwatchCriDecoderPublished(X86Context&, uint8_t*) {}
#else
void DarkwatchCriCreate(X86Context&, uint8_t*);
void DarkwatchCriDestroy(X86Context&, uint8_t*);
void DarkwatchCriDestroyCleared(X86Context&, uint8_t*);
void DarkwatchCriPoolInitialize(X86Context&, uint8_t*);
void DarkwatchCriPoolRelease(X86Context&, uint8_t*);
void DarkwatchCriPoolInitializeCleared(X86Context&, uint8_t*);
void DarkwatchCriPoolReleaseCleared(X86Context&, uint8_t*);
void DarkwatchCriOwnerAcquire(X86Context&, uint8_t*);
void DarkwatchCriOwnerGet(X86Context&, uint8_t*);
void DarkwatchCriOwnerDestroy(X86Context&, uint8_t*);
void DarkwatchCriChunkBegin(X86Context&, uint8_t*);
void DarkwatchCriChunkFirst(X86Context&, uint8_t*);
void DarkwatchCriChunkSecond(X86Context&, uint8_t*);
void DarkwatchCriChunkEnd(X86Context&, uint8_t*);
void DarkwatchCriDivide(X86Context&, uint8_t*);
void DarkwatchCriCompare(X86Context&, uint8_t*);
void DarkwatchCriWorkerBegin(X86Context&, uint8_t*);
void DarkwatchCriWorkerEnd(X86Context&, uint8_t*);
void DarkwatchCriDrainBegin(X86Context&, uint8_t*);
void DarkwatchCriDrainEnd(X86Context&, uint8_t*);
void DarkwatchCriHandshakeBegin(X86Context&, uint8_t*);
void DarkwatchCriHandshakeEnd(X86Context&, uint8_t*);
void DarkwatchCriWorkerAcknowledge(X86Context&, uint8_t*);
void DarkwatchCriWorkerSuspend(X86Context&, uint8_t*);
void DarkwatchCriDecoderCallback(X86Context&, uint8_t*);
void DarkwatchCriDecoderCleared(X86Context&, uint8_t*);
void DarkwatchCriDecoderPublished(X86Context&, uint8_t*);
#endif
