#include "character_runtime.h"
#include "kernel/memory.h"
#include <cstring>

namespace {
bool Failed(const char** failure, const char* reason) {
    if (failure) *failure = reason;
    return false;
}
bool Span(const uint8_t* base, uint64_t at, uint32_t bytes) {
    if (!base || !at || !bytes || at + bytes > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage) - 1); page < at + bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base + at, sizeof(value)); return true;
}
template<size_t N> bool Text(const uint8_t* base, uint32_t ref, const char (&expected)[N]) {
    if (!ref || !Span(base, uint64_t(ref) + 2, N)) return false;
    for (size_t i = 0; i < N; ++i) {
        char ch = char(base[uint64_t(ref) + 2 + i]);
        if (ch >= 'A' && ch <= 'Z') ch += 'a' - 'A';
        if (ch == '\\') ch = '/';
        if (ch != expected[i]) return false;
    }
    return true;
}
// 23C644 uses interned-name keys; 1006AF uses request IDs. Both maps have 8-byte rows.
bool LayoutBank(const uint8_t* base, uint32_t layout, uint32_t& found) {
    uint32_t buckets, count, total, seen = 0;
    found = 0;
    if (!Read(base, uint64_t(layout) + 4, buckets) || !Read(base, uint64_t(layout) + 8, count) ||
        !Read(base, uint64_t(layout) + 12, total) || count > 512 || total > 4096 ||
        (!count ? total != 0 : !Span(base, buckets, count * 8))) return false;
    for (unsigned i = 0; i < count; ++i) {
        uint16_t size; uint32_t rows;
        if (!Read(base, uint64_t(buckets) + i * 8, size) ||
            !Read(base, uint64_t(buckets) + i * 8 + 4, rows) || size > total - seen ||
            (size && !Span(base, rows, size * 8))) return false;
        seen += size;
        for (unsigned j = 0; j < size; ++j) {
            uint32_t key, record;
            if (!Read(base, uint64_t(rows) + j * 8, key) || !Read(base, uint64_t(rows) + j * 8 + 4, record) ||
                !key || (key >> 2) % count != i) return false;
            if (Text(base, key, "cassidy")) {
                if (found || !record) return false;
                found = record;
            }
        }
    }
    return seen == total;
}
uint32_t LoadedBank(const uint8_t* base, uint32_t loader, uint32_t id) {
    uint32_t buckets, count, rows, total, found = 0; uint16_t size;
    if (!id || !Read(base, uint64_t(loader) + 4, buckets) || !Read(base, uint64_t(loader) + 8, count) ||
        !Read(base, uint64_t(loader) + 12, total) || !count || count > 512 || !total || total > 4096 ||
        !Span(base, buckets, count * 8)) return 0;
    const uint64_t bucket = uint64_t(buckets) + (id % count) * 8;
    if (!Read(base, bucket, size) || !Read(base, bucket + 4, rows) || size > total ||
        (size && !Span(base, rows, size * 8))) return 0;
    for (unsigned i = 0; i < size; ++i) {
        uint32_t key, bank;
        if (!Read(base, uint64_t(rows) + i * 8, key) || !Read(base, uint64_t(rows) + i * 8 + 4, bank)) return 0;
        if (key == id) {if (found || !bank) return 0; found = bank;}
    }
    return found;
}
bool Resident(const uint8_t* base, uint32_t loader, uint32_t record, const char** failure) {
    uint32_t type, name, file, definition, refs, id, bank;
    uint8_t preload;
    if (!Read(base, record, type) || type != 0x43ED18 ||
        !Read(base, uint64_t(record) + 4, name) || !Text(base, name, "cassidy") ||
        !Read(base, uint64_t(record) + 8, file) || !Text(base, file, "cassidy"))
        return Failed(failure, "audio bank entry");
    if (!Read(base, uint64_t(record) + 12, preload) || preload != 1 ||
        !Read(base, uint64_t(record) + 20, refs) || !refs || refs > INT32_MAX)
        return Failed(failure, "audio bank preload ownership");
    if (!Read(base, uint64_t(record) + 16, definition) || !definition ||
        !Read(base, definition, type) || type != 0x43ED44)
        return Failed(failure, "audio bank definition");
    if (!Read(base, uint64_t(definition) + 4, id) || !(bank = LoadedBank(base, loader, id)))
        return Failed(failure, "audio bank request not resident");
    uint32_t state, owned_id, xsb, stream_list, handle, path; uint16_t streams;
    if (!Read(base, bank, type) || type != 0x43EDD4 ||
        !Read(base, uint64_t(bank) + 4, owned_id) || owned_id != id ||
        !Read(base, uint64_t(bank) + 12, path) || !Text(base, path, "audio/cassidy/cassidy.xsb"))
        return Failed(failure, "audio loaded bank identity");
    if (!Read(base, uint64_t(bank) + 8, state) || state != 2)
        return Failed(failure, "audio bank pending or failed");
    if (!Read(base, uint64_t(bank) + 0x90, xsb) || !xsb)
        return Failed(failure, "audio soundbank not ready");
    if (!Read(base, uint64_t(bank) + 0x98, streams) || !streams || streams > 64 ||
        !Read(base, uint64_t(bank) + 0x9C, stream_list) || !Span(base, stream_list, streams * 4))
        return Failed(failure, "audio stream list not ready");
    for (unsigned i = 0; i < streams; ++i)
        if (!Read(base, uint64_t(stream_list) + i * 4, handle) || !handle)
            return Failed(failure, "audio stream handle not ready");
    return LoadedBank(base, loader, id) == bank || Failed(failure, "audio bank ownership changed");
}
} // namespace

bool DarkwatchCharacterAudioReady(uint8_t* base, const char** failure) {
    if (failure) *failure = nullptr;
    uint32_t audio, loader, type, engine, node, count;
    if (!Read(base, 0x4AD2FC, audio) || !audio || !Read(base, audio, type) || type != 0x43E4B0 ||
        !Read(base, uint64_t(audio) + 0x400, engine) || !engine)
        return Failed(failure, "audio manager or engine");
    if (!Read(base, 0x4B4F80, loader) || !loader || !Read(base, loader, type) || type != 0x43EDFC)
        return Failed(failure, "audio bank loader");
    if (!Read(base, uint64_t(audio) + 0x218, node) ||
        !Read(base, uint64_t(audio) + 0x220, count) || !count || count > 64)
        return Failed(failure, "audio layout list");
    // Follow 2054F7's priority. A later ready bank must not hide an earlier loading bank.
    for (unsigned i = 0; i < count && node; ++i) {
        uint32_t layout, next, record; uint8_t active;
        if (!Read(base, node, layout) || !layout || !Read(base, uint64_t(node) + 4, next) || next == node ||
            !Read(base, layout, type) || type != 0x43E494 ||
            !Read(base, uint64_t(layout) + 0x10, active))
            return Failed(failure, "audio layout identity");
        if (active) {
            if (!LayoutBank(base, layout, record)) return Failed(failure, "audio layout bank map");
            if (record) {
                // The preloaded layout retains this bank until 20D0A0 clears active before unloading.
                uint32_t current_audio, current_loader;
                if (!Resident(base, loader, record, failure)) return false;
                if (!Read(base, uint64_t(layout) + 0x10, active) || !active ||
                    !Read(base, 0x4AD2FC, current_audio) || current_audio != audio ||
                    !Read(base, 0x4B4F80, current_loader) || current_loader != loader)
                    return Failed(failure, "audio layout ownership changed");
                return true;
            }
        }
        node = next;
    }
    return Failed(failure, "audio Cassidy bank absent from active layouts");
}
