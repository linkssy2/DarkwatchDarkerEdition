#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <array>
#include "controls.h"
#include <cstring>

X86_EXTERN_FUNC(sub_0007CB4F);
X86_EXTERN_FUNC(sub_000B9204);

namespace {
struct CrouchEdge { uint32_t controller = 0; uint64_t epoch = 0, pressed = 0; bool held = false; };
std::array<CrouchEdge, 2> crouch_edges;
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage) - 1); page < at + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(T)); return true;
}

bool CrouchDown(const uint8_t* base, uint32_t map, uint32_t crouch, unsigned& port_out) {
    uint32_t manager = 0, self = 0, reference = 0, stack = 0;
    uint16_t count = 0;
    uint8_t enabled = 0;
    if (map < 0xC) return false;
    const uint32_t controller = map - 0xC;
    if (!Read(base, uint64_t(controller) + 8, self) || self != controller ||
        !Read(base, uint64_t(controller) + 0x10, reference) || reference != map ||
        !Read(base, 0x4AC174, manager) || !manager ||
        !Read(base, uint64_t(manager) + 0x120, enabled) || enabled != 1) return false;
    bool local = false;
    for (unsigned port = 0; port < 2; ++port) {
        uint32_t current = 0; uint8_t blocked = 0;
        if (!Read(base, uint64_t(manager) + 0xD4 + port * 0x10, current) ||
            !Read(base, uint64_t(manager) + 0x121 + port, blocked)) return false;
        if (current == controller && !blocked) { local = true; port_out = port; }
    }
    if (!local || !Read(base, uint64_t(controller) + 0x28, count) || !count || count > 32 ||
        !Read(base, uint64_t(controller) + 0x2C, stack) || !Span(base, stack, count * 4)) return false;
    // Native 1DDEDF visits the active maps from the top, stopping at continue=false.
    while (count--) {
        uint32_t bindings = 0, rows = 0; uint16_t size = 0; uint8_t continuation = 0;
        if (!Read(base, uint64_t(stack) + count * 4, bindings)) return false;
        if (!bindings) continue;
        if (!Read(base, bindings, size) || size > 128 ||
            !Read(base, uint64_t(bindings) + 4, rows) ||
            !Read(base, uint64_t(bindings) + 8, continuation) || continuation > 1 ||
            (size && !Span(base, rows, size * 0x40))) return false;
        for (unsigned i = 0; i < size; ++i) {
            const uint64_t row = uint64_t(rows) + i * 0x40;
            uint32_t key = 0, analog = 0, digital = 0, next = 0, state = 0, button = 0;
            if (!Read(base, row, key)) return false;
            if (key != crouch) continue;
            if (!Read(base, row + 0xC, analog) || analog ||
                !Read(base, row + 0x34, digital) || !digital ||
                !Read(base, uint64_t(digital) + 4, state) || state != 2 ||
                !Read(base, uint64_t(digital) + 8, button) || button >= 17 ||
                !Read(base, uint64_t(digital) + 0xC, next) || next) return false;
            uint8_t down = 0;
            if (!Read(base, uint64_t(controller) + 0x41 + button, down)) return false;
            if (down) return true;
        }
        if (!continuation) break;
    }
    return false;
}
}

// Native controller refresh can run twice before OnButton. Keep the edge for
// this published input frame rather than re-reading its overwritten XOR byte.
void DarkwatchGroundPoundInput(X86Context& ctx, uint8_t* base) {
    const auto frame = input::GetMouseSnapshot();
    uint32_t crouch = 0; unsigned port = 2;
    if (!Read(base, 0x4ACB68, crouch)) return;
    const bool down = CrouchDown(base, ctx.esi + 0xC, crouch, port);
    if (port >= 2) {
        for (auto& edge : crouch_edges) if (edge.controller == ctx.esi) edge = {};
        return;
    }
    auto& edge = crouch_edges[port];
    if (!frame.active || !frame.published_us) { edge = {}; return; }
    if (edge.controller != ctx.esi || edge.epoch != frame.active_epoch) {
        edge = {ctx.esi, frame.active_epoch, 0, down};
        return;
    }
    if (down && !edge.held) edge.pressed = frame.generation;
    if (!down) edge.pressed = 0;
    edge.held = down;
}

void DarkwatchGroundPound(X86Context& ctx, uint8_t* base) {
    if (ctx.eax & 0xFF) return; // Keep the original Interact decision.
    uint32_t type = 0, state = 0, owner = 0, linked = 0, name = 0, map = 0, crouch = 0;
    constexpr char action[] = "abortjump";
    if (!Read(base, ctx.esi, type) || type != 0x41F6E8 ||
        !Read(base, uint64_t(ctx.esi) + 4, state) || !state ||
        !Read(base, state, type) || (type != 0x420E50 && type != 0x4223A8) ||
        !Read(base, uint64_t(ctx.esi) + 0xC, name) || !name ||
        !Span(base, uint64_t(name) + 2, sizeof(action)) ||
        std::memcmp(base + uint64_t(name) + 2, action, sizeof(action)) ||
        !Read(base, uint64_t(ctx.esi) + 0x2C, owner) || !owner ||
        !Read(base, owner, type) || type != 0x41F878 ||
        !Read(base, uint64_t(state) + 0x40, linked) || linked != owner ||
        !Read(base, uint64_t(state) + 0x7C, linked) || linked != owner ||
        !Read(base, uint64_t(owner) + 0x30, map) || !map ||
        !Read(base, 0x4ACB68, crouch) || !crouch) return;
    unsigned port = 2;
    const auto frame = input::GetMouseSnapshot();
    if (!CrouchDown(base, map, crouch, port) || port >= 2 || !frame.active || !frame.published_us) return;
    const auto& edge = crouch_edges[port];
    if (edge.controller != map - 0xC || edge.epoch != frame.active_epoch ||
        !edge.pressed || edge.pressed != frame.generation) return;
    uint32_t buckets = 0, count = 0, rows = 0; uint16_t size = 0;
    if (!Read(base, uint64_t(map) + 8, buckets) ||
        !Read(base, uint64_t(map) + 0xC, count) || !count || count > 4096) return;
    const uint64_t bucket = uint64_t(buckets) + (crouch % count) * 8;
    if (!buckets || !Read(base, bucket, size) || size > 1024 ||
        !Read(base, bucket + 4, rows) || (size && !Span(base, rows, size * 8))) return;
    uint32_t actor = 0, flags = 0;
    constexpr uint32_t rune = 0x4233F4; // Original VampireJumpRune name.
    constexpr char rune_name[] = "VampireJumpRune";
    if (!Read(base, uint64_t(owner) + 0xC, actor) || !Span(base, actor, 0x9C) ||
        !Read(base, uint64_t(actor) + 0x90, flags) || (flags & 2) ||
        !Span(base, rune, sizeof(rune_name)) ||
        std::memcmp(base + rune, rune_name, sizeof(rune_name))) return;
    std::array<uint8_t, 1024> saved{};
    if (ctx.esp < saved.size() || !Read(base, ctx.esp - saved.size(), saved)) return;
    const uint32_t scratch = ctx.esp - uint32_t(saved.size());
    X86Context call = ctx;
    // The native query checks this player's collected rune pieces, not the
    // consumable power meter. It neither spends a charge nor activates a power.
    call.esp = ctx.esp - 32;
    const uint32_t power_args[]{0x21210E, actor, rune};
    std::memcpy(base + call.esp, power_args, sizeof(power_args));
    sub_000B9204(call, base);
    const bool unlocked = darkwatch::GetGroundPoundAnytime() || (call.eax & 0xFF) != 0;
    call = ctx;
    call.ecx = map; call.esp = ctx.esp - 32;
    const uint32_t args[]{0x21210E, crouch};
    std::memcpy(base + call.esp, args, sizeof(args));
    if (unlocked) sub_0007CB4F(call, base);
    std::memcpy(base + scratch, saved.data(), saved.size());
    if (unlocked && (call.eax & 0xFF)) ctx.eax = (ctx.eax & 0xFFFFFF00u) | 1u;
}
