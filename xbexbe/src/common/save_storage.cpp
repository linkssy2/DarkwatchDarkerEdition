#include "save_storage.h"
#include "kernel/crypto.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <fstream>
#include <mutex>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#else
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#endif

namespace darkwatch::saves {
namespace {
constexpr uint32_t kChapters = 17;
std::mutex storage_lock;

struct Reader {
    std::span<const uint8_t> data;
    size_t at = 0;
    bool ok = true;

    bool Skip(size_t size) {
        if (!ok || size > data.size() - at) return ok = false;
        at += size;
        return true;
    }
    uint32_t Number(size_t size) {
        if (!Skip(size)) return 0;
        uint32_t value = 0;
        for (size_t i = 0; i < size; ++i) value |= uint32_t(data[at - size + i]) << (8 * i);
        return value;
    }
    bool String() { const auto size = Number(2); return Skip(size); }

    bool Profile() {
        if (Number(4) != 0x50524F46 || Number(4) != 5 || !Skip(6) || !String() ||
            !Skip(13) || !String() || !Skip(6)) return false;
        std::array<uint32_t, kChapters> prefixes{};
        std::array<bool, kChapters> known{};
        for (unsigned bank = 0; bank < 2; ++bank) {
            if (Number(4) != 0x53544154 || Number(4) != 2) return false;
            const auto count = Number(4);
            if (!ok || count > kChapters) return false;
            std::array<bool, kChapters> seen{};
            for (uint32_t i = 0; i < count; ++i) {
                const auto chapter = Number(4), prefix = Number(4), version = Number(4);
                if (!ok || chapter >= kChapters || seen[chapter] || version != 5 ||
                    (known[chapter] && prefixes[chapter] != prefix) || !Skip(84)) return false;
                seen[chapter] = known[chapter] = true;
                prefixes[chapter] = prefix;
            }
        }
        if (!Skip(24) || Number(1) > 1 || Number(1) > 1) return false;
        const auto count = Number(2);
        for (uint32_t i = 0; i < count; ++i) {
            if (Number(4) >= kChapters || !String() || !Skip(8)) return false;
            const auto size = Number(4);
            if (!Skip(size)) return false;
        }
        return ok;
    }
};

enum class FileState { Missing, InvalidSize, Error, Ok };

FileState ReadBytes(const std::filesystem::path& path, std::vector<uint8_t>& data) {
    std::error_code error;
    const auto state = std::filesystem::symlink_status(path, error);
    if (state.type() == std::filesystem::file_type::not_found) return FileState::Missing;
    if (error || !std::filesystem::is_regular_file(state)) return FileState::Error;
    const auto size = std::filesystem::file_size(path, error);
    if (error) return FileState::Error;
    if (size < 28 || size > kMaxFileBytes) return FileState::InvalidSize;
    std::ifstream file(path, std::ios::binary);
    if (!file) return FileState::Error;
    data.resize(static_cast<size_t>(size));
    if (!file.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(size)) ||
        file.peek() != std::ifstream::traits_type::eof()) return FileState::Error;
    return FileState::Ok;
}

std::filesystem::path Backup(const std::filesystem::path& path) {
    auto result = path;
    result += ".bak";
    return result;
}

struct Temporary {
    std::filesystem::path path;
    bool owned = false;
    ~Temporary() {
        if (owned) { std::error_code error; std::filesystem::remove(path, error); }
    }
};

bool WriteTemporary(const std::filesystem::path& target, std::span<const uint8_t> data, Temporary& temporary) {
    static std::atomic<uint64_t> sequence{0};
#ifdef _WIN32
    const auto pid = GetCurrentProcessId();
#else
    const auto pid = getpid();
#endif
    temporary.path = target;
    temporary.path += ".tmp-" + std::to_string(pid) + "-" + std::to_string(sequence++);
#ifdef _WIN32
    const auto file = CreateFileW(temporary.path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                                  FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    temporary.owned = true;
    DWORD written = 0;
    bool ok = WriteFile(file, data.data(), static_cast<DWORD>(data.size()), &written, nullptr) && written == data.size();
    if (ok) ok = FlushFileBuffers(file) != 0;
    const bool closed = CloseHandle(file) != 0;
    return ok && closed;
#else
    const int file = open(temporary.path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (file < 0) return false;
    temporary.owned = true;
    size_t done = 0;
    while (done < data.size()) {
        const auto count = write(file, data.data() + done, data.size() - done);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        done += static_cast<size_t>(count);
    }
    int flushed;
    do { flushed = fsync(file); } while (flushed < 0 && errno == EINTR);
    const int closed = close(file);
    return done == data.size() && flushed == 0 && closed == 0;
#endif
}

bool Replace(const std::filesystem::path& source, const std::filesystem::path& target) {
#ifdef _WIN32
    return MoveFileExW(source.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
#else
    auto parent = target.parent_path();
    if (parent.empty()) parent = ".";
    const int directory = open(parent.c_str(), O_RDONLY | O_DIRECTORY);
    if (directory < 0) return false;
    const bool replaced = rename(source.c_str(), target.c_str()) == 0;
    // Rename is the commit point; a later directory-sync error cannot roll it back.
    if (replaced) fsync(directory);
    close(directory);
    return replaced;
#endif
}
} // namespace

bool Valid(std::span<const uint8_t> data) {
    if (data.size() < 28 || data.size() > kMaxFileBytes) return false;
    std::array<uint8_t, 16> key{};
    std::array<uint8_t, 20> digest{};
    const auto payload = data.first(data.size() - digest.size());
    crypto::Hmac(key.data(), key.size(), payload.data(), payload.size(), nullptr, 0, digest.data());
    uint8_t difference = 0;
    for (size_t i = 0; i < digest.size(); ++i) difference |= digest[i] ^ data[payload.size() + i];
    if (difference) return false;
    Reader reader{payload};
    if (!reader.Profile()) return false;
    if (reader.at != payload.size() && !reader.Profile()) return false;
    return reader.at == payload.size();
}

bool Read(const std::filesystem::path& path, std::vector<uint8_t>& data, bool* recovered) {
    std::lock_guard guard(storage_lock);
    if (recovered) *recovered = false;
    std::vector<uint8_t> value;
    const auto state = ReadBytes(path, value);
    if (state == FileState::Missing || state == FileState::Error) return false;
    if (state != FileState::Ok || !Valid(value)) {
        if (ReadBytes(Backup(path), value) != FileState::Ok || !Valid(value)) return false;
        if (recovered) *recovered = true;
    }
    data = std::move(value);
    return true;
}

bool Write(const std::filesystem::path& path, std::span<const uint8_t> data) {
    if (!Valid(data)) return false;
    std::lock_guard guard(storage_lock);
    std::vector<uint8_t> previous;
    const auto state = ReadBytes(path, previous);
    if (state == FileState::Error) return false;
    const bool valid_previous = state == FileState::Ok && Valid(previous);
    if (valid_previous && std::equal(previous.begin(), previous.end(), data.begin(), data.end())) return true;
    Temporary staged;
    if (!WriteTemporary(path, data, staged)) return false;
    if (valid_previous) {
        Temporary backup;
        if (!WriteTemporary(Backup(path), previous, backup) || !Replace(backup.path, Backup(path))) return false;
        backup.owned = false;
    }
    if (!Replace(staged.path, path)) return false;
    staged.owned = false;
    return true;
}
} // namespace darkwatch::saves
