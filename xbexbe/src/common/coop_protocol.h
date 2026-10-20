#pragma once
// Network co-op wire format shared by the host runtime and darkwatch_coop_client.
// The host runs the original split-screen co-op; a guest's controller drives port 1.
// Little-endian, fixed-size UDP datagrams. The code check keeps strangers' packets
// off the pad; it is not encryption.
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string_view>

namespace darkwatch::coop {

constexpr uint32_t kMagic = 0x31435744;  // "DWC1"
constexpr uint8_t kVersion = 1;
constexpr uint16_t kDefaultPort = 41330;
constexpr size_t kCodeBytes = 32;
constexpr size_t kHeaderBytes = 16;
constexpr size_t kMaxPacket = 64;

enum class Type : uint8_t { Hello = 1, Welcome = 2, Pad = 3, Rumble = 4, Bye = 5 };
enum class Status : uint8_t { Accepted = 0, BadCode = 1, Busy = 2, BadVersion = 3 };

// Mirrors input::Pad without the connected flag; the host decides presence.
struct PadState {
    uint16_t buttons = 0;
    uint8_t analog[8] = {};
    int16_t lx = 0, ly = 0, rx = 0, ry = 0;
};

struct Packet {
    Type type = Type::Hello;
    uint8_t version = kVersion;
    uint32_t token = 0;  // chosen by the guest per session; stale sessions cannot inject
    uint32_t sequence = 0;
    std::array<char, kCodeBytes> code{};  // Hello
    Status status = Status::Accepted;     // Welcome
    PadState pad;                         // Pad
    uint16_t left = 0, right = 0;         // Rumble
};

inline bool SetCode(Packet& packet, std::string_view code) {
    if (code.empty() || code.size() > kCodeBytes) return false;
    packet.code.fill(0);
    std::memcpy(packet.code.data(), code.data(), code.size());
    return true;
}
inline bool CodeMatches(const Packet& packet, std::string_view code) {
    if (code.empty() || code.size() > kCodeBytes) return false;
    std::array<char, kCodeBytes> expected{};
    std::memcpy(expected.data(), code.data(), code.size());
    unsigned char diff = 0;  // constant time over the field
    for (size_t i = 0; i < kCodeBytes; ++i) diff |= uint8_t(expected[i] ^ packet.code[i]);
    return !diff;
}
// Wrap-aware: true when a is after b.
inline bool Newer(uint32_t a, uint32_t b) {return int32_t(a - b) > 0;}

namespace wire {
inline void Put16(uint8_t* p, uint16_t v) {p[0] = uint8_t(v); p[1] = uint8_t(v >> 8);}
inline void Put32(uint8_t* p, uint32_t v) {for (int i = 0; i < 4; ++i) p[i] = uint8_t(v >> (8 * i));}
inline uint16_t Get16(const uint8_t* p) {return uint16_t(p[0] | (p[1] << 8));}
inline uint32_t Get32(const uint8_t* p) {return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;}
inline size_t BodyBytes(Type type) {
    switch (type) {
    case Type::Hello: return kCodeBytes;
    case Type::Welcome: return 1;
    case Type::Pad: return 18;
    case Type::Rumble: return 4;
    case Type::Bye: return 0;
    }
    return SIZE_MAX;
}
} // namespace wire

// Returns the datagram size, or 0 for an unknown type.
inline size_t Encode(const Packet& packet, uint8_t (&out)[kMaxPacket]) {
    using namespace wire;
    const size_t body = BodyBytes(packet.type);
    if (body == SIZE_MAX) return 0;
    std::memset(out, 0, sizeof(out));
    Put32(out, kMagic); out[4] = packet.version; out[5] = uint8_t(packet.type);
    Put32(out + 8, packet.token); Put32(out + 12, packet.sequence);
    uint8_t* b = out + kHeaderBytes;
    switch (packet.type) {
    case Type::Hello: std::memcpy(b, packet.code.data(), kCodeBytes); break;
    case Type::Welcome: b[0] = uint8_t(packet.status); break;
    case Type::Pad:
        Put16(b, packet.pad.buttons); std::memcpy(b + 2, packet.pad.analog, 8);
        Put16(b + 10, uint16_t(packet.pad.lx)); Put16(b + 12, uint16_t(packet.pad.ly));
        Put16(b + 14, uint16_t(packet.pad.rx)); Put16(b + 16, uint16_t(packet.pad.ry));
        break;
    case Type::Rumble: Put16(b, packet.left); Put16(b + 2, packet.right); break;
    case Type::Bye: break;
    }
    return kHeaderBytes + body;
}

// Rejects foreign, truncated or oversized datagrams. A different version still decodes
// its header so the host can answer BadVersion.
inline bool Decode(const uint8_t* data, size_t size, Packet& packet) {
    using namespace wire;
    if (size < kHeaderBytes || Get32(data) != kMagic) return false;
    packet = {};
    packet.version = data[4]; packet.type = Type(data[5]);
    packet.token = Get32(data + 8); packet.sequence = Get32(data + 12);
    if (packet.version != kVersion) return packet.type == Type::Hello;
    const size_t body = BodyBytes(packet.type);
    if (body == SIZE_MAX || size != kHeaderBytes + body) return false;
    const uint8_t* b = data + kHeaderBytes;
    switch (packet.type) {
    case Type::Hello: std::memcpy(packet.code.data(), b, kCodeBytes); break;
    case Type::Welcome: if (b[0] > uint8_t(Status::BadVersion)) return false; packet.status = Status(b[0]); break;
    case Type::Pad:
        packet.pad.buttons = Get16(b); std::memcpy(packet.pad.analog, b + 2, 8);
        packet.pad.lx = int16_t(Get16(b + 10)); packet.pad.ly = int16_t(Get16(b + 12));
        packet.pad.rx = int16_t(Get16(b + 14)); packet.pad.ry = int16_t(Get16(b + 16));
        break;
    case Type::Rumble: packet.left = Get16(b); packet.right = Get16(b + 2); break;
    case Type::Bye: break;
    }
    return true;
}

} // namespace darkwatch::coop
