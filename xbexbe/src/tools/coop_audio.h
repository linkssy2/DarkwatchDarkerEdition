#pragma once
// Guest side of the co-op audio: plays the host's mix from Audio packets through XAudio2
// with a short jitter buffer. A starved voice refills before playing again; a queue that
// grew behind real time drops packets instead of drifting later.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <xaudio2.h>
#include <array>
#include <cstring>
#include <vector>
#include "common/coop_protocol.h"

namespace darkwatch::coop {

class AudioPlayer {
public:
    static constexpr uint32_t kPrefill = 7;     // packets (~42 ms) before playing
    static constexpr uint32_t kMaxQueued = 20;  // ~120 ms; newer packets are dropped beyond it
    static constexpr uint32_t kSlots = 32;      // above kMaxQueued: XAudio2 reads queued slots

    ~AudioPlayer() {Close();}
    bool Open() {
        WAVEFORMATEX format{};
        format.wFormatTag = WAVE_FORMAT_PCM;
        format.nChannels = 2;
        format.nSamplesPerSec = kAudioRate;
        format.wBitsPerSample = 16;
        format.nBlockAlign = 4;
        format.nAvgBytesPerSec = kAudioRate * 4;
        if (FAILED(XAudio2Create(&xaudio_, 0, XAUDIO2_DEFAULT_PROCESSOR)) || FAILED(xaudio_->CreateMasteringVoice(&master_)) ||
            FAILED(xaudio_->CreateSourceVoice(&voice_, &format))) {
            Close();
            return false;
        }
        return true;
    }
    void Close() {
        if (voice_) voice_->DestroyVoice();  // before the slots it may still read
        if (master_) master_->DestroyVoice();
        if (xaudio_) xaudio_->Release();
        voice_ = nullptr; master_ = nullptr; xaudio_ = nullptr;
    }
    // A new session's sequence starts over.
    void Reset() {
        if (voice_) {voice_->Stop(); voice_->FlushSourceBuffers();}
        playing_ = false; has_sequence_ = false;
    }
    void Push(const Packet& packet) {
        if (!voice_ || packet.type != Type::Audio || !packet.frames || packet.payload_size != packet.frames * 4u) return;
        if (has_sequence_ && !Newer(packet.sequence, sequence_)) return;  // late or repeated
        sequence_ = packet.sequence;
        has_sequence_ = true;
        XAUDIO2_VOICE_STATE state{};
        voice_->GetState(&state, XAUDIO2_VOICE_NOSAMPLESPLAYED);
        if (playing_ && state.BuffersQueued == 0) {voice_->Stop(); playing_ = false;}  // starved: refill
        if (state.BuffersQueued >= kMaxQueued) return;
        auto& slot = slots_[next_++ % kSlots];
        slot.assign(packet.payload, packet.payload + packet.payload_size);
        XAUDIO2_BUFFER buffer{};
        buffer.AudioBytes = UINT32(slot.size());
        buffer.pAudioData = slot.data();
        if (FAILED(voice_->SubmitSourceBuffer(&buffer))) return;
        if (!playing_ && state.BuffersQueued + 1 >= kPrefill) {voice_->Start(); playing_ = true;}
    }

private:
    IXAudio2* xaudio_ = nullptr;
    IXAudio2MasteringVoice* master_ = nullptr;
    IXAudio2SourceVoice* voice_ = nullptr;
    std::array<std::vector<uint8_t>, kSlots> slots_;
    uint32_t next_ = 0, sequence_ = 0;
    bool playing_ = false, has_sequence_ = false;
};

} // namespace darkwatch::coop
