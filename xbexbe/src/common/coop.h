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
private:
    std::string code_;
    std::optional<Address> guest_;
    uint32_t token_ = 0, sequence_ = 0;
    uint64_t last_ms_ = 0;
    PadState pad_;
    bool key_request_ = false;
};

// Host video: sends one encoded frame to the guest in Video chunks; false without a guest.
bool SendVideo(const uint8_t* data, size_t size, bool key);
bool TakeKeyRequest();  // the guest asked for a key frame since the last call

} // namespace darkwatch::coop
