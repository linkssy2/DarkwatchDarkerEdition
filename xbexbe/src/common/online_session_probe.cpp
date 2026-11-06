#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

// Original behavior verified in private regression evidence.
#ifndef XBE_RELEASE
#include "app/app.h"
#include "online_session_url.h"
#include "online_characters.h"
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <mutex>
#include <string>
#include <thread>

X86_EXTERN_FUNC(__imp__sub_000CD3F8);
X86_EXTERN_FUNC(__imp__sub_001A7390);
X86_EXTERN_FUNC(__imp__sub_0001B54C);
X86_EXTERN_FUNC(__imp__sub_00179B00);
X86_EXTERN_FUNC(__imp__sub_0017E850);
X86_EXTERN_FUNC(__imp__sub_0016DF20);
X86_EXTERN_FUNC(__imp__sub_0018D1B0);
X86_EXTERN_FUNC(__imp__sub_0016EEC0);
X86_EXTERN_FUNC(__imp__sub_0016E530);
X86_EXTERN_FUNC(__imp__sub_001C1D77);
X86_EXTERN_FUNC(__imp__sub_001C1799);
X86_EXTERN_FUNC(__imp__sub_000C326C);
X86_EXTERN_FUNC(__imp__sub_000C591E);
X86_EXTERN_FUNC(__imp__sub_001EB3D6);
X86_EXTERN_FUNC(__imp__sub_000CBA42);
X86_EXTERN_FUNC(__imp__sub_0005FC3B);
X86_EXTERN_FUNC(__imp__sub_000C244F);
X86_EXTERN_FUNC(__imp__sub_000C224E);
X86_EXTERN_FUNC(__imp__sub_00215805);
X86_EXTERN_FUNC(__imp__sub_000AC756);
X86_EXTERN_FUNC(__imp__sub_0009C8BC);
X86_EXTERN_FUNC(__imp__sub_00028291);
X86_EXTERN_FUNC(__imp__sub_00024DEB);
X86_EXTERN_FUNC(__imp__sub_0002C6DB);
X86_EXTERN_FUNC(__imp__sub_0002A359);
X86_EXTERN_FUNC(__imp__sub_0002A42E);
X86_EXTERN_FUNC(__imp__sub_0002A7FF);
extern bool DarkwatchOnlineCampaignLoaded(const X86Context&, const uint8_t*);
extern bool DarkwatchOnlineCampaignReady(const X86Context&, const uint8_t*);
extern void DarkwatchOnlineCampaignLoadTick(const X86Context&, uint8_t*);

namespace {
using Clock = std::chrono::steady_clock;
struct Probe {
    FILE* log = nullptr;
    bool thread_bound = false;
    bool registered_channels = false;
    bool participant_attempted = false;
    bool campaign = false, title_online = false;
    bool position_interval_owned = false;
    bool receive_delay_owned = false;
    bool position_error_checked = false, position_error_owned = false;
    unsigned blend_floors_owned = 0;
    bool movie_pumping = false;
    bool spawn_waiting = false;
    unsigned movie_passes = 0;
    unsigned coop_paths_seen = 0;
    unsigned story_paths_seen = 0;
    unsigned campaign_stage = 0, loader_state = ~0u;
    uint32_t game = 0, session = 0;
    std::atomic<bool> loading{false};
    int role = 0, completion = -1;
    std::atomic<int> phase{0};
    std::atomic<bool> creating{false};
    std::atomic<bool> resolving{false};
    unsigned records = 0, queries = 0;
    uint32_t scratch = 0, thread = 0, manager = 0, participant = 0;
    std::atomic<uint32_t> lan{0};
    Clock::time_point started{}, changed{}, query{}, sampled{};
    Clock::time_point movie_sampled{}, actors_sampled{};
    std::mutex mutex;
    std::string discovered;
};
Probe probe;
constexpr uint32_t kBlendFloors[] = {0x4AD45C, 0x4AD440}; // Position and rotation.
// Native squared error polynomial, scaled by 1/16 for four times finer movement updates.
constexpr uint32_t kPositionError[][3] = {
    {0x4AD468, 0x3C23D70B, 0x3A23D70B}, {0x4AD46C, 0x3BEBEDFA, 0x39EBEDFA},
    {0x4AD470, 0x3AA9DE8A, 0x38A9DE8A}, {0x4AD484, 0x3F800000, 0x3D800000},
};
bool Enabled() {
    static const bool enabled = [] {
        const char* path = std::getenv("DARKWATCH_ONLINE_SESSION_PROBE");
        const int role = app::Instance();
        if (!path || !*path || (role != 1 && role != 2)) return false;
        probe.log = std::fopen(path, "wb");
        if (!probe.log) return false;
        probe.role = role; probe.started = probe.changed = Clock::now();
        const char* campaign = std::getenv("DARKWATCH_ONLINE_CAMPAIGN_PROBE");
        probe.campaign = campaign && std::strcmp(campaign, "1") == 0;
        return true;
    }();
    return enabled;
}
bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    if (base != kernel::g_base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~uint64_t(mem::kPage - 1); page < at + size; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& out) {
    if (!Span(base, at, sizeof(T))) return false;
    std::memcpy(&out, base + at, sizeof(T)); return true;
}
uint32_t Word(const uint8_t* base, uint64_t at) {
    uint32_t value = 0; Read(base, at, value); return value;
}
bool ProofCampaignTemplate(const uint8_t* base, uint32_t token) {
    // These private clones enroll only the five audited opening-carriage actors.
    constexpr char reaper[] = "DwOnlineProofReaper", regulator[] = "DwOnlineProofRegulator";
    const auto text = uint64_t(token) + 2;
    return token && ((Span(base, text, sizeof(reaper)) && !std::memcmp(base + text, reaper, sizeof(reaper))) ||
                     (Span(base, text, sizeof(regulator)) && !std::memcmp(base + text, regulator, sizeof(regulator))));
}
void Put(uint8_t* base, uint32_t at, uint32_t value) { std::memcpy(base + at, &value, 4); }
bool PositionErrorMatches(const uint8_t* base, bool adjusted) {
    if (!Span(base, 0x4AD468, 32) || Word(base, 0x4AD474) || Word(base, 0x4AD478) ||
        Word(base, 0x4AD480) != 2) return false;
    for (const auto& field : kPositionError)
        if (Word(base, field[0]) != field[adjusted ? 2 : 1]) return false;
    return true;
}
void TightenPositionError(uint8_t* base) {
    uint8_t initialized = 0;
    if (probe.position_error_checked || !Read(base, 0x4AD44C, initialized) || initialized != 1) return;
    probe.position_error_checked = true;
    if (!PositionErrorMatches(base, false)) return;
    for (const auto& field : kPositionError) Put(base, field[0], field[2]);
    probe.position_error_owned = true;
}
int ChannelCallback(const uint8_t* base) {
    const auto sentinel = Word(base, 0x4AF78C), count = Word(base, 0x4AF790);
    if (!sentinel || count > 128 || !Span(base, sentinel, 12)) return -1;
    auto node = Word(base, sentinel);
    auto previous = sentinel;
    bool found = false;
    for (unsigned i = 0; i < count; ++i) {
        if (!node || node == sentinel || !Span(base, node, 12) || Word(base, uint64_t(node) + 4) != previous) return -1;
        found |= Word(base, uint64_t(node) + 8) == 0x1C4E4D;
        previous = node;
        node = Word(base, node);
    }
    return node == sentinel && Word(base, uint64_t(sentinel) + 4) == previous ? int(found) : -1;
}
bool String(const uint8_t* base, uint32_t at, std::string& out) {
    out.clear();
    for (unsigned i = 0; i <= 2048; ++i) {
        char c;
        if (!Read(base, uint64_t(at) + i, c)) return false;
        if (!c) return true;
        if (i == 2048 || c < 32 || c > 126) return false;
        out.push_back(c);
    }
    return false;
}
void Record(const char* event, uint32_t a = 0, uint32_t b = 0, uint32_t c = 0) {
    std::lock_guard lock(probe.mutex);
    if (probe.records++ >= (probe.campaign ? 32768u : 256u)) return;
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - probe.started).count();
    std::fprintf(probe.log, "{\"ms\":%lld,\"role\":%d,\"event\":\"%s\",\"a\":%u,\"b\":%u,\"c\":%u}\n",
        static_cast<long long>(ms), probe.role, event, a, b, c);
    std::fflush(probe.log);
}
void Phase(int phase) { probe.phase = phase; probe.changed = Clock::now(); }
uint32_t ActorTokenHash(const uint8_t* base, uint64_t at) {
    const auto token = Word(base, at);
    if (!token || token > 0xFFFFFFFDu) return 0;
    uint32_t hash = 2166136261u;
    for (unsigned i = 0; i < 128; ++i) {
        unsigned char c = 0;
        if (!Read(base, uint64_t(token) + 2 + i, c)) return 0;
        if (!c) return i ? hash : 0;
        if (c < 32 || c > 126) return 0;
        hash = (hash ^ c) * 16777619u;
    }
    return 0;
}
// Pure reads: native F9885 creates a player controller and must not be used as
// an actor getter. The title's +118 smart reference already contains the actor.
void ObserveActor(const uint8_t* base, uint32_t actor, unsigned kind, unsigned index,
                  unsigned local, uint32_t input) {
    uint32_t component = 0, object = 0, inventory = 0, animation = 0, valid = Span(base, actor, 0x9C);
    uint16_t count = 0;
    if (valid) {
        const auto list = Word(base, uint64_t(actor) + 0x64);
        valid = Read(base, uint64_t(actor) + 0x60, count) && count <= 128 && (!count || Span(base, list, count * 8));
        for (unsigned i = 0; valid && i < count; ++i) {
            const auto item = Word(base, uint64_t(list) + i * 8 + 4);
            if (!Span(base, item, 0x10) || Word(base, uint64_t(item) + 0xC) != actor) { valid = 0; break; }
            if (Word(base, item) == 0x41F29C) inventory = item;
            if (Word(base, item) == 0x41D258) animation = item;
            if (Word(base, item) != 0x4432DC) continue;
            if (component || !Span(base, item, 0x24)) { valid = 0; break; }
            component = item; object = Word(base, uint64_t(item) + 0x1C);
        }
        if (object && (!Span(base, object, 0x7C) || Word(base, uint64_t(object) + 0x68) != actor)) valid = 0;
    }
    if (valid && kind == 0) {
        if (Word(base, actor + 0x90) & 2u) {
            const auto rig = Word(base, uint64_t(animation) + 0x90), impl = Word(base, uint64_t(rig) + 4);
            const auto collection = Word(base, uint64_t(impl) + 4), bodies = Word(base, uint64_t(collection) + 8);
            const auto body = Word(base, bodies), motion = Word(base, uint64_t(body) + 0x3C);
            if (Word(base, rig) == 0x41D4AC && Word(base, uint64_t(impl) + 0x12C) == actor && Span(base, motion, 0xC0)) {
                Record("campaign-dead-player", actor, Word(base, impl + 0xC0) & 0xFF00u, body);
                Record("campaign-ragdoll-root", Word(base, motion + 0xB0), Word(base, motion + 0xB4), Word(base, motion + 0xB8));
                Record("campaign-ragdoll-velocity", Word(base, motion + 0x40), Word(base, motion + 0x44), Word(base, motion + 0x48));
                if (Span(base, object, 0x1FC))
                    Record("campaign-ragdoll-network", Word(base, object + 0x1F0), Word(base, object + 0x1F4), Word(base, object + 0x1F8));
            }
        }
        uint16_t slots = 0;
        const auto list = Word(base, uint64_t(inventory) + 0x8C);
        const bool readable = Span(base, inventory, 0x90) && Read(base, inventory + 0x88, slots) && slots <= 64 &&
            (!slots || Span(base, list, slots * 4));
        Record("campaign-inventory", actor, inventory, readable ? slots : ~0u);
        for (unsigned i = 0; readable && i < slots; ++i) {
            const auto slot = Word(base, uint64_t(list) + i * 4), type = Word(base, slot);
            if (type != 0x41F570 && type != 0x41F308 && type != 0x41F178) continue;
            if (!Span(base, slot, 0x1C) || Word(base, slot + 8) != inventory) continue;
            uint16_t items = 1; auto entries = slot + 0xC;
            if (type == 0x41F178 && (!Read(base, slot + 0xC, items) || items > 64 ||
                !(entries = Word(base, slot + 0x10)) || !Span(base, entries, items * 16))) continue;
            for (unsigned j = 0; j < items; ++j) {
                const auto weapon = Word(base, uint64_t(entries) + j * 16);
                if (weapon && Span(base, weapon, 0x9C)) Record("campaign-weapon", actor, weapon, ActorTokenHash(base, weapon + 0x50));
            }
        }
    }
    // IEEE-754 bits avoid locale/nonfinite JSON and preserve exact comparisons.
    std::lock_guard lock(probe.mutex);
    if (probe.records++ >= 32768u) return;
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - probe.started).count();
    std::fprintf(probe.log, "{\"ms\":%lld,\"role\":%d,\"event\":\"campaign-actor\",\"kind\":%u,\"index\":%u,\"local\":%u,\"input\":%u,\"actor\":%u,\"valid\":%u,\"component\":%u,\"object\":%u,\"handle\":%u,\"owner\":%u,\"vtable\":%u,\"name_hash\":%u,\"template_hash\":%u,\"position_bits\":[%u,%u,%u],\"orientation_bits\":[%u,%u,%u,%u,%u,%u,%u,%u,%u]}\n",
        static_cast<long long>(ms), probe.role, kind, index, local, input, actor, valid, component, object,
        Word(base, uint64_t(object) + 0x2C), Word(base, uint64_t(object) + 0xC), Word(base, object),
        ActorTokenHash(base, uint64_t(actor) + 0x54), ActorTokenHash(base, uint64_t(actor) + 0x50),
        Word(base, uint64_t(actor) + 0x40), Word(base, uint64_t(actor) + 0x44), Word(base, uint64_t(actor) + 0x48),
        Word(base, uint64_t(actor) + 0x10), Word(base, uint64_t(actor) + 0x14), Word(base, uint64_t(actor) + 0x18),
        Word(base, uint64_t(actor) + 0x20), Word(base, uint64_t(actor) + 0x24), Word(base, uint64_t(actor) + 0x28),
        Word(base, uint64_t(actor) + 0x30), Word(base, uint64_t(actor) + 0x34), Word(base, uint64_t(actor) + 0x38));
    std::fflush(probe.log);
}
void ObserveCampaignActors(const uint8_t* base) {
    const auto loader = Word(base, 0x4ACFBC);
    if (!probe.campaign || !probe.title_online || !probe.loading || probe.phase != 5 || probe.campaign_stage != 3 ||
        Word(base, 0x4AF628) != probe.session || !probe.session || Word(base, uint64_t(loader) + 8) != 5) return;
    const auto now = Clock::now();
    if (probe.actors_sampled != Clock::time_point{} && std::chrono::duration<double>(now - probe.actors_sampled).count() < 2) return;
    probe.actors_sampled = now;
    const auto queue = Word(base, 0x4B8DD0); uint16_t queued = 0;
    if (queue && !Read(base, queue, queued)) queued = 0xFFFF;
    Record("campaign-actor-queue", Word(base, 0x49E264) & 255, queue, queued);
    uint16_t count = 0; const auto records = Word(base, uint64_t(probe.game) + 0x54);
    if (!Read(base, uint64_t(probe.game) + 0x50, count) || count > 16 || (count && !Span(base, records, count * 0x130))) {
        Record("campaign-observation-invalid", 1, count, records); return;
    }
    for (unsigned i = 0; i < count; ++i) {
        const auto record = records + i * 0x130, index = Word(base, record + 0x10C);
        if (index < 2) ObserveActor(base, Word(base, record + 0x118), 0, index, base[record + 0x128], Word(base, record + 0x114));
    }
    const auto manager = Word(base, 0x4AC118), groups = Word(base, uint64_t(manager) + 4);
    uint16_t group_count = 0;
    if (!Read(base, manager, group_count) || group_count > 256 || (group_count && !Span(base, groups, group_count * 4))) {
        Record("campaign-observation-invalid", 2, group_count, groups); return;
    }
    unsigned visited = 0, found = 0;
    for (unsigned i = 0; i < group_count; ++i) {
        const auto group = Word(base, uint64_t(groups) + i * 4), actors = Word(base, uint64_t(group) + 0x24);
        uint16_t actor_count = 0;
        if (!Read(base, uint64_t(group) + 0x20, actor_count) || actor_count > 4096 - visited ||
            (actor_count && !Span(base, actors, actor_count * 4))) { Record("campaign-observation-invalid", 3, group, actor_count); return; }
        visited += actor_count;
        for (unsigned j = 0; j < actor_count; ++j) {
            const auto actor = Word(base, uint64_t(actors) + j * 4), token = Word(base, uint64_t(actor) + 0x50);
            // Record every enrolled instance, including accidental duplicate spawns.
            // Ordinary representatives below must not hide later proof actors.
            if (ProofCampaignTemplate(base, token)) {
                ObserveActor(base, actor, 1, ~0u, 0, ~0u); continue;
            }
            std::string name;
            if (token && token <= 0xFFFFFFFDu) String(base, token + 2, name);
            const auto actor_name = ActorTokenHash(base, uint64_t(actor) + 0x54);
            const unsigned kind = actor_name == 0xB5CF239F || name == "WrongTrainLock" ? 3 :
                actor_name == 0x2E8B6EA4 ? 4 : name == "Reaper" ? 1 :
                (name == "BasicPistolPickup" || name == "HealthPickup" ? 2 : 0);
            if (!kind || (found & (1u << (kind - 1)))) continue;
            found |= 1u << (kind - 1); ObserveActor(base, actor, kind, ~0u, 0, ~0u);
        }
    }
    Record("campaign-observation-scan", visited, found, group_count);
}
template<class Invoke> bool CampaignMembers(Invoke& invoke, const uint8_t* base, uint32_t (&objects)[2]) {
    const auto data = Word(base, Word(base, 0x4B0864)), list = Word(base, uint64_t(data) + 0x8C);
    uint16_t count = 0;
    if (!Read(base, uint64_t(data) + 0x88, count) || count != 2 || !Span(base, list, 8) ||
        !probe.session || Word(base, 0x4AF628) != probe.session ||
        (invoke(0x186A30, 0) & 255) != uint32_t(probe.role)) return false;
    const auto local = invoke(0x17BBB0, 0);
    uint32_t owners[2]{};
    for (unsigned i = 0; i < 2; ++i) {
        const auto wrapper = Word(base, uint64_t(list) + 4 * i);
        objects[i] = Word(base, uint64_t(Word(base, uint64_t(wrapper) + 4)) + 0x54);
        if (!Span(base, objects[i], 0xD8) || Word(base, uint64_t(objects[i]) + 0xD0) != wrapper) return false;
        owners[i] = Word(base, uint64_t(objects[i]) + 0xC);
    }
    return local && owners[0] && owners[1] && owners[0] != owners[1] &&
        ((owners[0] == local) != (owners[1] == local));
}
template<class Invoke> bool PrepareCampaignTitle(Invoke& invoke, uint8_t* base, uint32_t player_name) {
    const auto game = invoke(0x17595, 0), pm = game + 0x40, loader = Word(base, 0x4ACFBC);
    const auto params = probe.scratch + 1024, name = probe.scratch + 1080;
    if (!Span(base, game, 0x138) || !Span(base, loader, 0x74) || Word(base, uint64_t(loader) + 8) != 1 ||
        Word(base, uint64_t(loader) + 0xC) != 7 || base[game + 0xC] || Word(base, game + 0x70) ||
        !Span(base, Word(base, game + 0xA8), 4) || Word(base, Word(base, game + 0xA8))) {
        Record("campaign-initial-state-invalid", game, loader, Word(base, uint64_t(loader) + 8)); return false;
    }
    probe.game = game; probe.session = Word(base, 0x4AF628);
    invoke(0xC8A6B, params);
    invoke(0x138FA, params, {0x4259AC}); // Original chapter key: WrongTrain.
    Put(base, params + 0x20, 0);
    invoke(0xC21A2, game, {0});
    const auto configured = invoke(0xC36F4, game, {params});
    invoke(0x11C1A, params);
    if (!(configured & 255)) { Record("campaign-config-failed"); return false; }
    invoke(0xFA8E5, pm, {1});
    const auto record = invoke(0xF9A4D, pm, {0});
    if (!Span(base, record, 0x130)) { Record("campaign-local-record-missing"); return false; }
    invoke(0xFA79B, pm, {0, 0, record + 0x9C, 0});
    // Bind the title name before publication can make this peer visible remotely.
    invoke(0x138FA, name, {player_name});
    invoke(0x129DF, record + 0x108, {name});
    invoke(0x11C1A, name);
    if (Word(base, game + 0x4C) != 1 || !base[record + 0x128] || Word(base, record + 0x114) ||
        invoke(0xF983E, pm, {record + 0x108}) != record) {
        Record("campaign-local-record-invalid"); return false;
    }
    base[game + 0xC] = 1; probe.title_online = true;
    DarkwatchOnlineCharactersBegin(probe.session, game, invoke(0x17BBB0, 0), unsigned(probe.role - 1));
    // Keep native prediction/error filtering; remove the 150 ms position-send floor.
    if (Word(base, 0x48E528) == 150) {
        Put(base, 0x48E528, 8); probe.position_interval_owned = true;
        Record("campaign-position-interval", 150, 8);
    }
    // One 60 Hz frame of correction avoids the landing snaps seen with a 1 ms blend.
    for (unsigned i = 0; i < std::size(kBlendFloors); ++i) {
        if (Word(base, kBlendFloors[i]) != 250 || Word(base, kBlendFloors[i] - 4) != 1000) continue;
        Put(base, kBlendFloors[i], 16); Put(base, kBlendFloors[i] - 4, 16);
        probe.blend_floors_owned |= 1u << i;
        Record("campaign-blend-range", kBlendFloors[i], 16, 16);
    }
    // Native deserializers date received movement into the future before queuing it.
    if (Word(base, 0x4B084C) == 200) {
        Put(base, 0x4B084C, 0); probe.receive_delay_owned = true;
        Record("campaign-receive-delay", 200, 0);
    }
    if (probe.role == 2) invoke(0x22C864, 0, {1});
    invoke(0x24A17D, 0);
    Record("campaign-title-ready", game, Word(base, game + 0x44), Word(base, game + 0x4C));
    return true;
}
template<class Invoke> void CampaignStep(const X86Context& ctx, Invoke& invoke, uint8_t* base, double age) {
    const auto loader = Word(base, 0x4ACFBC);
    // The run script owns the loaded game's deadline; disabling its hooks mid-game is unsafe.
    if (!probe.loading && age > 180) {
        Record("campaign-timeout", probe.campaign_stage, Word(base, uint64_t(loader) + 8));
        Phase(7); return;
    }
    const auto data = Word(base, Word(base, 0x4B0864));
    uint16_t count = 0; Read(base, uint64_t(data) + 0x88, count);
    if (count != 2 && !probe.campaign_stage) return;
    uint32_t objects[2]{};
    if (!CampaignMembers(invoke, base, objects)) {
        Record("campaign-membership-role", invoke(0x186A30, 0) & 255, Word(base, 0x4AF628), probe.session);
        Record("campaign-membership-list", count, Word(base, uint64_t(data) + 0x8C), invoke(0x17BBB0, 0));
        for (unsigned i = 0; i < 2; ++i)
            Record("campaign-membership-object", objects[i], Word(base, uint64_t(objects[i]) + 0xC), Word(base, uint64_t(objects[i]) + 0xD0));
        Record("campaign-membership-invalid"); Phase(probe.loading ? 9 : 7); return;
    }
    for (auto object : objects) {
        if (Word(base, object + 0xC) == invoke(0x17BBB0, 0)) {
            DarkwatchOnlineCharactersTick(ctx, base, object);
        }
    }
    if (!DarkwatchOnlineCharactersReady()) return;
    if (probe.campaign_stage == 0) {
        if (probe.role == 1) {
            if (Word(base, probe.game + 0x70) || Word(base, Word(base, probe.game + 0xA8))) {
                Record("campaign-host-already-published"); Phase(7); return;
            }
            invoke(0xFACC9, probe.game + 0x40, {probe.game + 0xF0});
            invoke(0xC456D, probe.game + 0xA8);
        }
        probe.campaign_stage = 1;
        return;
    }
    const auto game = probe.game, pm = game + 0x40, roster = Word(base, game + 0x70);
    const auto stats = Word(base, Word(base, game + 0xA8));
    if (probe.campaign_stage == 1) {
        if (!roster || !stats) return;
        if (!Span(base, roster, 0xF4) || !Span(base, stats, 0xBC) || Word(base, stats + 0xB8) != game + 0xA8 ||
            Word(base, game + 0xEC) || base[roster + 0xC8] || Word(base, game + 0x4C) != 1) {
            Record("campaign-roster-invalid", roster, stats); Phase(7); return;
        }
        const auto host = Word(base, uint64_t(invoke(0x1869F0, 0)) + 0xC);
        for (unsigned i = 0; i < 2; ++i) {
            const auto slot = Word(base, objects[i] + 0xC) == host ? 0 : 1;
            std::string participant_name, roster_name;
            if (!String(base, objects[i] + 0x98, participant_name) || participant_name.empty() || participant_name.size() > 27 ||
                !String(base, Word(base, roster + 0x44 + slot * 4), roster_name) || participant_name != roster_name) return;
        }
        if (probe.role == 1 && !(invoke(0x1C29E4, 0) & 255)) return;
        Record("campaign-roster-ready", Word(base, roster + 0x2C), Word(base, stats + 0x2C), Word(base, roster + 0xCC));
        if (probe.role == 1) {
            invoke(0xFACAA, pm);
            Record("campaign-start-published", Word(base, roster + 0xD8), Word(base, roster + 0xDC));
        }
        probe.campaign_stage = 2;
    }
    if (probe.campaign_stage == 2) {
        if (!Word(base, game + 0x58)) return;
        invoke(0xF14A7, 0);
        if (Word(base, game + 0x58) != 2) return;
        const auto record = invoke(0xF9A12, pm, {0});
        if (!Span(base, record, 0x130) || !base[record + 0x128] || Word(base, record + 0x10C) != uint32_t(probe.role - 1) ||
            Word(base, game + 0x44) != 2 || Word(base, game + 0x4C) != 1 || Word(base, loader + 8) != 1 || Word(base, loader + 0xC) != 7) {
            Record("campaign-countdown-state-invalid", Word(base, record + 0x10C), Word(base, game + 0x44), Word(base, loader + 8)); Phase(7); return;
        }
        Record("campaign-countdown-complete", Word(base, record + 0x10C), Word(base, record + 0x114), Word(base, game + 0x4C));
        invoke(0xF9409, pm);
        probe.loading = true; probe.campaign_stage = 3;
        invoke(0xC58BB, loader, {game, probe.scratch + 1100, 0});
        Record("campaign-load-requested", Word(base, loader + 8), Word(base, loader + 0xC));
    }
    if (probe.campaign_stage == 3) {
        const auto state = Word(base, loader + 8);
        if (state != probe.loader_state) {
            probe.loader_state = state;
            Record("campaign-loader-state", state, Word(base, loader + 0xC), Word(base, loader + 0x70));
            if (state == 5) Record("campaign-gameplay-counts", Word(base, game + 0x44), Word(base, game + 0x4C), Word(base, game + 0xEC));
        }
        if (state == 5) {
            const bool owned = probe.position_error_owned;
            TightenPositionError(base);
            if (!owned && probe.position_error_owned) Record("campaign-position-error", 4, 0x4AD468);
            ObserveCampaignActors(base);
        }
    }
}
void Step(const X86Context& ctx, uint8_t* base) {
    if (!Enabled() || probe.phase == 9) return;
    if (!probe.thread_bound) { probe.thread = ctx.thread_handle; probe.thread_bound = true; probe.changed = Clock::now(); Record("native-tick", ctx.thread_handle); }
    if (probe.thread != ctx.thread_handle || ctx.esp < 0x10000 || !Span(base, ctx.esp - 0x10000, 0x10000)) return;
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self, std::initializer_list<uint32_t> args = {}) {
        call.ecx = self; return kernel::CallGuest(call, fn, args);
    };
    const uint32_t owner = Word(base, 0x4B4FC0);
    if (!owner || !Span(base, owner, 0x68)) { Record("invalid-network-owner", owner); Phase(9); return; }
    if (!probe.scratch) {
        probe.scratch = mem::AllocSystem(4096);
        if (!probe.scratch) { Record("scratch-allocation-failed"); Phase(9); return; }
        std::memset(base + probe.scratch, 0, 4096);
    }
    const auto now = Clock::now();
    const double age = std::chrono::duration<double>(now - probe.changed).count();
    if (probe.phase == 0) {
        if (age < 3) return;
        if (probe.campaign) {
            const auto loader = Word(base, 0x4ACFBC);
            if (Word(base, uint64_t(loader) + 8) != 1 || Word(base, uint64_t(loader) + 0xC) != 7) return;
        }
        const uint32_t context = invoke(0x19CB50, 0);
        const uint32_t module = invoke(0xCD8C3, 0x4AF658, {6, context});
        probe.manager = Word(base, uint64_t(module) + 0x28);
        if (!probe.manager || !Span(base, probe.manager, 0x64)) { Record("missing-discovery-manager", module); Phase(9); return; }
        probe.lan = invoke(0x19BBB0, probe.manager, {0x438050});
        if (!probe.lan || Word(base, probe.lan) != 0x47235C || !Word(base, uint64_t(probe.lan) + 0x1C)) {
            Record("missing-lan-provider", probe.lan); Phase(9); return;
        }
        Record("network-ready", owner, probe.manager, probe.lan);
        if (probe.role == 1) {
            const int channels = ChannelCallback(base);
            if (channels < 0) { Record("invalid-session-callback-list"); Phase(9); return; }
            if (!channels) {
                invoke(0x187DE0, 0, {0x1C4E4D});
                probe.registered_channels = true;
                if (ChannelCallback(base) != 1) { Record("channel-registration-failed"); Phase(7); return; }
                Record("channels-registered");
            }
            Record("create-begin");
            probe.creating = true;
            const auto result = invoke(0x211498, 0, {0x439C14, probe.scratch});
            probe.creating = false;
            Record("create-return", result & 255); Phase(1);
        } else Phase(2);
        return;
    }
    if (probe.phase == 1) {
        uint8_t owned = 0; Read(base, uint64_t(probe.manager) + 0x60, owned);
        std::string url;
        if (owned && String(base, Word(base, uint64_t(probe.manager) + 0x38), url) && !url.empty()) {
            darkwatch::OnlineSessionUrlFields fields;
            if (!darkwatch::ParseOnlineSessionUrl(url, fields)) { Record("host-url-invalid", uint32_t(url.size())); Phase(7); return; }
            Record("host-published", owned, uint32_t(url.size()), Word(base, 0x4AF628)); Phase(5);
        } else if (age > 30) { Record("host-publication-timeout", owned); Phase(7); }
    } else if (probe.phase == 2) {
        std::string url;
        { std::lock_guard lock(probe.mutex); url = probe.discovered; }
        if (!url.empty()) {
            darkwatch::OnlineSessionUrlFields fields;
            if (!darkwatch::ParseOnlineSessionUrl(url, fields)) { Record("discovery-url-invalid"); Phase(7); return; }
            const auto address = probe.scratch + 64, kid = probe.scratch + 104, key = probe.scratch + 112;
            std::memcpy(base + address, fields.address.data(), fields.address.size());
            std::memcpy(base + kid, fields.key_id.data(), fields.key_id.size());
            std::memcpy(base + key, fields.key.data(), fields.key.size());
            const auto registered = invoke(0x17E1A0, 0, {kid, key});
            Record("key-registration", registered);
            if (!(registered & 255)) { Phase(7); return; }
            invoke(0xF2BEA, probe.scratch, {0x1B54C, 0});
            Phase(3); Record("join-begin", Word(base, address));
            const auto result = invoke(0x2114CE, 0, {address, kid, key, probe.scratch});
            Record("join-return", result & 255, Word(base, uint64_t(owner) + 0x18));
            if (!(result & 255)) Phase(7);
        } else if (age > (probe.campaign ? 120 : 30)) { Record("discovery-timeout", probe.queries); Phase(7); }
        else if (!probe.queries || std::chrono::duration<double>(now - probe.query).count() >= 2) {
            { std::lock_guard lock(probe.mutex); probe.discovered.clear(); }
            invoke(0x2E9570, probe.lan); probe.query = now; ++probe.queries;
            Record("discovery-query", probe.queries, Word(base, uint64_t(probe.lan) + 0x20));
        }
    } else if (probe.phase == 3) {
        if (probe.completion >= 0) {
            Record("join-completion", uint32_t(probe.completion), invoke(0x186A30, 0) & 255, Word(base, 0x4AF628));
            Phase(probe.completion == 0 ? 5 : 7);
        } else if (age > 25) { Record("join-timeout", Word(base, uint64_t(owner) + 0x18)); Phase(7); }
    } else if (probe.phase == 5) {
        if (!probe.participant_attempted) {
            probe.participant_attempted = true;
            const auto frontend = Word(base, 0x4B0864), data = Word(base, frontend);
            const auto local = invoke(0x17BBB0, 0), provider = Word(base, 0x434B90);
            uint16_t locals = 0, existing = 0;
            if (!Read(base, 0x4B08A8, locals) || locals || !Span(base, data, 0xA8) ||
                !local || (invoke(0x186A30, 0) & 255) != uint32_t(probe.role) ||
                !Span(base, provider, 0x58) || !Span(base, Word(base, provider), 0x28)) {
                Record("participant-admission-failed", frontend, data, locals); Phase(7); return;
            }
            const auto existing_list = Word(base, uint64_t(data) + 0x8C);
            if (!Read(base, uint64_t(data) + 0x88, existing) || existing > 1 ||
                (existing && !Span(base, existing_list, uint32_t(existing) * 4))) {
                Record("participant-list-invalid", existing, existing_list); Phase(7); return;
            }
            for (unsigned i = 0; i < existing; ++i) {
                const auto wrapper = Word(base, uint64_t(existing_list) + 4 * i);
                const auto payload = Word(base, uint64_t(wrapper) + 4), object = Word(base, uint64_t(payload) + 0x54);
                const auto station = Word(base, uint64_t(object) + 0xC);
                if (!Span(base, object, 0xD8) || !station || station == local ||
                    Word(base, uint64_t(object) + 0xD0) != wrapper) {
                    Record("participant-existing-invalid", wrapper, object, station); Phase(7); return;
                }
            }
            const auto listener = invoke(0x1C1903, data);
            if (!Span(base, listener, 4) || !Span(base, Word(base, listener), 4) ||
                !Span(base, Word(base, Word(base, listener)), 1)) {
                Record("participant-listener-invalid", listener); Phase(7); return;
            }
            // The original local descriptor owns a native-heap wrapper, not a host allocation.
            const auto descriptor = probe.scratch + 256, name = probe.scratch + 288;
            const uint32_t fields[] = {local, 0x44574C41, 0, name, 0, 0};
            std::memcpy(base + descriptor, fields, sizeof(fields));
            std::strcpy(reinterpret_cast<char*>(base + name), probe.role == 1 ? "DW_HOST" : "DW_JOIN");
            const auto wrapper = invoke(0x24C546, 0, {8});
            if (!Span(base, wrapper, 8)) { Record("participant-allocation-failed"); Phase(7); return; }
            invoke(0x1C28BC, wrapper, {descriptor});
            invoke(0x1E249C, 0x4B08A8, {wrapper});
            probe.participant = wrapper;
            if (probe.campaign && !PrepareCampaignTitle(invoke, base, name)) { Phase(7); return; }
            invoke(0x1C2A02, 0);
            const auto payload = Word(base, uint64_t(wrapper) + 4), object = Word(base, uint64_t(payload) + 0x54);
            if (!Span(base, object, 0xD8) || Word(base, uint64_t(object) + 0xD0) != wrapper ||
                !Word(base, uint64_t(object) + 0x2C)) {
                Record("participant-publication-failed", wrapper, payload, object); Phase(7); return;
            }
            Record("participant-published", Word(base, uint64_t(object) + 0x2C), Word(base, uint64_t(object) + 0x0C), wrapper);
            if (probe.campaign) {
                const auto record = invoke(0xF9A12, probe.game + 0x40, {0}), title_name = probe.scratch + 1080;
                if (!Span(base, record, 0x130)) { Record("campaign-local-record-missing"); Phase(7); return; }
                invoke(0x1C29A9, wrapper, {title_name});
                const bool match = (Word(base, title_name) >> 2) == (Word(base, record + 0x108) >> 2);
                invoke(0x11C1A, title_name);
                if (!match) { Record("campaign-published-name-mismatch"); Phase(7); return; }
                invoke(0x1C2818, wrapper, {Word(base, record + 0xE0)});
            }
        }
        if (probe.sampled == Clock::time_point{} || std::chrono::duration<double>(now - probe.sampled).count() >= 2) {
            probe.sampled = now;
            const auto session = invoke(0x1869F0, 0), local = invoke(0x17BBB0, 0), iterator = probe.scratch + 512;
            Record("membership-session", Word(base, uint64_t(session) + 0x2C), Word(base, uint64_t(session) + 0xC), local);
            invoke(0x179D40, iterator);
            uint32_t ids[32]{}; unsigned count = 0; bool valid = true;
            while (const auto id = Word(base, uint64_t(iterator) + 8)) {
                const auto station = Word(base, uint64_t(iterator) + 4);
                if (count == 32 || !Span(base, station, 0x30) || Word(base, uint64_t(station) + 0x2C) != id) { valid = false; break; }
                for (unsigned i = 0; i < count; ++i) if (ids[i] == id) valid = false;
                if (!valid) break;
                ids[count++] = id;
                Record("membership-station", id, Word(base, uint64_t(station) + 0xC), id == local);
                invoke(0xF0A27, iterator, {0});
            }
            invoke(0x16A530, iterator);
            Record("membership-count", count, valid, invoke(0x186A30, 0) & 255);
            const auto data = Word(base, Word(base, 0x4B0864));
            uint16_t locals = 0, total = 0;
            Read(base, 0x4B08A8, locals); Read(base, uint64_t(data) + 0x88, total);
            Record("participant-count", locals, total);
            const auto list = Word(base, uint64_t(data) + 0x8C);
            if (total <= 8 && (!total || Span(base, list, uint32_t(total) * 4))) {
                for (unsigned i = 0; i < total; ++i) {
                    const auto wrapper = Word(base, uint64_t(list) + 4 * i);
                    const auto payload = Word(base, uint64_t(wrapper) + 4), object = Word(base, uint64_t(payload) + 0x54);
                    Record("participant-record", Word(base, uint64_t(object) + 0x2C), Word(base, uint64_t(object) + 0xC), wrapper == probe.participant);
                }
            }
        }
        if (probe.campaign) CampaignStep(ctx, invoke, base, age);
        else if (age > (probe.role == 1 ? 35 : 15)) {
            Record("session-state", invoke(0x186A30, 0) & 255, Word(base, 0x4AF628), Word(base, 0x4AF6C4)); Phase(7);
        }
    }
    if (probe.phase == 7) {
        if (probe.title_online) {
            // Full native abort owns both title DO disposal and its asynchronous Leave.
            invoke(0xC326C, probe.game); probe.title_online = false; Phase(8); return;
        }
        if (probe.participant) {
            uint16_t count = 0; Read(base, 0x4B08A8, count);
            if (count != 1 || Word(base, Word(base, 0x4B08AC)) != probe.participant) {
                Record("participant-cleanup-ownership-failed", count); Phase(9); return;
            }
            invoke(0x1C2BA2, 0); probe.participant = 0;
            Record("participant-cleanup", Word(base, 0x4B08A8), Word(base, 0x4B08AC));
        }
        if (!Word(base, 0x4B4FC4)) { Record("leave-begin"); invoke(0x210E57, 0); }
        Phase(8);
    } else if (probe.phase == 8) {
        // The native end-of-frame CD3FD hook drains and recreates the owner.
        if (!Word(base, 0x4B4FC4) && !(invoke(0x186A30, 0) & 255)) {
            if (probe.participant) {
                uint16_t count = 0; Read(base, 0x4B08A8, count);
                if (count != 1 || Word(base, Word(base, 0x4B08AC)) != probe.participant) {
                    Record("participant-cleanup-ownership-failed", count); Phase(9); return;
                }
                invoke(0x1C2BA2, 0); probe.participant = 0;
                Record("participant-cleanup", Word(base, 0x4B08A8), Word(base, 0x4B08AC));
            }
            if (probe.registered_channels) {
                invoke(0x186F00, 0, {0x1C4E4D}); probe.registered_channels = false;
                Record("channels-unregistered", uint32_t(ChannelCallback(base)));
            }
            Record("leave-complete", Word(base, 0x4B4FC4), Word(base, 0x4B4FC0));
            mem::FreeSystem(probe.scratch); probe.scratch = 0; Phase(9);
        } else if (age > 20) { Record("leave-timeout"); Phase(9); }
    }
}
}

X86_FUNC(sub_000CD3F8) {
    __imp__sub_000CD3F8(ctx, base);
    Step(ctx, base);
    DarkwatchOnlineCampaignLoadTick(ctx, base);
}
X86_FUNC(sub_001EB3D6) {
    const auto caller = Word(base, ctx.esp);
    __imp__sub_001EB3D6(ctx, base);
    if (!Enabled() || !probe.campaign || !probe.title_online || !probe.loading || probe.phase != 5 ||
        !probe.thread_bound || ctx.thread_handle != probe.thread || probe.movie_pumping ||
        caller != 0x1EB5B2 || !Span(base, 0x4B7A41, 1) || !base[0x4B7A41] ||
        ctx.esp < 0x10000 || !Span(base, ctx.esp - 0x10000, 0x10000)) return;
    const auto owner = Word(base, 0x4B4FC0), loader = Word(base, 0x4ACFBC);
    const auto state = Word(base, uint64_t(loader) + 8);
    if (!Span(base, owner, 0x68) || !Span(base, loader, 0x74) || (state != 3 && state != 4)) return;
    probe.movie_pumping = true;
    struct Reset { ~Reset() { probe.movie_pumping = false; } } reset;
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    uint32_t objects[2]{};
    if (!CampaignMembers(invoke, base, objects)) return;
    // Blocking campaign movies otherwise exceed the native ten-second peer timeout.
    invoke(0x17CBF0, 0);
    if (probe.phase != 5 || Word(base, 0x4B4FC0) != owner || Word(base, 0x4AF628) != probe.session) return;
    invoke(0xCD3F3, 0);
    ++probe.movie_passes;
    const auto now = Clock::now();
    if (probe.movie_sampled == Clock::time_point{} || std::chrono::duration<double>(now - probe.movie_sampled).count() >= 2) {
        probe.movie_sampled = now;
        uint16_t count = 0;
        Read(base, uint64_t(Word(base, Word(base, 0x4B0864))) + 0x88, count);
        Record("campaign-movie-service", probe.movie_passes, count, state);
    }
}
X86_FUNC(sub_000C244F) {
    const auto game = ctx.ecx, caller = Word(base, ctx.esp);
    __imp__sub_000C244F(ctx, base);
    if (Enabled() && probe.campaign && probe.phase == 5 &&
        probe.thread_bound && ctx.thread_handle == probe.thread && game == probe.game &&
        (caller == 0xCC408 || caller == 0xCC4ED || caller == 0xC41C8 || caller == 0xF8EB3)) {
        const unsigned bit = caller == 0xCC408 ? 1 : caller == 0xCC4ED ? 2 : caller == 0xC41C8 ? 4 : 8;
        if (!(probe.story_paths_seen & bit)) {
            probe.story_paths_seen |= bit;
            Record("campaign-story-coop-query", caller, Word(base, uint64_t(Word(base, 0x4ACFBC)) + 8),
                   (ctx.eax & 255) | (unsigned(probe.loading) << 8) | (unsigned(probe.title_online) << 9));
        }
    }
    if ((ctx.eax & 255) || !Enabled() || !probe.campaign || !probe.title_online || !probe.loading || probe.phase != 5 ||
        !probe.thread_bound || ctx.thread_handle != probe.thread || game != probe.game ||
        !Span(base, game, 0x138) || !base[game + 0xC] || Word(base, game + 0xEC) ||
        Word(base, game + 0x44) != 2 || Word(base, game + 0x4C) != 1 ||
        ctx.esp < 0x10000 || !Span(base, ctx.esp - 0x10000, 0x10000)) return;
    // Script IsCoOpGame and campaign state use both peers; camera queries still use one local view.
    constexpr uint32_t callers[]{0xC32BB, 0xCBEA8, 0xCBF00, 0xCBF0F, 0xCB6B1, 0xCB855, 0xC29E3, 0xC3E02, 0x9E4C5,
                                 0xCC408, 0xC41C8, 0xCC4ED, 0xF8EB3};
    unsigned path = 0;
    while (path < std::size(callers) && callers[path] != caller) ++path;
    if (path == std::size(callers)) return;
    const auto loader = Word(base, 0x4ACFBC), state = Word(base, uint64_t(loader) + 8);
    if (!Span(base, loader, 0x74) || state < 3 || state > 5) return;
    if (caller == 0xCC408 && state != 5) return;
    if ((caller == 0xC41C8 || caller == 0xCC4ED) && state != 3) return;
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    uint32_t objects[2]{};
    if (!CampaignMembers(invoke, base, objects)) return;
    ctx.eax = (ctx.eax & ~255u) | 1u;
    if (!(probe.coop_paths_seen & (1u << path))) {
        probe.coop_paths_seen |= 1u << path;
        Record("campaign-coop-path", caller, game, state);
    }
}
namespace {
bool CampaignPlayerCache(const X86Context& ctx, const uint8_t* base) {
    const auto game = probe.game, manager = Word(base, 0x4AC118), loader = Word(base, 0x4ACFBC);
    if (!Enabled() || !probe.campaign || !probe.title_online || !probe.loading || probe.phase != 5 ||
        !probe.thread_bound || ctx.thread_handle != probe.thread ||
        !Span(base, game, 0x138) || !base[game + 0xC] || Word(base, game + 0xEC) ||
        Word(base, game + 0x4C) != 1 || !Span(base, loader, 0x74) ||
        Word(base, loader + 8) != 5 || !Span(base, manager, 0x20) ||
        ctx.esp < 0x10000 || !Span(base, ctx.esp - 0x10000, 0x10000)) return false;
    const auto total = Word(base, game + 0x44), records = Word(base, game + 0x54);
    uint16_t count = 0, cached = 0;
    if (!total || total > 2 || !Read(base, game + 0x50, count) || count != total ||
        !Span(base, records, count * 0x130) || !Read(base, manager + 0x10, cached) || cached > 2 ||
        (cached && !Span(base, Word(base, manager + 0x14), cached * 4))) return false;
    unsigned seen = 0;
    for (unsigned i = 0; i < count; ++i) {
        const auto record = records + i * 0x130, index = Word(base, record + 0x10C);
        const auto actor = Word(base, record + 0x118);
        if (index >= total || (seen & (1u << index)) || (actor && !Span(base, actor, 0x9C))) return false;
        seen |= 1u << index;
    }
    return true;
}
bool RemoteCampaignDecision(const X86Context& ctx, uint8_t* base, uint32_t vtable, unsigned site) {
    const auto component = ctx.ecx, actor = Word(base, uint64_t(component) + 0xC);
    if (!CampaignPlayerCache(ctx, base) || Word(base, 0x4AF628) != probe.session || !probe.session ||
        !Span(base, component, 0x10) || Word(base, component) != vtable || !Span(base, actor, 0x9C)) return false;
    if (!ProofCampaignTemplate(base, Word(base, actor + 0x50))) return false;
    // Keep native event delivery intact, but don't start the proof NPC before both worlds are ready.
    if (site != 4 && !DarkwatchOnlineCampaignReady(ctx, base)) return true;
    uint16_t count = 0;
    const auto list = Word(base, actor + 0x64);
    if (!Read(base, actor + 0x60, count) || count > 128 || !Span(base, list, count * 8)) return false;
    uint32_t network = 0; bool found = false;
    for (unsigned i = 0; i < count; ++i) {
        const auto part = Word(base, list + i * 8 + 4);
        if (!Span(base, part, 0x10) || Word(base, part + 0xC) != actor) return false;
        found |= part == component;
        if (Word(base, part) != 0x4432DC) continue;
        if (network || !Span(base, part, 0x24)) return false;
        network = part;
    }
    if (!found || !network) return false;
    const auto object = Word(base, network + 0x1C);
    if (object && (!Span(base, object, 0x3F8) || Word(base, object) != 0x425CD0 ||
                   Word(base, object + 0x68) != actor)) return false;
    X86Context call = ctx;
    uint32_t members[2]{};
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    if (!CampaignMembers(invoke, base, members)) return false;
    // Query the native component directly: broadcasting here would recursively enter Lua.
    const auto query = ctx.esp - 32;
    const uint32_t initial[]{0x41E948, 0x24, 0, 1, 0};
    std::memcpy(base + query, initial, sizeof(initial));
    call.esp = query; call.ecx = network;
    kernel::CallGuest(call, 0x249BB9, {query});
    const bool remote = Word(base, query + 8) == 1 && Word(base, query + 0xC) == 0;
    static unsigned counts[6][2]{};
    const auto observed = ++counts[site][remote];
    if ((observed & (observed - 1)) == 0)
        Record(remote ? "campaign-npc-decision-blocked" : "campaign-npc-decision-owner", actor, site, observed);
    return remote;
}
void RefreshCampaignPlayers(const X86Context& ctx, uint8_t* base, uint32_t actor) {
    if (!CampaignPlayerCache(ctx, base)) return;
    X86Context call = ctx;
    call.ecx = probe.game + 0x40;
    kernel::CallGuest(call, 0xFA1F4, {});
    Record("campaign-player-cache-refreshed", actor, Word(base, 0x4AC118), Word(base, probe.game + 0x44));
}
}
#define CAMPAIGN_DECISION(entry, table, site) \
X86_FUNC(sub_##entry) { \
    if (RemoteCampaignDecision(ctx, base, table, site)) { ctx.esp += 8; return; } \
    __imp__sub_##entry(ctx, base); \
}
CAMPAIGN_DECISION(00028291, 0x418D78, 0)
CAMPAIGN_DECISION(00024DEB, 0x4188B4, 1)
CAMPAIGN_DECISION(0002C6DB, 0x419024, 2)
CAMPAIGN_DECISION(0002A359, 0x418F78, 3)
CAMPAIGN_DECISION(0002A42E, 0x418F78, 4)
CAMPAIGN_DECISION(0002A7FF, 0x418F78, 5)
#undef CAMPAIGN_DECISION
bool DarkwatchOnlineCampaignEventContext(const X86Context& ctx, const uint8_t* base) {
    return (CampaignPlayerCache(ctx, base) || DarkwatchOnlineCampaignLoaded(ctx, base)) &&
        probe.session && Word(base, 0x4AF628) == probe.session;
}
bool DarkwatchOnlineCharacterContext(const X86Context& ctx, const uint8_t* base, uint32_t game, uint32_t session) {
    return Enabled() && probe.campaign && probe.title_online && probe.phase == 5 &&
        probe.thread_bound && ctx.thread_handle == probe.thread && game == probe.game && session == probe.session &&
        session && Word(base, 0x4AF628) == session && Span(base, game, 0x138) &&
        base[game + 0xC] && !Word(base, game + 0xEC) && Word(base, game + 0x4C) == 1;
}
bool DarkwatchOnlineCharacterWireEnabled(const X86Context& ctx, const uint8_t* base) {
    // PlayerDO creation can precede title setup on a joining peer; its codec must still consume the extension.
    return Enabled() && probe.campaign && base == kernel::g_base &&
        probe.thread_bound && ctx.thread_handle == probe.thread;
}
bool DarkwatchOnlineCampaignTriggerContext(const X86Context& ctx, const uint8_t* base) {
    return probe.loading && DarkwatchOnlineCharacterContext(ctx, base, probe.game, probe.session);
}
bool DarkwatchOnlineCampaignLoadContext(const X86Context& ctx, const uint8_t* base,
                                       uint32_t& game, uint32_t& session, uint32_t& local, uint32_t& remote) {
    const auto loader = Word(base, 0x4ACFBC), state = Word(base, uint64_t(loader) + 8);
    if (!Enabled() || !probe.campaign || !probe.title_online || !probe.loading || probe.phase != 5 ||
        !probe.thread_bound || ctx.thread_handle != probe.thread || !Span(base, probe.game, 0x138) ||
        !Span(base, loader, 0x74) || (state != 4 && state != 5) || Word(base, loader + 0x70) ||
        !base[probe.game + 0xC] || Word(base, probe.game + 0xEC) || Word(base, probe.game + 0x44) != 2 ||
        Word(base, probe.game + 0x4C) != 1 || ctx.esp < 0x10000 || !Span(base, ctx.esp - 0x10000, 0x10000)) return false;
    uint16_t count = 0;
    const auto records = Word(base, probe.game + 0x54);
    if (!Read(base, probe.game + 0x50, count) || count != 2 || !Span(base, records, 2 * 0x130)) return false;
    unsigned indices = 0, locals = 0;
    for (unsigned i = 0; i < 2; ++i) {
        const auto record = records + i * 0x130, index = Word(base, record + 0x10C);
        const bool own = base[record + 0x128] != 0;
        if (index > 1 || (indices & (1u << index)) || Word(base, record + 0x114) != (own ? 0 : ~0u)) return false;
        indices |= 1u << index; locals += own;
    }
    if (locals != 1) return false;
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    uint32_t objects[2]{};
    if (!CampaignMembers(invoke, base, objects)) return false;
    game = probe.game; session = probe.session; local = invoke(0x17BBB0, 0);
    const auto first = Word(base, objects[0] + 0xC);
    remote = first == local ? Word(base, objects[1] + 0xC) : first;
    return true;
}
void DarkwatchOnlineEventRecord(const char* label, uint32_t a, uint32_t b, uint32_t c) {
    Record(label, a, b, c);
}
X86_FUNC(sub_000C224E) {
    const auto game = ctx.ecx, caller = Word(base, ctx.esp), actor = Word(base, uint64_t(ctx.esp) + 8);
    __imp__sub_000C224E(ctx, base);
    // Remote PlayerComponent binding omits the local spawn's AI-target refresh.
    if (game == probe.game && caller == 0xAD88B) RefreshCampaignPlayers(ctx, base, actor);
}
X86_FUNC(sub_0009C8BC) {
    const auto movement = ctx.ecx, caller = Word(base, ctx.esp);
    __imp__sub_0009C8BC(ctx, base);
    if (caller != 0x9CF9D || !CampaignPlayerCache(ctx, base) ||
        Word(base, probe.game + 0x44) != 2 || !Span(base, movement, 0xF8) ||
        Word(base, movement) != 0x41F878) return;
    const auto actor = Word(base, movement + 0xC), records = Word(base, probe.game + 0x54);
    if (!actor || (Word(base, records + 0x118) != actor && Word(base, records + 0x248) != actor)) return;
    const auto controller = Word(base, movement + 0xF4), physics = Word(base, controller);
    const auto phantom = Word(base, uint64_t(physics) + 0x9C), world = Word(base, uint64_t(physics) + 0xA4);
    if (!Span(base, controller, 4) || !Span(base, physics, 0xA8) ||
        !Span(base, phantom, 0x2C) || !Span(base, world, 4) || Word(base, phantom + 0x28) == 2) return;
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    uint32_t objects[2]{};
    if (!CampaignMembers(invoke, base, objects)) return;
    // Native death clears the standing collider only in mode 3; online campaign uses mode 0.
    call.ecx = controller;
    kernel::CallGuest(call, 0x83695, {2});
    Record("campaign-death-collision", actor, phantom, Word(base, phantom + 0x28));
}
X86_FUNC(sub_00215805) {
    const auto actor = Word(base, uint64_t(ctx.esp) + 4), manager = ctx.ecx;
    bool refresh = false;
    if (Enabled() && probe.campaign && probe.phase == 5 && probe.thread_bound &&
        ctx.thread_handle == probe.thread && ActorTokenHash(base, uint64_t(actor) + 0x50) == 0xB8B85844) {
        Record("campaign-proof-npc-remove", actor, manager, Word(base, actor + 0x90));
        for (unsigned i = 0; i < 24; ++i)
            Record("campaign-proof-npc-remove-stack", i, Word(base, uint64_t(ctx.esp) + i * 4));
    }
    if (Word(base, ctx.esp) == 0x2159CE && manager == Word(base, 0x4AC118) && CampaignPlayerCache(ctx, base)) {
        uint16_t count = 0; Read(base, manager + 0x10, count);
        const auto list = Word(base, manager + 0x14);
        for (unsigned i = 0; i < count; ++i) refresh |= actor && Word(base, list + i * 4) == actor;
    }
    __imp__sub_00215805(ctx, base);
    // Destruction clears native actor references; rebuild before AI can read the raw cache.
    if (refresh) RefreshCampaignPlayers(ctx, base, actor);
}
X86_FUNC(sub_000AC756) {
    const auto health = ctx.ecx, actor = Word(base, uint64_t(health) + 0xC);
    const auto message = Word(base, uint64_t(ctx.esp) + 4);
    const auto name = ActorTokenHash(base, uint64_t(actor) + 0x50);
    const bool trace = Enabled() && probe.campaign && probe.loading && probe.phase == 5 &&
        probe.thread_bound && ctx.thread_handle == probe.thread && Span(base, health, 0x140) &&
        Span(base, actor, 0x9C) && Span(base, message, 0x54) &&
        (name == 0x2079D5A5 || name == 0x8FB8116C || name == 0xF76B3563 || name == 0xB8B85844 ||
         ActorTokenHash(base, actor + 0x54) == 0xB5CF239F);
    if (trace) {
        Record("campaign-damage-target", actor, Word(base, message + 0x1C), Word(base, health + 0x9C));
        Record("campaign-damage-source", actor, Word(base, message + 8), Word(base, message + 0xC));
    }
    __imp__sub_000AC756(ctx, base);
    if (trace) Record("campaign-damage-result", actor, Word(base, health + 0x9C), Word(base, actor + 0x90));
}
X86_FUNC(sub_0005FC3B) {
    const auto component = ctx.ecx, caller = Word(base, ctx.esp);
    __imp__sub_0005FC3B(ctx, base);
    if ((ctx.eax & 255) || !Enabled() || !probe.campaign || !probe.title_online || !probe.loading || probe.phase != 5 ||
        !probe.thread_bound || ctx.thread_handle != probe.thread || caller != 0x5FC58 ||
        !Span(base, component, 0x28) || Word(base, component) != 0x41C698 || !base[component + 0x24] ||
        ctx.esp < 0x10000 || !Span(base, ctx.esp - 0x10000, 0x10000)) return;
    const auto game = probe.game, loader = Word(base, 0x4ACFBC), actor = Word(base, component + 0xC);
    const auto state = Word(base, uint64_t(loader) + 8);
    if (!Span(base, game, 0x138) || !Span(base, loader, 0x74) || !Span(base, actor, 0x9C) ||
        !base[game + 0xC] || Word(base, game + 0xEC) || Word(base, game + 0x44) != 2 ||
        Word(base, game + 0x4C) != 1 || (state != 3 && state != 4)) return;
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    uint32_t objects[2]{};
    if (!CampaignMembers(invoke, base, objects)) return;
    // Register the authored co-op point on both peers. Native F7106 still limits
    // that point to global player 1, and the host remains the spawn authority.
    ctx.eax = (ctx.eax & ~255u) | 1u;
    Record("campaign-coop-spawn-enabled", component, actor, ActorTokenHash(base, uint64_t(actor) + 0x50));
}
X86_FUNC(sub_000CBA42) {
    const auto helper = ctx.ecx, caller = Word(base, ctx.esp);
    const auto outer = Word(base, uint64_t(ctx.ebp) + 4), mode = Word(base, uint64_t(ctx.ebp) + 8);
    __imp__sub_000CBA42(ctx, base);
    if (!Enabled() || !probe.campaign || !probe.title_online || !probe.loading || probe.phase != 5 ||
        probe.role != 2 || !probe.thread_bound || ctx.thread_handle != probe.thread || probe.spawn_waiting ||
        caller != 0xCBC26 || outer != 0xCBFF0 || mode != 0 ||
        !Span(base, helper, 0x50) || Word(base, helper) != 0x425754 ||
        ctx.esp < 0x10000 || !Span(base, ctx.esp - 0x10000, 0x10000)) return;
    probe.spawn_waiting = true;
    struct Reset { ~Reset() { probe.spawn_waiting = false; } } reset;
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    const auto owner = Word(base, 0x4B4FC0);
    auto request = Word(base, helper + 0x4C);
    const auto started = Clock::now();
    auto requested = started;
    Record("campaign-initial-spawn-request", Word(base, helper + 8), request, Word(base, uint64_t(request) + 0xC));
    unsigned passes = 0;
    for (;;) {
        uint32_t objects[2]{};
        const bool owned = probe.phase == 5 && Word(base, 0x4B4FC0) == owner && Span(base, owner, 0x68) &&
            Word(base, helper + 0x4C) == request && Span(base, request, 0xC8) && CampaignMembers(invoke, base, objects);
        const auto status = Word(base, uint64_t(request) + 0xC);
        if (owned && status == 2 && int32_t(Word(base, helper + 0x44)) >= 0) {
            Record("campaign-initial-spawn-ready", Word(base, helper + 0x44), passes,
                uint32_t(std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - started).count()));
            return;
        }
        const bool not_ready = status == 2 && Word(base, helper + 0x44) == ~0u;
        // The host may still be watching the intro; only its valid spawn reply releases the client.
        if (!owned || (status != 1 && !not_ready) || Clock::now() - started > std::chrono::minutes(5)) {
            Record("campaign-initial-spawn-failed", status, Word(base, helper + 0x44), passes);
            // shortcut: diagnostic-only abort; production must return a join error before loading.
            std::_Exit(3);
        }
        if (not_ready && Clock::now() - requested >= std::chrono::milliseconds(100)) {
            // The host can answer before registering its authored co-op spawn point.
            invoke(0xCB2DA, helper); // Native completion disposes the finished request.
            if (Word(base, helper + 0x4C)) std::_Exit(3);
            invoke(0xCBA42, helper);
            request = Word(base, helper + 0x4C);
            requested = Clock::now();
            Record("campaign-initial-spawn-retry", request, passes);
        }
        // Keep the stack helper alive until its host-selected spawn result arrives.
        invoke(0x17CBF0, 0);
        if (probe.phase == 5 && Word(base, 0x4B4FC0) == owner && Word(base, 0x4AF628) == probe.session)
            invoke(0xCD3F3, 0);
        ++passes;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}
X86_FUNC(sub_001A7390) {
    if (Enabled() && probe.role == 2 && probe.phase == 2 && ctx.ecx == probe.lan) {
        const uint32_t description = Word(base, uint64_t(ctx.esp) + 4);
        std::string provider, application, expected_application, name, url;
        darkwatch::OnlineSessionUrlFields fields;
        unsigned valid = 0;
        if (String(base, Word(base, description), provider) && provider == "LAN") valid |= 1;
        if (String(base, Word(base, 0x495324), expected_application) && !expected_application.empty() &&
            String(base, Word(base, uint64_t(description) + 8), application) && application == expected_application) valid |= 2;
        if (String(base, Word(base, uint64_t(description) + 28), name) && name == "Darkwatch") valid |= 4;
        if (String(base, Word(base, uint64_t(description) + 16), url) && darkwatch::ParseOnlineSessionUrl(url, fields)) valid |= 8;
        if (valid == 15) {
            { std::lock_guard lock(probe.mutex); if (probe.phase == 2) probe.discovered = url; }
            Record("discovery-result", uint32_t(url.size()));
        } else Record("discovery-rejected", valid, uint32_t(url.size()), uint32_t(name.size()));
    }
    __imp__sub_001A7390(ctx, base);
}
X86_FUNC(sub_0001B54C) {
    if (Enabled() && probe.phase == 3 && ctx.thread_handle == probe.thread && ctx.ecx == 0 && Word(base, ctx.esp) == 0x2113F0)
        probe.completion = int(Word(base, uint64_t(ctx.esp) + 4));
    __imp__sub_0001B54C(ctx, base);
}
X86_FUNC(sub_001C1D77) {
    const auto frontend = Word(base, 0x4B0864), data = Word(base, frontend);
    if (Enabled() && probe.role == 1 && probe.phase == 5 && frontend && ctx.ecx == frontend &&
        Word(base, ctx.esp) == 0x1C5EAC && Span(base, data, 0x70) &&
        !Word(base, uint64_t(data) + 0x6C) && !Word(base, 0x4B08A4)) {
        // A direct LAN join has no Xbox Live slot reservation to consume.
        Record("lan-participant-no-reservation", Word(base, uint64_t(ctx.esp) + 4));
        ctx.esp += 8; return;
    }
    __imp__sub_001C1D77(ctx, base);
}
X86_FUNC(sub_001C1799) {
    const auto caller = Word(base, ctx.esp);
    __imp__sub_001C1799(ctx, base);
    if (Enabled() && probe.campaign && probe.loading && probe.phase == 5) {
        static unsigned observed = 0;
        if (observed++ < 48) Record("campaign-status-query", caller, ctx.eax, Word(base, uint64_t(Word(base, 0x4ACFBC)) + 0x70));
    }
    if (!Enabled() || !probe.campaign || !probe.loading || probe.phase != 5 || caller != 0xC5A06) return;
    const auto game = probe.game, loader = Word(base, 0x4ACFBC), roster = Word(base, uint64_t(game) + 0x70);
    const auto stats = Word(base, Word(base, uint64_t(game) + 0xA8));
    X86Context call = ctx;
    auto invoke = [&](uint32_t fn, uint32_t self) { call.ecx = self; return kernel::CallGuest(call, fn, {}); };
    uint32_t objects[2]{};
    if (Span(base, game, 0x138) && Span(base, roster, 0xF4) && Word(base, uint64_t(loader) + 8) == 4 &&
        Span(base, stats, 0xBC) && Word(base, stats + 0xB8) == game + 0xA8 &&
        CampaignMembers(invoke, base, objects) && base[game + 0xC] &&
        Word(base, game + 0x44) == 2 && Word(base, game + 0x4C) == 1) {
        static bool recorded = false;
        if (!recorded) { recorded = true; Record("campaign-lan-loader-status", ctx.eax, probe.session, Word(base, roster + 0x2C)); }
        ctx.eax = 1;
    }
}
X86_FUNC(sub_000C326C) {
    const bool restore_timing = Enabled() && probe.campaign && probe.title_online &&
        base == kernel::g_base && ctx.ecx == probe.game;
    if (Enabled() && probe.campaign && probe.title_online) {
        const auto loader = Word(base, 0x4ACFBC);
        Record("campaign-native-abort", Word(base, ctx.esp), Word(base, uint64_t(loader) + 8), Word(base, uint64_t(loader) + 0x70));
    }
    __imp__sub_000C326C(ctx, base);
    if (restore_timing) {
        if (probe.position_interval_owned && Word(base, 0x48E528) == 8) Put(base, 0x48E528, 150);
        probe.position_interval_owned = false;
        for (unsigned i = 0; i < std::size(kBlendFloors); ++i)
            if ((probe.blend_floors_owned & (1u << i)) && Word(base, kBlendFloors[i]) == 16 &&
                Word(base, kBlendFloors[i] - 4) == 16) {
                Put(base, kBlendFloors[i], 250);
                Put(base, kBlendFloors[i] - 4, 1000);
            }
        probe.blend_floors_owned = 0;
        if (probe.receive_delay_owned && Word(base, 0x4B084C) == 0) Put(base, 0x4B084C, 200);
        probe.receive_delay_owned = false;
        if (probe.position_error_owned && PositionErrorMatches(base, true))
            for (const auto& field : kPositionError) Put(base, field[0], field[1]);
        probe.position_error_checked = probe.position_error_owned = false;
    }
}
X86_FUNC(sub_000C591E) {
    if (Enabled() && probe.campaign && probe.loading) {
        Record("campaign-network-failure", Word(base, ctx.esp), Word(base, uint64_t(ctx.ecx) + 8), Word(base, uint64_t(ctx.ecx) + 0x70));
        Record("campaign-network-budget", Word(base, 0x4B4FCC), Word(base, 0x4B4FC0), Word(base, 0x4AF628));
    }
    __imp__sub_000C591E(ctx, base);
}
#define PROBE_CREATE_RETURN(name) \
X86_FUNC(sub_##name) { \
    const bool capture = Enabled() && probe.creating; \
    const uint32_t self = ctx.ecx, argument = capture ? Word(base, uint64_t(ctx.esp) + 4) : 0; \
    __imp__sub_##name(ctx, base); \
    if (capture) Record("create-" #name, ctx.eax, self, argument); \
}
PROBE_CREATE_RETURN(00179B00)
PROBE_CREATE_RETURN(0017E850)
PROBE_CREATE_RETURN(0016DF20)
#undef PROBE_CREATE_RETURN
X86_FUNC(sub_0018D1B0) {
    const bool capture = Enabled() && probe.creating;
    if (capture) {
        uint32_t node = Word(base, 0x4AF804);
        for (unsigned i = 0; node && i < 16; ++i) {
            Record("required-handle", node, Word(base, node), Word(base, uint64_t(node) + 8));
            node = Word(base, uint64_t(node) + 8);
        }
        probe.resolving = true;
    }
    __imp__sub_0018D1B0(ctx, base);
    if (capture) { probe.resolving = false; Record("create-0018D1B0", ctx.eax); }
}
X86_FUNC(sub_0016E530) {
    const bool capture = Enabled() && probe.resolving;
    const uint32_t self = ctx.ecx, handle = capture ? Word(base, uint64_t(ctx.esp) + 4) : 0;
    __imp__sub_0016E530(ctx, base);
    if (capture) Record("resolve-required", handle, Word(base, self), Word(base, uint64_t(self) + 4));
}
X86_FUNC(sub_0016EEC0) {
    if (Enabled() && probe.creating) Record("create-error", Word(base, uint64_t(ctx.esp) + 12));
    __imp__sub_0016EEC0(ctx, base);
}
#endif
