#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>

namespace darkwatch {

inline constexpr size_t kOnlineSessionUrlMaxBytes = 2048;

struct OnlineSessionUrlFields {
    std::array<uint8_t, 36> address{};
    std::array<uint8_t, 8> key_id{};
    std::array<uint8_t, 16> key{};
};

namespace online_session_url_detail {
inline int HexDigit(char ch) noexcept {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    return -1;
}

template <size_t N>
inline bool DecodeHex(std::string_view value, std::array<uint8_t, N>& out) noexcept {
    if (value.size() != N * 2) return false;
    for (size_t i = 0; i < N; ++i) {
        const int high = HexDigit(value[i * 2]);
        const int low = HexDigit(value[i * 2 + 1]);
        if (high < 0 || low < 0) return false;
        out[i] = static_cast<uint8_t>((high << 4) | low);
    }
    return true;
}
} // namespace online_session_url_detail

// Original StationURL: prudp:/name=value;name=value#secondary=value;...
// 18F870/18F8C0/18F9E0 parse ';', '#', ':/' and '='; 190FA0 writes
// address/xnkid/xnkey into the primary section as 36/8/16 bytes of hex.
// Decode here: native 190060 ignores hex-decoder failure and accepts short fields.
// Input excludes the terminating NUL. On failure, out remains unchanged.
inline bool ParseOnlineSessionUrl(std::string_view url, OnlineSessionUrlFields& out) noexcept {
    constexpr std::string_view prefix = "prudp:/";
    if (url.size() > kOnlineSessionUrlMaxBytes || url.substr(0, prefix.size()) != prefix)
        return false;
    for (unsigned char ch : url) {
        if (ch <= 0x20 || ch >= 0x7F) return false;
    }
    if (url.find(":/", prefix.size()) != std::string_view::npos) return false;

    OnlineSessionUrlFields decoded;
    unsigned required = 0;
    bool secondary = false;
    // The shortest field is "a=b;", so a bounded URL cannot fill this array.
    std::array<std::string_view, kOnlineSessionUrlMaxBytes / 4> names{};
    size_t name_count = 0;
    size_t begin = prefix.size();
    while (begin < url.size()) {
        size_t end = url.find_first_of(";#", begin);
        if (end == std::string_view::npos) end = url.size();
        const auto field = url.substr(begin, end - begin);
        const size_t equals = field.find('=');
        if (equals == std::string_view::npos || equals == 0 || equals + 1 == field.size() ||
            field.find('=', equals + 1) != std::string_view::npos)
            return false;
        const auto name = field.substr(0, equals);
        const auto value = field.substr(equals + 1);
        for (size_t i = 0; i < name_count; ++i) {
            if (names[i] == name) return false;
        }
        if (name_count == names.size()) return false;
        names[name_count++] = name;

        unsigned bit = 0;
        if (name == "address") bit = 1;
        else if (name == "xnkid") bit = 2;
        else if (name == "xnkey") bit = 4;
        if (bit) {
            // Native getters request primary fields. A shadow key in the secondary
            // section must not silently change which identity a caller validates.
            if (secondary || (required & bit)) return false;
            bool valid = false;
            if (bit == 1) valid = online_session_url_detail::DecodeHex(value, decoded.address);
            else if (bit == 2) valid = online_session_url_detail::DecodeHex(value, decoded.key_id);
            else valid = online_session_url_detail::DecodeHex(value, decoded.key);
            if (!valid) return false;
            required |= bit;
        }
        if (end == url.size()) break;
        if (url[end] == '#') {
            if (secondary) return false;
            secondary = true;
            name_count = 0; // Native primary/secondary attributes are distinct namespaces.
        }
        begin = end + 1;
        if (begin == url.size()) return false;
    }
    if (required != 7) return false;
    out = decoded;
    return true;
}

} // namespace darkwatch
