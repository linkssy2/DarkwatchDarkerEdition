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
    {"D:\\packfile.pck", 143099169, "ceacf60e64cafc0d676fa5b03a0a11289811ba29a1bd7adcfbcea6582827466f"},
    {"D:\\LvlSingl.pck", 1792512951, "4897d56557d87584ed6804d9b4eab172ae959460e89f13715088bc0391d672b3"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};

#if defined(DARKWATCH_GRENADE_PAIR_FIXTURE)
static_assert(DARKWATCH_GRENADE_PAIR_FIXTURE == 20261029);
// Only the private pickup arrangement may replace the production archive pin.
constexpr auto kAdmittedCharacterArchives = [] {
    auto pins = kCharacterArchives;
    pins[0].size = 142404897;
    pins[0].sha256 = "8b8f1b9e3d0334a03ccbf8fb38d3d3a471374e3822aec37d597a0b1b7cd9a073";
    pins[1].size = 1792254903;
    pins[1].sha256 = "04878dcaf630a679a327460c72939d98f84140d2d42cf3a79492ccb1f9eea7a9";
    return pins;
}();
#else
constexpr auto& kAdmittedCharacterArchives = kCharacterArchives;
#endif

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
    static const CharacterArchiveSet content(kAdmittedCharacterArchives);
    return content.ready;
}

void DarkwatchCharacterInitialize(X86Context&, uint8_t*) {
    (void)DarkwatchCharacterContentReady();
}
