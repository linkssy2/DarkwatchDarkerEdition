#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

#ifndef XBE_RELEASE
#include <cstdio>
#include <cstdlib>
#include <cstring>

// Original pair constructor/consumer and stream contract: campaign/named-event-original.json.
extern bool DarkwatchOnlineCampaignEventContext(const X86Context&, const uint8_t*);
extern void DarkwatchOnlineEventRecord(const char*, uint32_t, uint32_t, uint32_t);
extern bool DarkwatchOnlineCampaignControl(const X86Context&, uint8_t*);
extern bool DarkwatchOnlineStoryControl(const X86Context&, uint8_t*);
X86_EXTERN_FUNC(__imp__sub_00218335);
X86_EXTERN_FUNC(__imp__sub_0001271B);
X86_EXTERN_FUNC(__imp__sub_00011A20);
X86_EXTERN_FUNC(__imp__sub_0024AF33);

namespace {
uint32_t pair_factory = 0;
bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    if (base != kernel::g_base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~uint64_t(mem::kPage - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
uint32_t Word(const uint8_t* base, uint64_t at) {
    uint32_t value = 0;
    if (Span(base, at, 4)) std::memcpy(&value, base + at, 4);
    return value;
}
void Put(uint8_t* base, uint32_t at, uint32_t value) { std::memcpy(base + at, &value, 4); }
bool Symbol(const uint8_t* base, uint32_t id, uint32_t& token) {
    token = 0;
    if (id == ~0u) return true;
    const auto count = Word(base, 0x4B7850), table = Word(base, 0x4B7854);
    if (!count || count > 65536 || id >= count || !Span(base, uint64_t(table) + id * 4, 4)) return false;
    token = Word(base, uint64_t(table) + id * 4);
    if (!Span(base, token, 3)) return false;
    for (unsigned i = 2; i < 258; ++i) {
        if (!Span(base, uint64_t(token) + i, 1)) return false;
        if (!base[token + i]) return true;
    }
    return false;
}
bool Ours(const X86Context& ctx, const uint8_t* base) {
    return pair_factory && ctx.ecx == pair_factory && Word(base, pair_factory) == 0x4164A0;
}
[[noreturn]] void InvalidPair(uint32_t event, uint32_t a, uint32_t b) {
    DarkwatchOnlineEventRecord("campaign-named-event-invalid", event, a, b);
    std::fputs("Online campaign named-event contract failed; see the diagnostic trace.\n", stderr);
    std::fflush(stderr);
    std::_Exit(3);
}
}

X86_FUNC(sub_00218335) {
    const auto registry = ctx.ecx, id = Word(base, uint64_t(ctx.esp) + 4);
    __imp__sub_00218335(ctx, base);
    if (ctx.eax || id != 0x49 || registry != Word(base, 0x4AC120) || !registry ||
        !DarkwatchOnlineCampaignEventContext(ctx, base)) return;
    // Reuse the native factory slots; identify our instance without modifying the original registry.
    if (!pair_factory) {
        pair_factory = mem::AllocSystem(4);
        if (!pair_factory) InvalidPair(id, 0, 0);
        Put(base, pair_factory, 0x4164A0);
    }
    ctx.eax = pair_factory;
}
X86_FUNC(sub_0001271B) {
    const bool pair = Ours(ctx, base);
    __imp__sub_0001271B(ctx, base);
    if (!pair || !ctx.eax) return;
    // The existing allocation is larger than the two-string event; its fields are already empty.
    if (!Span(base, ctx.eax, 0x1C)) InvalidPair(ctx.eax, 0, 0);
    Put(base, ctx.eax, 0x43F3FC);
    Put(base, ctx.eax + 4, 0x49);
}
X86_FUNC(sub_00011A20) {
    if (!Ours(ctx, base)) { __imp__sub_00011A20(ctx, base); return; }
    const auto stream = Word(base, uint64_t(ctx.esp) + 4), event = Word(base, uint64_t(ctx.esp) + 8);
    if (!Span(base, stream, 0x18) || Word(base, stream) != 0x443528 ||
        !Span(base, event, 0x10) || Word(base, event) != 0x43F3FC || Word(base, event + 4) != 0x49 ||
        ctx.esp < 0x1000 || !Span(base, ctx.esp - 0x1000, 0x1000)) InvalidPair(event, stream, 0);
    const auto temporary = ctx.esp - 32;
    X86Context call = ctx;
    call.esp = temporary - 16;
    uint32_t ids[2]{~0u, ~0u}, tokens[2]{};
    const bool writing = Word(base, stream + 8) != 0;
    if (writing) {
        for (unsigned i = 0; i < 2; ++i) {
            call.ecx = 0;
            ids[i] = kernel::CallGuest(call, 0x217EBE, {event + 8 + i * 4});
            if (!Symbol(base, ids[i], tokens[i]) ||
                (Word(base, event + 8 + i * 4) && !tokens[i])) InvalidPair(event, ids[0], ids[1]);
        }
    }
    for (unsigned i = 0; i < 2; ++i) {
        Put(base, temporary, ids[i]);
        call.ecx = 0;
        kernel::CallGuest(call, 0x173CC, {stream, temporary});
        ids[i] = Word(base, temporary);
    }
    if (!writing) {
        if (!Symbol(base, ids[0], tokens[0]) || !Symbol(base, ids[1], tokens[1]))
            InvalidPair(event, ids[0], ids[1]);
        for (unsigned i = 0; i < 2; ++i) {
            Put(base, temporary, tokens[i]);
            call.ecx = event + 8 + i * 4;
            kernel::CallGuest(call, 0x129DF, {temporary});
        }
    }
    static unsigned counts[2]{};
    const auto count = ++counts[writing];
    if ((count & (count - 1)) == 0)
        DarkwatchOnlineEventRecord(writing ? "campaign-named-event-sent" : "campaign-named-event-received",
                                   ids[0], ids[1], count);
    ctx.esp += 12;
}
X86_FUNC(sub_0024AF33) {
    if (DarkwatchOnlineStoryControl(ctx, base)) { ctx.esp += 12; return; }
    if (DarkwatchOnlineCampaignControl(ctx, base)) { ctx.esp += 12; return; }
    // Native 24BB32 decodes two bytes; the upper half of its stack slot is unspecified.
    if (uint16_t(Word(base, uint64_t(ctx.esp) + 4)) == 0x49 && DarkwatchOnlineCampaignEventContext(ctx, base)) {
        const auto buffer = Word(base, uint64_t(ctx.esp) + 8), data = Word(base, uint64_t(buffer) + 4);
        uint16_t size = 0;
        if (Span(base, buffer, 8)) std::memcpy(&size, base + buffer, 2);
        uint32_t tokens[2]{};
        if (size != 8 || !Span(base, data, 8) ||
            !Symbol(base, Word(base, data), tokens[0]) || !Symbol(base, Word(base, uint64_t(data) + 4), tokens[1])) {
            DarkwatchOnlineEventRecord("campaign-named-event-rejected", buffer, size, data);
            ctx.esp += 12;
            return;
        }
    }
    __imp__sub_0024AF33(ctx, base);
}
#endif
