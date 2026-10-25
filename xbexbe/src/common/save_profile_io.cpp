#include "save_profile_io.h"
#include "save_storage.h"
#include "kernel/crypto.h"
#include "kernel/kernel.h"

#include <cstring>
#include <new>
#include <string>

X86_EXTERN_FUNC(__imp__sub_000FC840);
X86_EXTERN_FUNC(__imp__sub_000FC994);
X86_EXTERN_FUNC(__imp__sub_000FC7FE);
X86_EXTERN_FUNC(__imp__sub_000FC799);

namespace {
constexpr uint32_t kStorage = 0x4AD9E4, kVtable = 0x42C938, kDrive = 0x42CAB0;
constexpr uint32_t kScratch = 0x800;
using darkwatch::saves::kMaxPayloadBytes;
using darkwatch::saves::kSignatureBytes;

bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
bool String(const uint8_t* base, uint32_t at, size_t limit, std::string& value) {
    value.clear();
    for (size_t i = 0; i < limit; ++i) {
        if (!Span(base, uint64_t(at) + i, 1)) return false;
        const auto c = base[uint64_t(at) + i];
        if (!c) return true;
        value += char(c);
    }
    return false;
}
bool Slot(const std::string& name) {
    if (name == "CoOp" || name == "Profile 10") return true;
    return name.size() == 9 && name.compare(0, 8, "Profile ") == 0 && name[8] >= '1' && name[8] <= '9';
}
bool Frame(const X86Context& ctx, uint8_t* base, unsigned arguments) {
    return base == kernel::g_base && ctx.esp >= 0x8000 &&
        Span(base, uint64_t(ctx.esp) - 0x8000, 0x8000 + 4 + arguments * 4) &&
        ctx.ecx == kStorage && Span(base, kStorage, 4) && kernel::R32(kStorage) == kVtable;
}
std::filesystem::path Path(const std::string& directory, const std::string& slot) {
    // XCreateSaveGame / XFindSaveGame provide one container directly under U:.
    if (directory.size() < 5 || directory.size() + slot.size() >= 260 ||
        directory.compare(0, 3, "U:\\") || directory.back() != '\\') return {};
    const auto folder = directory.substr(3, directory.size() - 4);
    if (folder.empty() || folder == "." || folder == ".." ||
        folder.find_first_of("\\/:\0", 0, 4) != std::string::npos) return {};
    const auto path = std::filesystem::path(kernel::ResolvePath(directory + slot, 0));
    const auto root = std::filesystem::path(kernel::ResolvePath("U:\\", 0));
    if (path.empty() || root.empty()) return {};
    std::error_code error;
    const auto title = std::filesystem::weakly_canonical(root, error);
    if (error) return {};
    const auto container = std::filesystem::weakly_canonical(path.parent_path(), error);
    // The U-drive root may itself be a legitimate Proton link; a container may
    // not redirect writes outside that resolved title root or to another slot.
    if (error || container != title / path.parent_path().filename()) return {};
    return path;
}
enum class FoundFile { Missing, Found, Error };
FoundFile EnumerationEnd(X86Context& call) {
    const auto error = kernel::CallGuest(call, 0x159317, {});
    return error == 2 || error == 3 || error == 18 ? FoundFile::Missing : FoundFile::Error;
}
FoundFile Find(X86Context& call, uint8_t* base, uint32_t scratch, const std::string& slot,
               std::filesystem::path& path) {
    const auto handle = kernel::CallGuest(call, 0x159B6A, {kDrive, scratch});
    if (handle == 0xFFFFFFFF) return EnumerationEnd(call);
    struct Enumeration {
        X86Context& call; uint32_t handle;
        ~Enumeration() { kernel::CallGuest(call, 0x159CBB, {handle}); }
    } enumeration{call, handle};
    std::filesystem::path empty;
    do {
        std::string directory;
        if (!String(base, scratch + 0x140, 260, directory)) return FoundFile::Error;
        const auto candidate = Path(directory, slot);
        if (candidate.empty()) return FoundFile::Error;
        std::error_code error;
        const auto state = std::filesystem::symlink_status(candidate, error);
        if (error && error != std::errc::no_such_file_or_directory) return FoundFile::Error;
        // Do not find .bak alone: intentionally deleted slots stay deleted.
        if (std::filesystem::is_regular_file(state) && !error) {
            const auto size = std::filesystem::file_size(candidate, error);
            if (error) return FoundFile::Error;
            // The original size probe could create an empty slot in an earlier
            // CoOp container. Prefer the existing nonempty save without deleting
            // that artifact; a sole empty slot retains normal backup recovery.
            if (!size) {
                if (empty.empty()) empty = candidate;
                continue;
            }
            path = candidate;
            return FoundFile::Found;
        }
    } while (kernel::CallGuest(call, 0x159C74, {handle, scratch}));
    const auto end = EnumerationEnd(call);
    if (end == FoundFile::Missing && !empty.empty()) {
        path = std::move(empty);
        return FoundFile::Found;
    }
    return end;
}
void FailSize(X86Context& ctx, uint8_t* base) {
    if (base == kernel::g_base && Span(base, ctx.esp, 16)) {
        const auto status = kernel::R32(ctx.esp + 12);
        if (Span(base, status, 4)) kernel::W32(status, 0);
    }
    kernel::Return(ctx, 0xFFFFFFFF, 3);
}
void FailPresence(X86Context& ctx, uint8_t* base) {
    if (base == kernel::g_base && Span(base, ctx.esp, 12)) {
        const auto status = kernel::R32(ctx.esp + 8);
        if (Span(base, status, 4)) kernel::W32(status, 0);
    }
    kernel::Return(ctx, 0, 2);
}
void FailRead(X86Context& ctx, uint8_t* base) {
    if (base == kernel::g_base && Span(base, ctx.esp, 16)) {
        const auto output = kernel::R32(ctx.esp + 4), status = kernel::R32(ctx.esp + 12);
        if (Span(base, output, 4)) kernel::W32(output, 0);
        if (Span(base, status, 4)) kernel::W32(status, 0);
        kernel::Return(ctx, output, 3);
    } else kernel::Return(ctx, 0, 3);
}
void FailWrite(X86Context& ctx, uint8_t* base) {
    if (base == kernel::g_base && Span(base, ctx.esp, 20)) {
        const auto status = kernel::R32(ctx.esp + 16);
        if (Span(base, status, 4)) kernel::W32(status, 0);
    }
    kernel::Return(ctx, 0, 4);
}
} // namespace

X86_FUNC(sub_000FC799) try {
    if (!Frame(ctx, base, 3)) { FailSize(ctx, base); return; }
    const auto filename = kernel::R32(ctx.esp + 4), rounded = kernel::R32(ctx.esp + 8);
    const auto status = kernel::R32(ctx.esp + 12);
    std::string slot;
    if (!String(base, filename, 260, slot) || (status && !Span(base, status, 4))) {
        FailSize(ctx, base); return;
    }
    if (!Slot(slot)) { __imp__sub_000FC799(ctx, base); return; }
    auto call = ctx;
    const auto scratch = call.esp -= kScratch;
    std::filesystem::path path;
    const auto found = Find(call, base, scratch, slot, path);
    uint32_t size = 0xFFFFFFFF;
    if (found == FoundFile::Found) {
        std::error_code error;
        const auto bytes = std::filesystem::file_size(path, error);
        if (error || bytes > darkwatch::saves::kMaxFileBytes) { FailSize(ctx, base); return; }
        size = uint32_t(bytes);
        if (rounded) size = (size + 0x3FFFu) & ~0x3FFFu;
    }
    // Preserve native missing/rounding semantics, without FC658's create path.
    if (status) kernel::W32(status, found != FoundFile::Error);
    kernel::Return(ctx, size, 3);
} catch (const std::bad_alloc&) {
    FailSize(ctx, base);
} catch (const std::filesystem::filesystem_error&) {
    FailSize(ctx, base);
}

X86_FUNC(sub_000FC7FE) try {
    if (!Frame(ctx, base, 2)) { FailPresence(ctx, base); return; }
    const auto filename = kernel::R32(ctx.esp + 4), status = kernel::R32(ctx.esp + 8);
    std::string slot;
    if (!String(base, filename, 260, slot) || (status && !Span(base, status, 4))) {
        FailPresence(ctx, base); return;
    }
    if (!Slot(slot)) { __imp__sub_000FC7FE(ctx, base); return; }
    auto call = ctx;
    const auto scratch = call.esp -= kScratch;
    std::filesystem::path path;
    const auto found = Find(call, base, scratch, slot, path);
    if (status) kernel::W32(status, found != FoundFile::Error);
    kernel::Return(ctx, found == FoundFile::Found, 2);
} catch (const std::bad_alloc&) {
    FailPresence(ctx, base);
} catch (const std::filesystem::filesystem_error&) {
    FailPresence(ctx, base);
}

X86_FUNC(sub_000FC994) try {
    if (!Frame(ctx, base, 4)) { FailWrite(ctx, base); return; }
    const auto name = kernel::R32(ctx.esp + 4), filename = kernel::R32(ctx.esp + 8);
    const auto buffer = kernel::R32(ctx.esp + 12), status = kernel::R32(ctx.esp + 16);
    std::string slot, display_name;
    if (!String(base, filename, 260, slot)) { FailWrite(ctx, base); return; }
    if (!Slot(slot)) { __imp__sub_000FC994(ctx, base); return; }
    if ((status && !Span(base, status, 4)) || !String(base, name, 128, display_name) ||
        display_name.empty() || !Span(base, buffer, 0x14)) { FailWrite(ctx, base); return; }
    const auto size = kernel::R32(buffer + 12), data = kernel::R32(buffer + 16);
    if (size > kMaxPayloadBytes || size > kernel::R32(buffer + 8) || !Span(base, data, size)) {
        FailWrite(ctx, base); return;
    }
    std::vector<uint8_t> signed_data(base + data, base + data + size);
    signed_data.resize(size + kSignatureBytes);
    const uint8_t key[16]{};
    crypto::Hmac(key, sizeof(key), signed_data.data(), size, nullptr, 0, signed_data.data() + size);
    if (!darkwatch::saves::Valid(signed_data)) { FailWrite(ctx, base); return; }

    auto call = ctx;
    const auto scratch = call.esp -= kScratch;
    std::memset(base + scratch, 0, kScratch);
    call.ecx = kStorage;
    if (!kernel::CallGuest(call, 0xFC50B, {size + uint32_t(kSignatureBytes), 0, 0})) { FailWrite(ctx, base); return; }
    // Match the native byte-to-wide conversion, including non-ASCII player names.
    for (size_t i = 0; i < display_name.size(); ++i)
        kernel::W16(scratch + uint32_t(i * 2), uint8_t(display_name[i]));
    const auto directory_at = scratch + 0x208;
    if (kernel::CallGuest(call, 0x159837, {kDrive, scratch, 4, 1, directory_at, 256}) != 0) {
        FailWrite(ctx, base); return;
    }
    std::string directory;
    if (!String(base, directory_at, 256, directory)) { FailWrite(ctx, base); return; }
    const auto path = Path(directory, slot);
    if (path.empty() || !darkwatch::saves::Write(path, signed_data)) { FailWrite(ctx, base); return; }
    if (status) kernel::W32(status, 1);
    kernel::Return(ctx, 1, 4);
} catch (const std::bad_alloc&) {
    FailWrite(ctx, base);
} catch (const std::filesystem::filesystem_error&) {
    FailWrite(ctx, base);
}

X86_FUNC(sub_000FC840) try {
    if (!Frame(ctx, base, 3)) { FailRead(ctx, base); return; }
    const auto output = kernel::R32(ctx.esp + 4), filename = kernel::R32(ctx.esp + 8);
    const auto status = kernel::R32(ctx.esp + 12);
    std::string slot;
    if (!String(base, filename, 260, slot)) { FailRead(ctx, base); return; }
    if (!Slot(slot)) { __imp__sub_000FC840(ctx, base); return; }
    if (!Span(base, output, 4) || (status && !Span(base, status, 4))) { FailRead(ctx, base); return; }
    auto call = ctx;
    const auto scratch = call.esp -= kScratch;
    std::filesystem::path path;
    std::vector<uint8_t> bytes;
    if (Find(call, base, scratch, slot, path) != FoundFile::Found || !darkwatch::saves::Read(path, bytes)) {
        FailRead(ctx, base); return;
    }
    // FB89D owns one reference; FB910 reserves the entire signed payload.
    kernel::W32(output, 0);
    kernel::CallGuest(call, 0xFB89D, {output, uint32_t(bytes.size())});
    const auto buffer = kernel::R32(output);
    if (!buffer || !Span(base, buffer, 0x14)) { FailRead(ctx, base); return; }
    call.ecx = buffer;
    const auto data = kernel::CallGuest(call, 0xFB910, {uint32_t(bytes.size())});
    if (!Span(base, data, bytes.size())) {
        call.ecx = buffer;
        kernel::CallGuest(call, 0x2172F1, {});
        FailRead(ctx, base); return;
    }
    std::memcpy(base + data, bytes.data(), bytes.size());
    if (status) kernel::W32(status, 1);
    kernel::Return(ctx, output, 3);
} catch (const std::bad_alloc&) {
    FailRead(ctx, base);
} catch (const std::filesystem::filesystem_error&) {
    FailRead(ctx, base);
}
