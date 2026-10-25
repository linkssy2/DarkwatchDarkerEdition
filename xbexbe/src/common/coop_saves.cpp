#include "coop_saves.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_000CAE2D);
X86_EXTERN_FUNC(__imp__sub_000CAEB0);
X86_EXTERN_FUNC(__imp__sub_000CAF4C);
X86_EXTERN_FUNC(__imp__sub_000E5613);

namespace {
constexpr uint32_t kCoopName = 0x424A48; // Original "CoOp", separate from Profile 1..10.
constexpr uint32_t kStorage = 0x42C938, kCoopRecord = 0x4252C4;

bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(T)); return true;
}
void Put(uint8_t* base, uint32_t at, uint32_t value) {
    std::memcpy(base + at, &value, sizeof(value));
}
bool Storage(const uint8_t* base, uint32_t storage) {
    uint32_t type;
    return Read(base, storage, type) && type == kStorage;
}
bool Stack(const X86Context& ctx, const uint8_t* base) {
    return base == kernel::g_base && ctx.esp >= 0x4000 &&
        Span(base, uint64_t(ctx.esp) - 0x4000, 0x400C);
}
bool Database(const X86Context& ctx, const uint8_t* base, uint32_t& storage) {
    uint32_t app, database, count, type;
    return Stack(ctx, base) && Read(base, ctx.esp + 4, storage) && Storage(base, storage) &&
        Read(base, 0x4ACFBC, app) && Read(base, uint64_t(app) + 0x68, database) && database == ctx.ecx &&
        Span(base, database, 0x1C) && Read(base, database, count) && count == 10 &&
        Read(base, database + 8, type) && type == kCoopRecord;
}
// Calls use a private copy of the CPU context and scratch below the caller's
// frame. Native string/buffer destructors retain the original ownership rules.
bool Save(X86Context call, uint8_t* base, uint32_t database, uint32_t storage) {
    uint32_t dirty, state, first, second;
    const auto record = database + 8;
    if (!Read(base, record + 4, dirty) || !Read(base, record + 8, state)) return false;
    if (!dirty) return true;
    if (dirty > 2 || (dirty == 1 && (state != 2 ||
        !Read(base, record + 0xC, first) || !Read(base, record + 0x10, second) || first == second ||
        !Span(base, first, 0x6C) || !Span(base, second, 0x6C)))) return false;
    const auto scratch = call.esp - 0x100;
    call.esp = scratch - 0x20;
    Put(base, scratch, 0); Put(base, scratch + 4, 0);
    call.ecx = record; kernel::CallGuest(call, 0xC8C00, {scratch});
    kernel::CallGuest(call, 0xFB89D, {scratch + 4, 0x40000});
    uint32_t buffer = 0, name = 0;
    Read(base, scratch + 4, buffer); Read(base, scratch, name);
    bool ok = false;
    if (buffer && name) {
        call.ecx = record;
        // C915B consumes this buffer reference; a failed write retains dirty=1.
        ok = uint8_t(kernel::CallGuest(call, 0xC915B, {scratch, storage, buffer})) != 0;
    } else if (buffer) {
        call.ecx = buffer; kernel::CallGuest(call, 0x2172F1, {});
    }
    call.ecx = scratch; kernel::CallGuest(call, 0x11C1A, {});
    return ok;
}
bool Load(X86Context call, uint8_t* base, uint32_t database, uint32_t storage) {
    const auto record = database + 8, scratch = call.esp - 0x100, temporary = scratch + 0x10;
    call.esp = scratch - 0x20;
    Put(base, scratch, 0); Put(base, scratch + 4, 0);
    call.ecx = storage;
    const bool exists = uint8_t(kernel::CallGuest(call, 0xFC7FE, {kCoopName, scratch + 4})) != 0;
    uint32_t status = 0;
    if (!Read(base, scratch + 4, status) || status != 1) return false;
    if (!exists) {
        call.ecx = record; kernel::CallGuest(call, 0xC912C, {});
        return true;
    }
    call.ecx = record; kernel::CallGuest(call, 0xC8C00, {scratch});
    call.ecx = temporary; kernel::CallGuest(call, 0xC8A98, {});
    call.ecx = temporary;
    const bool ok = uint8_t(kernel::CallGuest(call, 0xC9274, {scratch, storage})) != 0;
    if (ok) {
        // Only replace the old in-memory pair after both native profiles load.
        call.ecx = record; kernel::CallGuest(call, 0xC912C, {});
        std::memcpy(base + record, base + temporary, 0x14);
        Put(base, temporary + 0xC, 0); Put(base, temporary + 0x10, 0);
    }
    call.ecx = temporary; kernel::CallGuest(call, 0xC912C, {});
    call.ecx = scratch; kernel::CallGuest(call, 0x11C1A, {});
    return ok;
}
}

X86_FUNC(sub_000CAE2D) {
    const auto entry = ctx;
    uint32_t storage = 0;
    const bool valid = Database(entry, base, storage);
    __imp__sub_000CAE2D(ctx, base);
    if (valid && !Save(entry, base, entry.ecx, storage)) ctx.eax &= ~0xFFu;
}
X86_FUNC(sub_000CAEB0) {
    const auto entry = ctx;
    uint32_t storage = 0;
    const bool valid = Database(entry, base, storage);
    __imp__sub_000CAEB0(ctx, base);
    if (valid && !Load(entry, base, entry.ecx, storage)) ctx.eax &= ~0xFFu;
}
X86_FUNC(sub_000CAF4C) {
    const auto entry = ctx;
    uint32_t storage = 0, status_at = 0;
    const bool valid = Stack(entry, base) && Read(base, entry.esp + 4, storage) && Storage(base, storage) &&
        Read(base, entry.esp + 8, status_at) && (!status_at || Span(base, status_at, 4));
    __imp__sub_000CAF4C(ctx, base);
    if (!valid || uint8_t(ctx.eax)) return;
    uint32_t status = 1;
    if (status_at && (!Read(base, status_at, status) || status != 1)) return;
    auto call = entry;
    call.ecx = storage;
    // A co-op-only installation must also enter the original load-profiles flow.
    const auto exists = uint8_t(kernel::CallGuest(call, 0xFC7FE, {kCoopName, status_at}));
    ctx.eax = (ctx.eax & ~0xFFu) | exists;
}

X86_FUNC(sub_000E5613) {
    uint32_t app, frontend, app_type, frontend_type;
    uint8_t reload, pending;
    // Saving can finish after C5424 checks its deferred reload, but before this
    // frame's frontend update. Wait for the original reload before choosing a profile page.
    if (base == kernel::g_base && Read(base, 0x4ACFBC, app) &&
        Read(base, app, app_type) && app_type == 0x424B3C &&
        Read(base, uint64_t(app) + 0x65, reload) && reload == 1 &&
        Read(base, 0x4AD664, frontend) && frontend == ctx.ecx &&
        Read(base, frontend, frontend_type) && frontend_type == 0x4296EC &&
        Read(base, uint64_t(frontend) + 0x68, pending) && pending == 1) {
        ctx.esp += 4; // Original void thiscall, no arguments.
        return;
    }
    __imp__sub_000E5613(ctx, base);
}
