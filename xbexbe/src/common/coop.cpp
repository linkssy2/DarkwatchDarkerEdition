// Winsock 2 must precede any windows.h pulled in by the runtime headers.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <mstcpip.h>
#ifndef SIO_UDP_CONNRESET  // absent from some non-Microsoft headers
#define SIO_UDP_CONNRESET _WSAIOW(IOC_VENDOR, 12)
#endif
#include "common/coop.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>
#include <toml++/toml.hpp>
#include <cmath>
#include <vector>
#include "audio/audio.h"
#include "tools/coop_keys.h"
#include "core/input.h"
#include "core/log.h"

namespace darkwatch::coop {

std::optional<Packet> Session::Receive(const Packet& packet, Address from, uint64_t now_ms) {
    Packet reply;
    reply.token = packet.token;
    if (packet.type == Type::Hello) {
        reply.type = Type::Welcome;
        if (packet.version != kVersion) {reply.status = Status::BadVersion; return reply;}
        if (!CodeMatches(packet, code_)) {reply.status = Status::BadCode; return reply;}
        // One guest. A guest restarting from the same address replaces its own session.
        if (Active(now_ms) && *guest_ != from) {reply.status = Status::Busy; return reply;}
        if (!Active(now_ms) || packet.token != token_) {
            token_ = packet.token; sequence_ = packet.sequence; pad_ = {};
            ++mouse_epoch_;
            key_request_ = true;  // a new viewer starts from a key frame
            LOGR("coop: guest joined");
        }
        guest_ = from; last_ms_ = now_ms;
        return reply;
    }
    if (!Active(now_ms) || from != *guest_ || packet.token != token_) return std::nullopt;
    if (packet.type == Type::Pad) {
        last_ms_ = now_ms;
        if (Newer(packet.sequence, sequence_)) {
            if (packet.pad.mouse != pad_.mouse) {
                ++mouse_epoch_;  // grabbed or released: no motion across it
            } else if (packet.pad.mouse) {
                // 32-bit wire totals become 64-bit totals, like the host's own mouse.
                mouse_x_ += uint64_t(int64_t(int32_t(packet.pad.mouse_x - pad_.mouse_x)));
                mouse_y_ += uint64_t(int64_t(int32_t(packet.pad.mouse_y - pad_.mouse_y)));
            }
            sequence_ = packet.sequence; pad_ = packet.pad; pad_ms_ = now_ms; ++pads_;
        }
    } else if (packet.type == Type::KeyRequest) {
        last_ms_ = now_ms;
        key_request_ = true;
    } else if (packet.type == Type::Bye) {
        guest_.reset();
        LOGR("coop: guest left");
    }
    return std::nullopt;
}

bool Session::Current(PadState& pad, uint64_t now_ms) const {
    if (!Active(now_ms)) return false;
    pad = pad_;
    return true;
}

namespace {

std::mutex g_settings_lock;
Settings g_settings;

uint64_t NowMs() {
    using namespace std::chrono;
    return uint64_t(duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count());
}

// Shared by the network thread and the guest's input/rumble threads.
struct Host {
    std::mutex lock;
    Session session;
    uint16_t left = 0, right = 0;
    bool rumble_changed = false;
    SOCKET socket = INVALID_SOCKET;   // sendto is safe beside the network thread's recvfrom
    std::atomic<uint32_t> video_frame{0}, audio_sequence{0};
    explicit Host(std::string code) : session(std::move(code)) {}
};
std::atomic<Host*> g_host{nullptr};
void AudioTap(const float* frames, uint32_t count);

void Send(SOCKET s, const Packet& packet, Address to) {
    uint8_t data[kMaxPacket];
    const size_t size = Encode(packet, data);
    sockaddr_in addr{};
    addr.sin_family = AF_INET; addr.sin_addr.s_addr = to.ip; addr.sin_port = to.port;
    if (size) sendto(s, reinterpret_cast<const char*>(data), int(size), 0, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
}

void Serve(Host* host, SOCKET s) {
    constexpr uint64_t kRumbleIntervalMs = 50;  // also tells the guest the host is alive
    uint64_t rumble_sent = 0;
    uint32_t sequence = 0;
    for (;;) {
        uint8_t data[kMaxPacket + 1];
        sockaddr_in from{};
        int from_size = sizeof(from);
        const int size = recvfrom(s, reinterpret_cast<char*>(data), sizeof(data), 0,
                                  reinterpret_cast<sockaddr*>(&from), &from_size);
        const uint64_t now = NowMs();
        std::optional<Packet> reply;
        Address source{from.sin_addr.s_addr, from.sin_port};
        Packet packet;
        std::optional<Address> guest;
        Packet rumble;
        bool send_rumble = false;
        {
            std::lock_guard lock(host->lock);
            if (size > 0 && from.sin_family == AF_INET && Decode(data, size_t(size), packet))
                reply = host->session.Receive(packet, source, now);
            guest = host->session.Guest(now);
            if (guest && (host->rumble_changed || now - rumble_sent >= kRumbleIntervalMs)) {
                rumble.type = Type::Rumble; rumble.token = host->session.Token(); rumble.sequence = ++sequence;
                rumble.left = host->left; rumble.right = host->right;
                host->rumble_changed = false; send_rumble = true; rumble_sent = now;
            }
        }
        if (reply) Send(s, *reply, source);
        if (send_rumble) Send(s, rumble, *guest);
    }
}

} // namespace

Settings Snapshot() {
    std::lock_guard lock(g_settings_lock);
    return g_settings;
}

void Load(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    Settings settings;
    settings.host = t["coop_host"].is_boolean() && t["coop_host"].value_or(false);
    if (auto value = t["coop_port"].is_integer() ? t["coop_port"].value<int64_t>() : std::nullopt)
        settings.port = uint32_t(std::clamp(*value, int64_t(1024), int64_t(65535)));
    if (auto value = t["coop_code"].value<std::string>(); value && value->size() <= kCodeBytes) settings.code = *value;
    settings.campaign = t["coop_campaign"].is_boolean() && t["coop_campaign"].value_or(false);
    std::lock_guard lock(g_settings_lock);
    g_settings = settings;
}

void Save(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    const Settings settings = Snapshot();
    t.insert_or_assign("coop_host", settings.host);
    t.insert_or_assign("coop_port", int64_t(settings.port));
    t.insert_or_assign("coop_code", settings.code);
    t.insert_or_assign("coop_campaign", settings.campaign);
}

void Start() {
    const Settings settings = Snapshot();
    if (!settings.host || g_host.load()) return;
    if (settings.code.empty()) {LOGE("coop: hosting needs coop_code in the settings file"); return;}
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa)) {LOGE("coop: Winsock unavailable"); return;}
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) {LOGE("coop: socket failed (%d)", WSAGetLastError()); return;}
    // An unreachable guest must not turn the next receive into an error.
    BOOL report = FALSE; DWORD bytes = 0;
    WSAIoctl(s, SIO_UDP_CONNRESET, &report, sizeof(report), nullptr, 0, &bytes, nullptr, nullptr);
    DWORD timeout = 20;  // ms; paces keepalives while no packets arrive
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout), sizeof(timeout));
    sockaddr_in addr{};
    addr.sin_family = AF_INET; addr.sin_addr.s_addr = htonl(INADDR_ANY); addr.sin_port = htons(uint16_t(settings.port));
    if (bind(s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr))) {
        LOGE("coop: UDP port %u is unavailable (%d)", settings.port, WSAGetLastError());
        closesocket(s); return;
    }
    // Lives for the process: the guest's input threads may read it until exit.
    auto* host = new Host(settings.code);
    host->socket = s;
    g_host = host;
    static_assert(audio::kRate == kAudioRate, "the guest plays the mix at the host's rate");
    audio::SetTap(AudioTap);
    std::thread(Serve, host, s).detach();
    LOGR("coop: hosting on UDP %u", settings.port);
}

void Pad(int port, input::Pad& pad) {
    Host* host = g_host.load();
    if (port != kGuestPort || !host) return;
    PadState state;
    {
        std::lock_guard lock(host->lock);
        if (!host->session.Current(state, NowMs())) return;  // no guest: local split screen
    }
    pad.connected = true;
    pad.buttons = state.buttons;
    std::copy(std::begin(state.analog), std::end(state.analog), std::begin(pad.analog));
    pad.lx = state.lx; pad.ly = state.ly; pad.rx = state.rx; pad.ry = state.ry;
}

bool SendVideo(const uint8_t* data, size_t size, bool key) {
    Host* host = g_host.load();
    if (!host || !size) return false;
    std::optional<Address> guest;
    uint32_t token = 0;
    {
        std::lock_guard lock(host->lock);
        guest = host->session.Guest(NowMs());
        token = host->session.Token();
    }
    const size_t count = (size + kVideoChunk - 1) / kVideoChunk;
    if (!guest || count > 0xFFFF) return false;
    Packet packet;
    packet.type = Type::Video;
    packet.token = token;
    packet.frame = packet.sequence = host->video_frame++;
    packet.count = uint16_t(count);
    packet.key = key;
    for (size_t i = 0; i < count; ++i) {
        packet.index = uint16_t(i);
        packet.payload = data + i * kVideoChunk;
        packet.payload_size = uint16_t(std::min(kVideoChunk, size - i * kVideoChunk));
        Send(host->socket, packet, *guest);
    }
    return true;
}

bool SendAudio(const int16_t* samples, uint32_t frames) {
    Host* host = g_host.load();
    if (!host || !frames) return false;
    std::optional<Address> guest;
    uint32_t token = 0;
    {
        std::lock_guard lock(host->lock);
        guest = host->session.Guest(NowMs());
        token = host->session.Token();
    }
    if (!guest) return false;
    constexpr uint32_t kPacketFrames = kVideoChunk / 4 / 48 * 48;  // whole milliseconds per datagram
    Packet packet;
    packet.type = Type::Audio;
    packet.token = token;
    for (uint32_t done = 0; done < frames; done += kPacketFrames) {
        packet.sequence = host->audio_sequence++;
        packet.frames = uint16_t(std::min(kPacketFrames, frames - done));
        packet.payload = reinterpret_cast<const uint8_t*>(samples + size_t(done) * 2);
        packet.payload_size = uint16_t(packet.frames * 4);
        Send(host->socket, packet, *guest);
    }
    return true;
}

namespace {
// Audio output thread, every 10 ms block: the host's mix for the guest as int16 stereo.
void AudioTap(const float* frames, uint32_t count) {
    thread_local std::vector<int16_t> pcm;
    pcm.resize(size_t(count) * 2);
    for (size_t i = 0; i < pcm.size(); ++i)
        pcm[i] = int16_t(std::lround(std::clamp(frames[i], -1.0f, 1.0f) * 32767.0f));
    SendAudio(pcm.data(), count);
}
} // namespace

bool GuestMouse(Session::Mouse& mouse) {
    Host* host = g_host.load();
    if (!host) return false;
    std::lock_guard lock(host->lock);
    return host->session.CurrentMouse(mouse, NowMs());
}

void GuestMouseStick(input::Pad& pad) {
    // Input threads poll port 1 several times a frame; the window spreads uneven updates.
    static std::mutex lock;
    static keys::MouseVelocity velocity;
    static Session::Mouse last;
    Session::Mouse mouse;
    if (!GuestMouse(mouse)) return;
    const uint64_t now_us = NowMs() * 1000;
    std::lock_guard guard(lock);
    if (mouse.epoch == last.epoch && mouse.generation != last.generation && mouse.active)
        velocity.Add(int64_t(mouse.x - last.x), int64_t(mouse.y - last.y), now_us);
    last = mouse;
    int64_t dx = 0, dy = 0;
    uint64_t window_us = 0;
    velocity.Stick(now_us, dx, dy, window_us);
    const int16_t rx = keys::MouseAxis(dx, window_us), ry = keys::MouseAxis(-dy, window_us);
    if (rx || ry) {pad.rx = rx; pad.ry = ry;}
}

bool TakeKeyRequest() {
    Host* host = g_host.load();
    if (!host) return false;
    std::lock_guard lock(host->lock);
    return host->session.TakeKeyRequest();
}

bool GuestActive() {
    Host* host = g_host.load();
    if (!host) return false;
    std::lock_guard lock(host->lock);
    return host->session.Active(NowMs());
}

void Rumble(int port, uint16_t& left, uint16_t& right) {
    Host* host = g_host.load();
    if (port != kGuestPort || !host) return;
    std::lock_guard lock(host->lock);
    if (!host->session.Active(NowMs())) return;
    if (host->left != left || host->right != right) host->rumble_changed = true;
    host->left = left; host->right = right;
    left = right = 0;  // the guest's controller vibrates, not a local pad on port 1
}

} // namespace darkwatch::coop
