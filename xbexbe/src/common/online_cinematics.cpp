#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

#ifndef XBE_RELEASE
#include <array>
#include <cstring>
#include "online_cinematic_resources.h"

extern bool DarkwatchOnlineCharacterWireEnabled(const X86Context&, const uint8_t*);
extern bool DarkwatchOnlineCampaignReady(const X86Context&, const uint8_t*);
extern bool DarkwatchOnlineQueueCinematic(const X86Context&, uint8_t*, uint32_t, uint32_t, uint32_t);
extern void DarkwatchOnlineEventRecord(const char*, uint32_t, uint32_t, uint32_t);
X86_EXTERN_FUNC(__imp__sub_00229DA9);
X86_EXTERN_FUNC(__imp__sub_00229D67);
X86_EXTERN_FUNC(__imp__sub_0021B43E);

namespace {
uint32_t active = 0, active_template = 0, host_resource = 0;
bool replay = false;
bool invalid_reported = false;
bool Invalid(const char* reason, uint32_t a, uint32_t b, uint32_t c) {
    if (!invalid_reported) DarkwatchOnlineEventRecord(reason, a, b, c);
    invalid_reported = true;
    return false;
}
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
uint32_t Resource(const uint8_t* base, uint32_t action) {
    if (!Span(base, action, 12) || Word(base, action) != 0x41D9FC) return 0;
    const uint64_t text = uint64_t(Word(base, action + 4)) + 2;
    char name[256]{};
    for (unsigned i = 0; i < sizeof(name); ++i) {
        if (!Span(base, text + i, 1)) return 0;
        char c = char(base[text + i]);
        name[i] = c == '\\' ? '/' : (c >= 'A' && c <= 'Z' ? char(c + 'a' - 'A') : c);
        if (!c) {
            for (unsigned n = 0; n < std::size(kCinematicResources); ++n) {
                const auto* resource = kCinematicResources[n];
                // Original score/Lua references omit the archive's .bxml suffix.
                if (!std::strcmp(name, resource) ||
                    (std::strlen(resource) == i + 5 && !std::memcmp(name, resource, i) &&
                     !std::strcmp(resource + i, ".bxml"))) return n + 1;
            }
            return 0;
        }
    }
    return 0;
}
bool Presentation(uint32_t type) {
    switch (type) {
    case 0x428C2C: case 0x428C20: // Start/EndCinematic
    case 0x429228: case 0x428C44: case 0x428C5C: case 0x428C8C: // Cameras
    case 0x428A44: case 0x428A7C: // Camera shake/rock; native "Zoom" loads a different area.
    case 0x428BC8: case 0x428CD4: case 0x428BDC: case 0x4289B4: // Fades/masks
    case 0x42F0B0: case 0x42D3D4: // Fog/clip plane
    case 0x428CF8: case 0x4289F0: case 0x428D04: case 0x428D88: // Music/environment/voice
    case 0x42D400: case 0x42D40C: case 0x42D418: case 0x42D3A0:
    case 0x42D424: case 0x42D3AC: return true;
    default: return false;
    }
}
bool BattleSound(const uint8_t* base, uint32_t wrapper, uint32_t event) {
    constexpr uint32_t battle_car_start = 166; // Appended to preserve existing wire resource IDs.
    if (Resource(base, Word(base, wrapper + 0x54)) != battle_car_start) return false;
    const auto config = Word(base, event + 0x54);
    if (Word(base, event) != 0x440614 || !Span(base, config, 16) || Word(base, config) != 0x423340) return false;
    uint16_t count = 0; std::memcpy(&count, base + config + 8, 2);
    const auto args = Word(base, config + 12);
    if (count != 3 || !Span(base, args, 12)) return false;
    const uint32_t tokens[]{Word(base, config + 4), Word(base, args), Word(base, args + 4), Word(base, args + 8)};
    const char* names[]{"scripts/playsoundfromactor", "a_fake_combat", "emitter", "os_05"};
    for (unsigned i = 0; i < 4; ++i) {
        const auto size = uint32_t(std::strlen(names[i]) + 1);
        if (!tokens[i] || !Span(base, uint64_t(tokens[i]) + 2, size) ||
            std::memcmp(base + tokens[i] + 2, names[i], size)) return false;
    }
    return true;
}
bool Prepare(uint8_t* base, uint32_t wrapper, uint32_t& skipped) {
    const auto seq = Word(base, uint64_t(wrapper) + 0x70);
    if (!Span(base, wrapper, 0x80) || Word(base, wrapper) != 0x440554 ||
        !Span(base, seq, 0xA0) || Word(base, seq) != 0x440E34)
        return Invalid("campaign-cinematic-sequence-invalid", wrapper, seq, Word(base, seq));
    const auto counts = Word(base, seq + 0x70), count = counts & 0xFFFF, table = Word(base, seq + 0x74);
    if (!count || count > 512 || (counts >> 16) < count || !Span(base, table, count * 4))
        return Invalid("campaign-cinematic-table-invalid", seq, counts, table);
    // Validate the whole privately allocated instance before changing its action flags.
    for (unsigned n = 0; n < count; ++n) {
        const auto row = Word(base, table + n * 4), desc = Word(base, row), event = Word(base, uint64_t(row) + 4);
        const auto type = Word(base, desc);
        // Dependent actions extend the original fixed-time descriptor with dependency/timeout fields.
        if (!Span(base, row, 8) || !Span(base, desc, type == 0x440E2C ? 0x21 : 0x18) ||
            (type != 0x440E24 && type != 0x440E2C))
            return Invalid("campaign-cinematic-descriptor-invalid", n, desc, Word(base, desc));
        if (!Span(base, event, 0x70) || Word(base, event + 0x54) != Word(base, desc + 4))
            return Invalid("campaign-cinematic-action-invalid", event, Word(base, event + 0x54), Word(base, desc + 4));
    }
    for (unsigned n = 0; n < count; ++n) {
        const auto row = Word(base, table + n * 4), event = Word(base, row + 4);
        if (!Presentation(Word(base, Word(base, event + 0x54))) && !BattleSound(base, wrapper, event)) {
            // Native sequence dispatch checks disabled at +5A, and completion at +58.
            // shortcut: nested sequences/actor actions stay host-owned until their proxy path is verified.
            base[event + 0x5A] = 1; base[event + 0x58] = 1; ++skipped;
        }
    }
    return true;
}
}

void DarkwatchOnlineCinematicReset() {
    active = active_template = host_resource = 0; replay = invalid_reported = false;
}
bool DarkwatchOnlineCinematicResource(uint32_t id) { return id && id <= std::size(kCinematicResources); }

bool DarkwatchOnlineCinematicApply(const X86Context& ctx, uint8_t* base, uint32_t kind, uint32_t value, uint32_t time) {
    if (!DarkwatchOnlineCampaignReady(ctx, base)) return false;
    X86Context call = ctx;
    if (kind == 0x10002) {
        replay = true;
        if (active && Span(base, active, 0x80) && Word(base, active) == 0x440554) {
            call.ecx = active; kernel::CallGuest(call, 0x244DEA, {});
        }
        kernel::CallGuest(call, 0x21B43E, {value, time});
        replay = false;
        DarkwatchOnlineEventRecord("campaign-cinematic-ended", value, time, active);
        return true;
    }
    if (kind != 0x10001 || !DarkwatchOnlineCinematicResource(value) || active) return false;
    if (ctx.esp < 1024 || !Span(base, uint64_t(ctx.esp) - 1024, 1024)) return false;
    // Triggers create their wrappers lazily. Resolve the receiver's own original resource,
    // with original interned-string ownership, instead of depending on its trigger firing.
    const auto action = kernel::CallGuest(call, 0x228CA4, {});
    if (!Span(base, action, 12) || Word(base, action) != 0x41D9FC) return false;
    const auto text = ctx.esp - 256;
    std::array<uint8_t, 256> saved;
    std::memcpy(saved.data(), base + text, saved.size());
    call.esp = ctx.esp - 512;
    std::strcpy(reinterpret_cast<char*>(base + text), kCinematicResources[value - 1]);
    call.ecx = action + 4; kernel::CallGuest(call, 0x138FA, {text});
    std::strcpy(reinterpret_cast<char*>(base + text), "WorldSpace");
    call.ecx = action + 8; kernel::CallGuest(call, 0x138FA, {text});
    std::memcpy(base + text, saved.data(), saved.size());
    call.ecx = action;
    const auto instance = kernel::CallGuest(call, 0x229D89, {});
    uint32_t skipped = 0;
    if (!instance || !Prepare(base, instance, skipped)) {
        if (instance) { call.ecx = instance; kernel::CallGuest(call, 0x229D67, {1}); }
        call.ecx = action; kernel::CallGuest(call, 0x100EAE, {1});
        return false;
    }
    active = instance; active_template = action;
    base[instance + 0x59] = 1; // Original event manager owns completion/destruction of this clone.
    replay = true; call.ecx = instance;
    kernel::CallGuest(call, 0x229DA9, {0});
    replay = false;
    DarkwatchOnlineEventRecord("campaign-cinematic-started", value, instance, skipped);
    return true;
}

X86_FUNC(sub_00229DA9) {
    if (!DarkwatchOnlineCharacterWireEnabled(ctx, base)) { __imp__sub_00229DA9(ctx, base); return; }
    const auto id = Span(base, ctx.ecx, 0x80) && Word(base, ctx.ecx) == 0x440554 ?
        Resource(base, Word(base, ctx.ecx + 0x54)) : 0;
    static unsigned observed = 0;
    if (id && !replay && observed++ < 256)
        DarkwatchOnlineEventRecord("campaign-cinematic-entry", id, Word(base, ctx.esp),
                                   DarkwatchOnlineCampaignReady(ctx, base));
    if (id && !replay && DarkwatchOnlineCampaignReady(ctx, base)) {
        X86Context call = ctx;
        const auto role = kernel::CallGuest(call, 0x186A30, {}) & 255;
        if (role == 2) {
            base[ctx.ecx + 0x58] = 1; ctx.esp += 8;
            DarkwatchOnlineEventRecord("campaign-cinematic-await-host", id, ctx.ecx, 0);
            return;
        }
        if (role == 1 && DarkwatchOnlineQueueCinematic(ctx, base, 0x10001, id, 0)) host_resource = id;
    }
    __imp__sub_00229DA9(ctx, base);
}
X86_FUNC(sub_00229D67) {
    const auto owned = ctx.ecx == active ? active_template : 0;
    if (owned) active = active_template = 0;
    __imp__sub_00229D67(ctx, base);
    if (owned) { X86Context call = ctx; call.ecx = owned; kernel::CallGuest(call, 0x100EAE, {1}); }
}
X86_FUNC(sub_0021B43E) {
    if (host_resource && !replay && DarkwatchOnlineCampaignReady(ctx, base) &&
        DarkwatchOnlineQueueCinematic(ctx, base, 0x10002, Word(base, uint64_t(ctx.esp) + 4), Word(base, uint64_t(ctx.esp) + 8)))
        host_resource = 0;
    __imp__sub_0021B43E(ctx, base);
}
#endif
