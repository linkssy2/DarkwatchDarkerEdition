#pragma once
#include <cstdint>
namespace darkwatch {
void AudioLoad(const void* table);
void AudioSave(void* table);
void SyncAudioDevice(uint8_t* base);
}
