#pragma once
#include <cstdint>
namespace darkwatch {
int MonsterScreamsVolume();
void SetMonsterScreamsVolume(int value);
void AudioLoad(const void* table);
void AudioSave(void* table);
void SyncAudioDevice(uint8_t* base);
}
