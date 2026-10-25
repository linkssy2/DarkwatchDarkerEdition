#include "kernel/kernel.h"
#include <algorithm>
#include <array>
#include <filesystem>
#include <string_view>
#include <windows.h>
#include <bcrypt.h>

namespace {
struct ArchivePin { const char* guest_path; uint64_t size; std::string_view sha256; };
constexpr std::array<ArchivePin, 3> kCharacterArchives{{
    {"D:\\packfile.pck", 133411077, "61ecad4b43070941e066c1b69e2ba03b67f0a846c0298472f3111f5f055a1425"},
    {"D:\\LvlSingl.pck", 1170739944, "97a1b7d06cc2ee42de3875685cc5d6c561b5a34275de072b0aa5e2463110c64e"},
    {"D:\\audio.pck", 145688078, "c889f14963005bb796e29d84ad06c7ab52fa1d8b138a7107f8fa7355e73970f1"},
}};

HANDLE OpenCharacterArchive(const ArchivePin& pin) {
    const auto host = kernel::ResolvePath(pin.guest_path, 0);
    if (host.empty() || pin.sha256.size() != 64) return INVALID_HANDLE_VALUE;
    const auto path = std::filesystem::u8path(host);
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file == INVALID_HANDLE_VALUE) return file;
    LARGE_INTEGER size{};
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    bool ok = GetFileSizeEx(file, &size) && size.QuadPart >= 0 && uint64_t(size.QuadPart) == pin.size;
    if (ok) ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
    if (ok) ok = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    std::array<unsigned char, 64 * 1024> buffer{};
    uint64_t total = 0;
    while (ok && total < pin.size) {
        DWORD read = 0;
        const DWORD requested = DWORD((std::min)(uint64_t(buffer.size()), pin.size - total));
        ok = ReadFile(file, buffer.data(), requested, &read, nullptr) && read != 0;
        if (ok) ok = BCryptHashData(hash, buffer.data(), read, 0) >= 0;
        total += read;
    }
    DWORD extra = 0;
    if (ok) ok = ReadFile(file, buffer.data(), 1, &extra, nullptr) && extra == 0;
    std::array<unsigned char, 32> digest{};
    if (ok) ok = BCryptFinishHash(hash, digest.data(), ULONG(digest.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    constexpr char hex[] = "0123456789abcdef";
    for (size_t i = 0; ok && i < digest.size(); ++i)
        ok = pin.sha256[i * 2] == hex[digest[i] >> 4] && pin.sha256[i * 2 + 1] == hex[digest[i] & 15];
    if (ok) return file;
    CloseHandle(file);
    return INVALID_HANDLE_VALUE;
}

struct CharacterArchiveSet {
    std::array<HANDLE, 3> handles{INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE};
    bool ready = false;
    explicit CharacterArchiveSet(const std::array<ArchivePin, 3>& pins) {
        try {
            for (size_t i = 0; i < pins.size(); ++i) {
                handles[i] = OpenCharacterArchive(pins[i]);
                if (handles[i] == INVALID_HANDLE_VALUE) { Close(); return; }
            }
            ready = true;
        } catch (...) { Close(); }
    }
    void Close() {
        for (auto& handle : handles) {
            if (handle != INVALID_HANDLE_VALUE) CloseHandle(handle);
            handle = INVALID_HANDLE_VALUE;
        }
        ready = false;
    }
    ~CharacterArchiveSet() { Close(); }
};
}

bool DarkwatchCharacterContentReady() {
    // Call after mounting D: and before guest archive opens; retained locks force their read-only fallback.
    static const CharacterArchiveSet content(kCharacterArchives);
    return content.ready;
}

void DarkwatchCharacterInitialize(X86Context&, uint8_t*) {
    (void)DarkwatchCharacterContentReady();
}
