#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include "common/coop_protocol.h"

namespace input { struct Pad; }

namespace darkwatch::coop {

// Network co-op, host side. A guest's controller replaces controller port 1 while the
// session is live; without a guest, port 1 keeps its local controller for split screen.
struct Settings {
    bool host = false;
    uint32_t port = kDefaultPort;
    std::string code;  // required to host; 1-32 bytes
    bool campaign = false;  // experimental: Split Screen offers the retained co-op campaign
    uint32_t video_kbps = 16000;  // guest view bitrate; a LAN or LAN VPN carries it easily
    uint32_t video_height = 720;  // 720 or 1080 lines; 1080 needs a fast host CPU at 60 fps
};
Settings Snapshot();
void Load(const void* table);
void Save(void* table);
void Start();  // once after settings load; no-op unless hosting with a code
void Pad(int port, input::Pad& pad);
void Rumble(int port, uint16_t& left, uint16_t& right);
bool GuestActive();  // a network guest is playing now

constexpr int kGuestPort = 1;
constexpr uint64_t kTimeoutMs = 1500;  // silent guest: port 1 unplugs, another guest may join

struct Address {
    uint32_t ip = 0;
    uint16_t port = 0;
    bool operator==(const Address&) const = default;
};

// Single-guest session state, without sockets or clocks; exposed for tests.
class Session {
public:
    explicit Session(std::string code) : code_(std::move(code)) {}
    // Returns the reply to send to `from`, if any.
    std::optional<Packet> Receive(const Packet& packet, Address from, uint64_t now_ms);
    bool Active(uint64_t now_ms) const {return guest_ && now_ms - last_ms_ < kTimeoutMs;}
    bool Current(PadState& pad, uint64_t now_ms) const;
    std::optional<Address> Guest(uint64_t now_ms) const {return Active(now_ms) ? guest_ : std::nullopt;}
    uint32_t Token() const {return token_;}
    void Leave() {guest_.reset();}
    // The guest joined or lost video: the next frame must be a key frame.
    bool TakeKeyRequest() {return std::exchange(key_request_, false);}
    // The guest's raw mouse: totals from its newest pad, a count of pad updates, and an
    // epoch that changes when a session starts or the client grabs or releases the mouse.
    // Totals wrap modulo 2^64, as input::MouseSnapshot's do.
    struct Mouse {uint64_t x = 0, y = 0, generation = 0, epoch = 0, published_ms = 0; bool active = false;};
    bool CurrentMouse(Mouse& mouse, uint64_t now_ms) const {
        if (!Active(now_ms)) return false;
        mouse = {mouse_x_, mouse_y_, pads_, mouse_epoch_, pad_ms_, pad_.mouse};
        return true;
    }
private:
    std::string code_;
    std::optional<Address> guest_;
    uint32_t token_ = 0, sequence_ = 0;
    uint64_t last_ms_ = 0, pad_ms_ = 0, pads_ = 0, mouse_epoch_ = 0, mouse_x_ = 0, mouse_y_ = 0;
    PadState pad_;
    bool key_request_ = false;
};

// Host video: sends one encoded frame to the guest in Video chunks; false without a guest.
bool SendVideo(const uint8_t* data, size_t size, bool key);
bool TakeKeyRequest();  // the guest asked for a key frame since the last call
// Host audio: sends interleaved int16 stereo frames to the guest; false without a guest.
bool SendAudio(const int16_t* samples, uint32_t frames);
// The guest's raw mouse for direct aim on port 1's player; false without a guest.
bool GuestMouse(Session::Mouse& mouse);
// With direct mouse off, the guest's mouse drives port 1's right stick as a local mouse would.
void GuestMouseStick(input::Pad& pad);

} // namespace darkwatch::coop
