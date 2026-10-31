#include "graphics_view.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <algorithm>
#include <cmath>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_00016DF2);
X86_EXTERN_FUNC(__imp__sub_0009E86A);
X86_EXTERN_FUNC(__imp__sub_0006D7CA);
X86_EXTERN_FUNC(__imp__sub_00213677);
X86_EXTERN_FUNC(__imp__sub_001E4083);
X86_EXTERN_FUNC(__imp__sub_0021F60E);
X86_EXTERN_FUNC(__imp__sub_0021F57F);
X86_EXTERN_FUNC(__imp__sub_001430F0);
X86_EXTERN_FUNC(__imp__sub_00151040);
X86_EXTERN_FUNC(__imp__sub_000AB2C0);

namespace {
bool Span(const uint8_t* base, uint64_t at, uint64_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}

template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&value, base + at, sizeof(value)); return true;
}
bool KeepBody(const uint8_t* base, uint32_t timeout) {
    uint32_t type = 0, actor = 0, flags = 0, state = 0, list = 0;
    uint16_t count = 0; uint8_t removed = 0, fading = 0;
    if (!Read(base, timeout, type) || type != 0x41766C ||
        !Read(base, uint64_t(timeout) + 0xC, actor) || !actor ||
        !Read(base, uint64_t(actor) + 0x90, flags) || !(flags & 2) ||
        !Read(base, uint64_t(timeout) + 0x18, state) || !state ||
        !Read(base, uint64_t(state) + 4, removed) || removed ||
        !Read(base, uint64_t(state) + 5, fading) || fading ||
        !Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, count * 8)) return false;
    unsigned found = 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, component) || !Read(base, component, type)) return false;
        if (type == 0x4227A4) return false; // PlayerComponent: never change player death/respawn.
        unsigned bit = 0;
        if (type == 0x41766C) { if (component != timeout) return false; bit = 1; }
        if (type == 0x422674) bit = 2; // HealthComponent.
        if (type == 0x41F878) bit = 4; // CharacterStateMachineComponent.
        if (!bit) continue;
        if ((found & bit) || !Read(base, uint64_t(component) + 0xC, owner) || owner != actor) return false;
        found |= bit;
    }
    return found == 7;
}
uint32_t RetainedTimeout(const uint8_t* base, uint32_t actor) {
    uint32_t list = 0; uint16_t count = 0;
    if (!actor || !Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, count * 8)) return 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component = 0, type = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, component) || !Read(base, component, type)) return 0;
        if (type != 0x41766C) continue;
        return Read(base, uint64_t(component) + 0xC, owner) && owner == actor && KeepBody(base, component) ? component : 0;
    }
    return 0;
}
bool CorpsePhysicsCommand(const X86Context& ctx, const uint8_t* base) {
    uint32_t type = 0, csm = 0, actor = 0, name = 0, text = 0, state = 0;
    uint8_t parent = 0, started = 0;
    constexpr char command[] = "TurnRagdollOff";
    if (!Read(base, ctx.ecx, type) || type != 0x43F2A8 ||
        !Read(base, uint64_t(ctx.ecx) + 0x14, parent) || parent ||
        !Read(base, uint64_t(ctx.ecx) + 8, csm) || !Read(base, csm, type) || type != 0x41F878 ||
        !Read(base, uint64_t(csm) + 0xC, actor) ||
        !Read(base, uint64_t(ctx.esp) + 4, name) || !Read(base, name, text) || !text ||
        !Span(base, uint64_t(text) + 2, sizeof(command)) ||
        std::memcmp(base + uint64_t(text) + 2, command, sizeof(command))) return false;
    const auto timeout = RetainedTimeout(base, actor);
    return timeout && Read(base, uint64_t(timeout) + 0x18, state) &&
        Read(base, uint64_t(state) + 6, started) && started;
}
}

// Original HealthComponent marks death and broadcasts it before the CSM starts
// this corpse timeout. Hold only its fade/removal countdown: death events,
// scripted removal and level teardown remain native.
X86_FUNC(sub_00016DF2) {
    if (darkwatch::view::Snapshot().forever_ragdolls && Span(base, ctx.esp, 8) && KeepBody(base, ctx.ecx)) {
        ctx.esp += 8; // Original thiscall returns with ret 4.
        return;
    }
    __imp__sub_00016DF2(ctx, base);
}

// The corpse CSM starts its timeout and then turns its ragdoll off. Keep that
// existing physics instance; ordinary scripted messages and teardown bypass
// this CSM command hook, and native dormancy can still put bodies to sleep.
X86_FUNC(sub_00213677) {
    if (darkwatch::view::Snapshot().forever_ragdolls && Span(base, ctx.esp, 8) && CorpsePhysicsCommand(ctx, base)) {
        ctx.esp += 8; // Original thiscall returns with ret 4.
        return;
    }
    __imp__sub_00213677(ctx, base);
}

namespace {
thread_local bool retained_admission = false;
bool RetainedQuery(const uint8_t* base, uint32_t query) {
    uint32_t type = 0, csm = 0, actor = 0;
    // Original factory A36ED creates 420060; its condition slot is 9E86A.
    return Read(base, query, type) && type == 0x420060 &&
        Read(base, uint64_t(query) + 0x2C, csm) && Read(base, csm, type) && type == 0x41F878 &&
        Read(base, uint64_t(csm) + 0xC, actor) && RetainedTimeout(base, actor);
}
}

// Keep the native ragdoll-resource/type checks, but do not let retained corpses
// exhaust the old console count quota. Allocation and all counters stay native.
X86_FUNC(sub_0009E86A) {
    const bool previous = retained_admission;
    retained_admission = darkwatch::view::Snapshot().forever_ragdolls && RetainedQuery(base, ctx.ecx);
    __imp__sub_0009E86A(ctx, base);
    retained_admission = previous;
}

X86_FUNC(sub_0006D7CA) {
    uint32_t caller = 0, kind = 2;
    if (retained_admission && Read(base, ctx.esp, caller) && caller == 0x9E8A3 &&
        Read(base, uint64_t(ctx.esp) + 4, kind) && kind < 2) {
        ctx.eax = (uint32_t(ctx.eax) & 0xFFFFFF00u) | 1u;
        ctx.esp += 4;
        return;
    }
    __imp__sub_0006D7CA(ctx, base);
}

namespace {
uint32_t OwnedComponent(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    uint32_t list = 0, found = 0; uint16_t count = 0;
    if (!Read(base, uint64_t(actor) + 0x60, count) || !count || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, list) || !Span(base, list, count * 8)) return 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component = 0, type = 0, owner = 0;
        if (!Read(base, uint64_t(list) + i * 8 + 4, component) || !Read(base, component, type)) return 0;
        if (type != wanted) continue;
        if (found || !Read(base, uint64_t(component) + 0xC, owner) || owner != actor) return 0;
        found = component;
    }
    return found;
}
struct CollisionOwner { uint32_t body = 0, actor = 0, category = 0, kind = 0; };
bool CollisionProperties(const uint8_t* base, uint32_t collidable, CollisionOwner& result) {
    uint32_t properties = 0, count = 0;
    if (!Read(base, uint64_t(collidable) + 0x18, result.kind) || (result.kind != 1 && result.kind != 2) ||
        !Read(base, uint64_t(collidable) + 0x20, result.body) || !result.body ||
        !Read(base, uint64_t(result.body) + 0x30, properties) ||
        !Read(base, uint64_t(result.body) + 0x34, count) || !count || count > 64 ||
        !Span(base, properties, count * 8)) return false;
    unsigned found = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t key = 0, value = 0;
        Read(base, uint64_t(properties) + i * 8, key);
        Read(base, uint64_t(properties) + i * 8 + 4, value);
        if (key > 1) continue;
        if (found & (1u << key)) return false;
        found |= 1u << key;
        (key == 0 ? result.actor : result.category) = value;
    }
    return found == 3 && result.actor;
}
bool PlayerCorpseContact(const uint8_t* base, uint32_t player_shape, uint32_t corpse_shape) {
    CollisionOwner player, corpse;
    uint32_t flags = 0, wrapper = 0, impl = 0, collection = 0, bodies = 0, count = 0, world = 0;
    uint8_t active = 0;
    if (!CollisionProperties(base, player_shape, player) || !CollisionProperties(base, corpse_shape, corpse) ||
        player.actor == corpse.actor || corpse.kind != 1 || corpse.category != 0x200 ||
        // Native CSM/state setup adds these flags to the player's base category.
        ((player.category & ~0x02500000u) != 2 && (player.category & ~0x02500000u) != 3) ||
        !Read(base, uint64_t(player.actor) + 0x90, flags) || (flags & 2) ||
        !OwnedComponent(base, player.actor, 0x4227A4)) return false;
    auto animation = OwnedComponent(base, corpse.actor, 0x41D258);
    uint32_t rig_offset = 0x90;
    if (animation) {
        if (!RetainedTimeout(base, corpse.actor)) return false;
    } else {
        // Authored ragdoll props have no death timeout; never activate a scripted pose.
        animation = OwnedComponent(base, corpse.actor, 0x41D378);
        rig_offset = 0x1C0;
        if (OwnedComponent(base, corpse.actor, 0x4227A4) ||
            OwnedComponent(base, corpse.actor, 0x41F878)) return false;
    }
    if (!animation || !Read(base, uint64_t(animation) + rig_offset, wrapper) || !wrapper ||
        !Read(base, uint64_t(wrapper) + 4, impl) || !impl ||
        !Read(base, uint64_t(impl) + 0xC1, active) || !active ||
        !Read(base, uint64_t(impl) + 4, collection) || !collection ||
        !Read(base, uint64_t(collection) + 8, bodies) ||
        !Read(base, uint64_t(collection) + 0xC, count) || !count || count > 128 ||
        !Span(base, bodies, count * 4) ||
        !Read(base, uint64_t(corpse.body) + 8, world) || !world) return false;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t body = 0; Read(base, uint64_t(bodies) + i * 4, body);
        if (body == corpse.body) return true;
    }
    return false;
}
}

// Some original death paths leave positive numeric health behind the dead flag.
// Campaign scripts also use QueryHealth to wait for enemies, so a retained body
// must report zero current health. Keep the actual health/statistics and native
// death broadcasts unchanged; only adjust this query's current-health reply.
X86_FUNC(sub_000AB2C0) {
    uint32_t caller = 0, message = 0, type = 0, id = 0, actor = 0, state = 0;
    uint8_t started = 0;
    bool retained = false;
    if (darkwatch::view::Snapshot().forever_ragdolls &&
        Read(base, ctx.esp, caller) && caller == 0xACF40 &&
        Read(base, uint64_t(ctx.esp) + 4, message) && Span(base, message, 0x2C) &&
        Read(base, message, type) && type == 0x41E948 &&
        Read(base, uint64_t(message) + 4, id) && id == 0x12D &&
        Read(base, ctx.ecx, type) && type == 0x422674 &&
        Read(base, uint64_t(ctx.ecx) + 0xC, actor) &&
        OwnedComponent(base, actor, 0x422674) == ctx.ecx) {
        const auto timeout = RetainedTimeout(base, actor);
        retained = timeout && Read(base, uint64_t(timeout) + 0x18, state) &&
            Read(base, uint64_t(state) + 6, started) && started;
    }
    __imp__sub_000AB2C0(ctx, base);
    float health = 0;
    if (retained && Read(base, uint64_t(message) + 8, health) && health > 0) {
        health = 0;
        std::memcpy(base + uint64_t(message) + 8, &health, sizeof(health));
    }
}

// The original collision masks exclude corpses from the character controller.
// Admit only a live player/retained-body pair through the filter's local mask;
// every other native veto and the normal contact impulse/wake solver still run.
X86_FUNC(sub_001E4083) {
    uint32_t caller = 0, shape = 0, other = 0, expected = 0, output = 0;
    bool admit = false;
    if (Read(base, ctx.esp, caller) && (caller == 0x1E3EFD || caller == 0x1E3F1B) &&
        darkwatch::view::Snapshot().forever_ragdolls &&
        Read(base, uint64_t(ctx.esp) + 4, shape) && Read(base, uint64_t(ctx.esp) + 0xC, output) &&
        ctx.ebp >= 0x1C && output == ctx.ebp - (caller == 0x1E3EFD ? 0x1C : 0x18) &&
        Read(base, uint64_t(ctx.ebp) + (caller == 0x1E3EFD ? 0xC : 0x10), expected) && shape == expected &&
        Read(base, uint64_t(ctx.ebp) + (caller == 0x1E3EFD ? 0x10 : 0xC), other))
        admit = PlayerCorpseContact(base, shape, other);
    __imp__sub_001E4083(ctx, base);
    uint32_t mask = 0;
    if (admit && Read(base, output, mask)) {
        mask |= 0x200;
        std::memcpy(base + output, &mask, sizeof(mask));
    }
}

namespace {
void MatchCorpseContactDistance(const X86Context& ctx, uint8_t* base) {
    uint32_t caller = 0, point = 0, output = 0, type = 0, phantom = 0,
        manifold = 0, count = 0, shape = 0, body = 0, motion = 0;
    // 151040 has returned to 156591, with the producer's aligned frame restored.
    if (ctx.esp < 12 || ctx.ebp < 0x100 ||
        !Read(base, uint64_t(ctx.esp) - 12, caller) || caller != 0x156591 ||
        !darkwatch::view::Snapshot().forever_ragdolls ||
        uint64_t(ctx.esp) + 0x100 != (ctx.ebp & ~15u) ||
        !Read(base, uint64_t(ctx.esp) - 8, point) || point != uint64_t(ctx.esp) + 0x30 ||
        !Read(base, uint64_t(ctx.esp) - 4, output) || output != uint64_t(ctx.esp) + 0x70 ||
        !Read(base, ctx.esi, type) || type != 0x41E478 ||
        !Read(base, uint64_t(ctx.esi) + 0x30, phantom) || !phantom ||
        !Read(base, uint64_t(ctx.esi) + 0x64, manifold) ||
        !Read(base, uint64_t(ctx.esi) + 0x68, count) || !count || count > 128 ||
        ctx.ebx % 0x30 || ctx.ebx / 0x30 >= count ||
        !Read(base, uint64_t(manifold) + ctx.ebx + 0x28, shape) ||
        !Read(base, uint64_t(shape) + 0x20, body) || body != ctx.edi ||
        !Read(base, uint64_t(body) + 0x3C, motion) || motion != ctx.ecx ||
        uint64_t(phantom) + 0xC > UINT32_MAX || !PlayerCorpseContact(base, phantom + 0xC, shape)) return;
    float copied[4]{}, original[4]{}, margin = 0;
    if (!Read(base, point, copied) || !Read(base, uint64_t(manifold) + ctx.ebx, original) ||
        std::memcmp(copied, original, sizeof(copied)) ||
        !Read(base, uint64_t(ctx.esi) + 0x58, margin) || !std::isfinite(margin) || margin <= 0 ||
        !std::isfinite(copied[3]) || copied[3] <= 0) return;
    // The native constraint builder 155F10 measures from the controller's skin.
    // Use that same surface for pushing; keep real penetration and never invent
    // negative penetration while standing inside the skin. Shared contacts stay native.
    const float gap = std::max(copied[3] - margin, 0.0f);
    std::memcpy(base + uint64_t(point) + 12, &gap, sizeof(gap));
}

void BoostCorpsePush(const X86Context& ctx, uint8_t* base) {
    uint32_t caller = 0, output = 0, type = 0, phantom = 0, manifold = 0, count = 0,
        offset = 0, shape = 0, body = 0, motion = 0;
    if (!Read(base, ctx.esp, caller) || caller != 0x15672C ||
        !darkwatch::view::Snapshot().forever_ragdolls || ctx.ebp < 0x108 ||
        uint64_t(ctx.esp) + 0x108 != (ctx.ebp & ~15u) ||
        !Read(base, uint64_t(ctx.esp) + 4, output) || output != uint64_t(ctx.esp) + 0x23 ||
        !Read(base, ctx.esi, type) || type != 0x41E478 ||
        !Read(base, uint64_t(ctx.esi) + 0x30, phantom) || !phantom ||
        !Read(base, uint64_t(ctx.esi) + 0x64, manifold) ||
        !Read(base, uint64_t(ctx.esi) + 0x68, count) || !count || count > 128 ||
        !Read(base, uint64_t(ctx.esp) + 0x2C, offset) || offset % 0x30 || offset / 0x30 >= count ||
        !Read(base, uint64_t(manifold) + offset + 0x28, shape) ||
        !Read(base, uint64_t(shape) + 0x20, body) || body != ctx.ecx ||
        uint64_t(phantom) + 0xC > UINT32_MAX || !PlayerCorpseContact(base, phantom + 0xC, shape) ||
        !Read(base, uint64_t(body) + 0x3C, motion)) return;

    float impulse[3]{}, velocity[3]{}, inverse_mass = 0;
    if (!Read(base, uint64_t(ctx.esp) + 0x98, impulse) ||
        !Read(base, uint64_t(ctx.esi) + 0x10, velocity) ||
        !Read(base, uint64_t(motion) + 0x2C, inverse_mass) ||
        !std::isfinite(inverse_mass) || inverse_mass <= 0) return;
    double magnitude_squared = 0, into_body = 0;
    for (unsigned i = 0; i < 3; ++i) {
        if (!std::isfinite(impulse[i]) || !std::isfinite(velocity[i])) return;
        magnitude_squared += double(impulse[i]) * impulse[i];
        into_body += double(impulse[i]) * velocity[i];
    }
    if (into_body <= 0 || magnitude_squared <= 0) return;
    float closing = 0, effective_inverse_mass = 0, solved = 0, normal[3]{};
    if (!Read(base, uint64_t(ctx.esp) + 0x60, closing) || !std::isfinite(closing) || closing <= 0 ||
        !Read(base, uint64_t(ctx.esp) + 0x64, effective_inverse_mass) ||
        !std::isfinite(effective_inverse_mass) || effective_inverse_mass <= 0 ||
        !Read(base, uint64_t(ctx.esp) + 0x58, solved) || !std::isfinite(solved) || solved >= 0 ||
        !Read(base, uint64_t(ctx.esp) + 0x48, normal)) return;
    // Do not override a listener that attenuated or redirected the native impulse.
    for (unsigned i = 0; i < 3; ++i)
        if (!std::isfinite(normal[i]) || normal[i] * solved != impulse[i]) return;
    // Amplify closing motion, not the solver's inverse-dt separation correction.
    // Keep native larger hits and cap the resulting linear velocity change at 8.
    const auto requested_gain = (4.0 * 0.9 * closing / effective_inverse_mass) / -double(solved);
    const auto gain = std::max(1.0, std::min(requested_gain,
        8.0 / (std::sqrt(magnitude_squared) * inverse_mass)));
    for (auto& value : impulse) {
        value = float(value * gain);
        if (!std::isfinite(value)) return;
    }
    std::memcpy(base + ctx.esp + 0x98, impulse, sizeof(impulse));
}
}

X86_FUNC(sub_00151040) {
    __imp__sub_00151040(ctx, base);
    MatchCorpseContactDistance(ctx, base);
}

// This exact call follows the native contact listeners, before wake/applyPointImpulse.
X86_FUNC(sub_001430F0) {
    BoostCorpsePush(ctx, base);
    __imp__sub_001430F0(ctx, base);
}

namespace {
bool SpawnReference(const uint8_t* base, uint32_t entry) {
    uint32_t actor = 0, head = 0, first = 0, next = 0, previous = 0, value = 0;
    return Read(base, entry, actor) && actor &&
        Read(base, uint64_t(entry) + 4, head) && head &&
        Read(base, uint64_t(head) + 4, value) && value == actor &&
        Read(base, head, first) && first &&
        Read(base, uint64_t(first) + 0xC, value) && Span(base, value, 0x10) &&
        Read(base, uint64_t(entry) + 8, next) &&
        Read(base, uint64_t(next) + 0xC, value) && value == entry &&
        Read(base, uint64_t(entry) + 0xC, previous) &&
        Read(base, uint64_t(previous) + 8, value) && value == entry;
}
}

// The global NPC budget otherwise counts retained dead actors until deletion,
// preventing later encounter waves. Release only their budget references through
// the original unlink/swap routine; world references and physical bodies remain.
X86_FUNC(sub_0021F60E) {
    const uint32_t manager = ctx.ecx;
    __imp__sub_0021F60E(ctx, base);
    uint32_t original_manager = 0, entries = 0;
    uint16_t count = 0;
    if (!darkwatch::view::Snapshot().forever_ragdolls ||
        !Read(base, 0x4ACD20, original_manager) || manager != original_manager ||
        !Span(base, manager, 0x18) || !Read(base, uint64_t(manager) + 0x10, count) ||
        !count || count > 1024 || ctx.esp < 128 || !Span(base, uint64_t(ctx.esp) - 128, 128)) return;

    uint8_t previous[128];
    std::memcpy(previous, base + ctx.esp - sizeof(previous), sizeof(previous));
    struct Restore {
        uint8_t* target; const uint8_t* saved;
        ~Restore() { std::memcpy(target, saved, 128); }
    } restore{base + ctx.esp - sizeof(previous), previous};
    const unsigned limit = count;
    unsigned index = 0;
    for (unsigned visited = 0; visited < limit; ++visited) {
        if (!Read(base, uint64_t(manager) + 0x10, count) || count > limit || index >= count ||
            !Read(base, uint64_t(manager) + 0x14, entries) || !Span(base, entries, count * 0x14)) return;
        uint32_t actor = 0, state = 0; uint8_t started = 0;
        Read(base, uint64_t(entries) + index * 0x14, actor);
        const auto timeout = RetainedTimeout(base, actor);
        if (!timeout || !Read(base, uint64_t(timeout) + 0x18, state) ||
            !Read(base, uint64_t(state) + 6, started) || !started) { ++index; continue; }
        if (!SpawnReference(base, entries + index * 0x14) ||
            !SpawnReference(base, entries + (count - 1) * 0x14)) return;

        X86Context call = ctx;
        call.ecx = manager + 0x10;
        call.esp -= 8;
        const uint32_t args[]{0x21F631, index};
        std::memcpy(base + call.esp, args, sizeof(args));
        __imp__sub_0021F57F(call, base);
        uint16_t remaining = 0;
        if (!Read(base, uint64_t(manager) + 0x10, remaining) || remaining != count - 1) return;
    }
}
