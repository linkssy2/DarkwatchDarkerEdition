#pragma once
// Guest side of the co-op video: reassembles Video chunks into encoded frames. Frames are
// predicted from the previous one, so after any loss the guest drops frames and asks for
// a key frame until one arrives whole.
#include <cstdint>
#include <cstring>
#include <vector>
#include "common/coop_protocol.h"

namespace darkwatch::coop {

class FrameAssembler {
public:
    // Adds one chunk; true when `frame` now holds a complete frame to decode.
    bool Add(const Packet& chunk, std::vector<uint8_t>& frame, bool& key) {
        if (chunk.type != Type::Video || !chunk.count || chunk.index >= chunk.count ||
            chunk.payload_size > kVideoChunk || (chunk.payload_size && !chunk.payload)) return false;
        if (started_ && !Newer(chunk.frame, frame_) && chunk.frame != frame_) return false;  // late
        if (!started_ || chunk.frame != frame_) {
            if (started_ && !Complete() && !done_) Lose();  // the previous frame never completed
            Begin(chunk);
        }
        if (done_ || chunk.count != count_) return false;
        if (have_[chunk.index]) return false;
        have_[chunk.index] = true;
        ++received_;
        // Only the last chunk may be short; its size fixes the frame's length.
        std::memcpy(data_.data() + size_t(chunk.index) * kVideoChunk, chunk.payload, chunk.payload_size);
        if (chunk.index + 1 == count_) length_ = size_t(chunk.index) * kVideoChunk + chunk.payload_size;
        key_ |= chunk.key;
        if (!Complete()) return false;
        done_ = true;
        const bool continues = has_last_ && frame_ == last_ + 1;
        has_last_ = true;
        last_ = frame_;
        if (!key_ && (waiting_key_ || !continues)) {waiting_key_ = true; return false;}
        waiting_key_ = false;
        frame.assign(data_.begin(), data_.begin() + length_);
        key = key_;
        return true;
    }
    // A loss is waiting for a key frame.
    bool NeedKey() const {return waiting_key_;}
    void Reset() {*this = {};}

private:
    void Begin(const Packet& chunk) {
        started_ = true; done_ = false; key_ = false;
        frame_ = chunk.frame; count_ = chunk.count; received_ = 0; length_ = 0;
        have_.assign(count_, false);
        data_.resize(size_t(count_) * kVideoChunk);
    }
    void Lose() {waiting_key_ = true;}
    bool Complete() const {return received_ == count_ && length_;}

    bool started_ = false, done_ = false, key_ = false, waiting_key_ = false, has_last_ = false;
    uint32_t frame_ = 0, last_ = 0;
    uint16_t count_ = 0, received_ = 0;
    size_t length_ = 0;
    std::vector<bool> have_;
    std::vector<uint8_t> data_;
};

} // namespace darkwatch::coop
