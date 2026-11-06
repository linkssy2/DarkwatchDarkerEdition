#include "character_runtime.h"
#include "carry_all_weapons.h"
#include "sight_mode.h"
#include "coop_respawn_weapons.h"
#include "character_secondary.h"
#include "character_selection.h"
#include "online_characters.h"
#include "kernel/kernel.h"
#include "core/log.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <string>
#include <vector>

namespace {
struct Type { uint32_t id, vtable, accessor; };
constexpr Type types[]{
    {0x495844, 0x4396D4, 0x1BFFF9}, // ModelResource
    {0x495660, 0x439210, 0x1BF76A}, // SkeletonLayoutResource
    {0x49582C, 0x4393AC, 0x1BFE09}, // LocatorResource
    {0x49556C, 0x439618, 0x1BEAFF}, // HavokObjectResource
    {0x4955CC, 0x43958C, 0x1BD94F}, // AnimatedCharacterResource
    {0x4955C8, 0x439114, 0x1BF0EF}, // BoneAnimatedResource
    {0x49D594, 0x440694, 0x326C19}, // AnimatedPathResource
    {0x495600, 0x43919C, 0x1BF5DC}, // EventSequenceResource
    {0x495870, 0x439714, 0x1C0433}, // ParticleEffectResource
    {0x495830, 0x4393C0, 0x1BFB70}, // TexDictionaryResource
};
struct Dependency { uint32_t hash; uint8_t type; uint32_t modes; };
struct Route { uint32_t hash; uint8_t mode; bool audio; };
#include "character_runtime_data.h"
#include "character_cinematic_routes.h"

struct Held { uint32_t record, data; };
std::vector<Held> held;
// Count: bits 0..1; Cassidy slots: 2..3; spectral P2/P1: 4/5; additional IDs: 8..15.
std::atomic<unsigned> mission{0};
std::atomic<unsigned> unavailable{0};
std::atomic<unsigned> reported{0};
uint32_t owner = 0;
unsigned mission_mode = 0;
unsigned local_count = 0, online_ordinal = 2;
// File reads can run on the loader thread: publish the choice and audited chapter together.
std::atomic<uint64_t> cinematic_mission{0};

bool Span(const uint8_t* base, uint64_t address, uint64_t bytes) {
    if (!base || !address || !bytes || address + bytes > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~uint64_t(mem::kPage - 1); page < address + bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t address, T& value) {
    if (!Span(base, address, sizeof(T))) return false;
    std::memcpy(&value, base + address, sizeof(T)); return true;
}
template<class T> void Write(uint8_t* base, uint32_t address, T value) {
    std::memcpy(base + address, &value, sizeof(T));
}
void Reject(const uint8_t* base, unsigned player, const char* gate, unsigned family, const char* name,
            const Dependency* dependency = nullptr, uint32_t record = 0, const char* detail = "-") {
    // An unavailable selection is an error, but repeated respawns must not flood the report.
    if (player >= 2 || (reported.fetch_or(1u << player) & (1u << player))) return;
    uint32_t type = 0, vtable = 0, state = 0, uses = 0; uint16_t refs = 0;
    if (dependency) Read(base, types[dependency->type].id, type);
    if (record) {
        Read(base, record, vtable); Read(base, uint64_t(record) + 8, state);
        Read(base, uint64_t(record) + 4, refs); Read(base, uint64_t(record) + 12, uses);
    }
    LOGE("Character fallback: player=%u gate=%s family=%u actor=%s detail=%s type=%u hash=%08X record=%08X vtable=%08X state=%u refs=%u uses=%u",
         player + 1, gate, family, name, detail, type, dependency ? dependency->hash : 0,
         record, vtable, state, unsigned(refs), uses);
}
bool String(const uint8_t* base, uint64_t address, std::string& value, unsigned limit = 255) {
    value.clear();
    for (unsigned i = 0; i <= limit; ++i) {
        char c;
        if (!Read(base, address + i, c)) return false;
        if (!c) return true;
        if (i == limit || static_cast<unsigned char>(c) > 127) return false;
        value += c;
    }
    return false;
}
bool OwnedString(const uint8_t* base, uint32_t address, std::string& value) {
    uint32_t handle;
    return Read(base, address, handle) && handle && String(base, uint64_t(handle) + 2, value, 63);
}
bool CassidyActor(const std::string& name) {
    return name == "CassidySolo" || name == "CassidyPlayerTwo" ||
        name == "CassidySpectralPlayerTwo" || name == "CassidySpectralSolo";
}
unsigned Selection(unsigned state, unsigned player) {
    const unsigned added = (state >> (8 + 4 * player)) & 15;
    if (added) return added;
    if (!(state & (4u << player))) return 0;
    return state & (player ? 16 : 32) ? 2 : 1;
}
bool Roster(unsigned state) { return (state & 0xFF00) != 0; }
struct Presentation { const char* solo; const char* coop; const char* solo_hands; const char* coop_hands; };
constexpr Presentation presentations[]{
    {"Chaz", "JerichoCoop", "ChazHands", "ChazHands"},
    {"CassidySolo", "CassidyPlayerTwo", "CassidySoloHands", "CassidyPlayerTwoHands"},
    {"CassidySpectralSolo", "CassidySpectralPlayerTwo", "CassidySpectralSoloHands", "CassidySpectralHands"},
    {"CivilianJerichoSolo", "CivilianJerichoCoop", "CivilianJerichoHands", "CivilianJerichoHands"},
    {"TrooperSolo", "TrooperCoop", "ChazHands", "ChazHands"},
    {"BlueTrooperSolo", "BlueTrooperCoop", "BlueTrooperHands", "BlueTrooperHands"},
    {"RedTrooperSolo", "RedTrooperCoop", "RedTrooperHands", "RedTrooperHands"},
    {"TalaSolo", "TalaCoop", "TalaSoloHands", "TalaCoopHands"},
    {"VampireTalaSolo", "VampireTalaCoop", "VampireTalaSoloHands", "VampireTalaCoopHands"},
    {"BossTalaSolo", "BossTalaCoop", "BossTalaSoloHands", "BossTalaCoopHands"},
};
static_assert(std::size(presentations) == darkwatch::settings::kCharacterCount);
static_assert(std::size(presentations) <= 16); // Mission choices occupy four bits per player.
unsigned Family(unsigned choice, bool coop) {
    if (choice >= 3) return 1u << (5 + 2 * (choice - 3) + unsigned(coop));
    return choice == 2 ? (coop ? 8 : 16) : choice == 1 ? (coop ? 2 : 1) : 4;
}
bool PlayerTemplate(const std::string& name, bool& solo, unsigned& choice) {
    for (unsigned i = 0; i < std::size(presentations); ++i) {
        if (i && name == presentations[i].solo) { solo = true; choice = i; return true; }
        if (name == presentations[i].coop) { solo = false; choice = i; return true; }
    }
    return false;
}
uint32_t Hash(std::string value, bool resource = false) {
    uint32_t crc = ~0u;
    for (unsigned char c : value) {
        if (resource && c == '.') break;
        if (c == '\\') c = '/';
        if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
        crc ^= c;
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
    return ~crc;
}
bool PathEquals(const std::string& path, const char* expected) {
    const size_t prefix = !path.empty() && (path.front() == '/' || path.front() == '\\') ? 1 : 0;
    return path.size() == std::strlen(expected) + prefix &&
        std::equal(path.begin() + prefix, path.end(), expected, [](char actual, char wanted) {
            if (actual == '\\') actual = '/';
            if (actual >= 'A' && actual <= 'Z') actual += 'a' - 'A';
            return actual == wanted;
        });
}
bool SelectedCinematicPath(std::string& path, unsigned state) {
    const unsigned choice = Selection(state, 0);
    const uint64_t snapshot = cinematic_mission.load();
    const uint32_t chapter_index = uint32_t(snapshot) - 1;
    if (!snapshot || unsigned(snapshot >> 32) != state || chapter_index >= std::size(cinematic_files) ||
        choice >= std::size(presentations) || ((state & 3) != 1 && (state & 3) != 2)) return false;
    const char* chapter = cinematic_files[chapter_index].chapter;
    auto match = [&](const CinematicRoute& r) {
        return !std::strcmp(chapter, r.chapter) && PathEquals(path, r.path);
    };
    for (const auto& r : cinematic_files) {
        if (match(r)) {
            // Jericho keeps the original poses/events; only his cinematic body changes.
            if (!choice && !std::strstr(r.path, "_actors.bxml")) return false;
            path.insert(path.rfind('.'), "_selectedcharacter" + std::to_string(choice));
            return true;
        }
    }
    if (!choice) return false;
    // Keep original resource keys/events; only the matching skeleton's SANM payload changes.
    // Chapter ownership also prevents remapping a Jericho clip reused by story Tala in M12.
    for (const auto& r : cinematic_clips) {
        if (match(r)) {
            path = "characters/player_cinematic/" + std::to_string(choice) + "/" + (std::strrchr(r.path, '/') + 1);
            return true;
        }
    }
    return false;
}
bool GuestCalls(const X86Context& ctx, uint8_t* base) {
    return base == kernel::g_base && ctx.esp >= 0x2000 && Span(base, uint64_t(ctx.esp) - 0x2000, 0x2000);
}
uint32_t Call(const X86Context& ctx, uint32_t object, uint32_t function) {
    X86Context call = ctx; call.ecx = object;
    return kernel::CallGuest(call, function, {});
}
void Release(const X86Context& ctx, size_t first = 0) {
    while (held.size() > first) {
        const Held h = held.back(); held.pop_back();
        Call(ctx, h.data, 0x2172F1);
        Call(ctx, h.record, 0x2172F1);
    }
}
uint32_t Find(const uint8_t* base, uint32_t manager, uint32_t type, uint32_t group, uint32_t hash) {
    uint32_t buckets, capacity;
    if (!Read(base, manager, buckets) || !Read(base, uint64_t(manager) + 4, capacity) ||
        !capacity || capacity > 65536) return 0;
    const uint64_t bucket = uint64_t(buckets) + 8ull * ((type ^ group ^ hash) % capacity);
    uint16_t count; uint32_t rows;
    if (!Read(base, bucket, count) || !Read(base, bucket + 4, rows) ||
        count > 4096 || (count && !Span(base, rows, 24ull * count))) return 0;
    for (unsigned i = 0; i < count; ++i) {
        const uint32_t row = rows + 24 * i;
        uint32_t key[4]; std::memcpy(key, base + row + 4, sizeof(key));
        if (key[0] == type && key[1] == group && key[2] == hash) return key[3];
    }
    return 0;
}
uint32_t Resident(const uint8_t* base, uint32_t manager, const Dependency& d) {
    uint32_t type, policy, group;
    if (!Read(base, types[d.type].id, type) || type == ~0u ||
        !Read(base, uint64_t(manager) + 0x5C, policy) || !Read(base, uint64_t(manager) + 0x60, group)) return 0;
    if (policy == 1) group = ~1u;
    uint32_t record = Find(base, manager, type, group, d.hash);
    if (!record && group != 0x04277DC9) record = Find(base, manager, type, 0x04277DC9, d.hash);
    if (!record && group) record = Find(base, manager, type, 0, d.hash);
    return record;
}
bool Acquire(const X86Context& ctx, uint8_t* base, unsigned mode, unsigned player, const char* name) {
    uint32_t manager;
    if (!Read(base, 0x4AC17C, manager) || !manager || !GuestCalls(ctx, base)) {
        Reject(base, player, "resource-manager", mode, name); return false;
    }
    const size_t first = held.size();
    for (const auto& d : dependencies) {
        if (!(d.modes & mode)) continue;
        const uint32_t record = Resident(base, manager, d);
        const auto& t = types[d.type];
        uint32_t vtable = 0, state = 0, uses = 0, accessor = 0; uint16_t refs = 0;
        if (!Span(base, record, 0x20) || !Read(base, record, vtable) || vtable != t.vtable ||
            !Read(base, uint64_t(vtable) + 4, accessor) || accessor != t.accessor ||
            !Read(base, uint64_t(record) + 8, state) || state != 3 ||
            !Read(base, uint64_t(record) + 4, refs) || !refs || refs == 0xFFFF ||
            !Read(base, uint64_t(record) + 12, uses) || uses == ~0u) {
            Reject(base, player, "resource", mode, name, &d, record);
            Release(ctx, first); return false;
        }
        if (std::any_of(held.begin(), held.end(), [record](const Held& h) { return h.record == record; })) continue;
        // The map reference and the typed-data reference have separate native lifetimes.
        Write(base, record + 4, uint16_t(refs + 1));
        const uint32_t data = Call(ctx, record, 0x1BD8E1);
        uint16_t data_refs;
        if (!data) {
            Reject(base, player, "resource-accessor", mode, name, &d, record);
            Call(ctx, record, 0x2172F1); Release(ctx, first); return false;
        }
        if (!Read(base, uint64_t(data) + 4, data_refs) || data_refs == 0xFFFF) {
            // A native accessor owns this result; malformed returned objects are fatal native corruption.
            x86_trap(const_cast<X86Context&>(ctx), data, "Invalid character resource handle");
        }
        Write(base, data + 4, uint16_t(data_refs + 1));
        held.push_back({record, data});
    }
    return true;
}
bool Actor(const uint8_t* base, uint32_t manager, const std::string& name) {
    uint16_t count; uint32_t rows;
    if (!Read(base, uint64_t(manager) + 8, count) || !count || count > 1024 ||
        !Read(base, uint64_t(manager) + 12, rows) || !Span(base, rows, 4ull * count)) return false;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t actor; std::string actual; uint8_t enabled;
        if (!Read(base, uint64_t(rows) + 4 * i, actor) || !actor) return false;
        if (OwnedString(base, actor, actual) && actual == name)
            return Read(base, uint64_t(actor) + 0x13, enabled) && enabled;
    }
    return false;
}
bool CoopTemplate(const uint8_t* base, uint32_t manager, bool& coop) {
    uint16_t count; uint32_t rows;
    if (!Read(base, uint64_t(manager) + 0x14, count) || count > 256 ||
        !Read(base, uint64_t(manager) + 0x18, rows) || (count && !Span(base, rows, 8ull * count))) return false;
    std::string resolved = "Chaz";
    for (unsigned i = 0; i < count; ++i) {
        std::string from, to;
        if (!OwnedString(base, rows + 8 * i, from) || !OwnedString(base, rows + 8 * i + 4, to)) return false;
        if (from == resolved) resolved = to;
    }
    if (resolved != "Chaz" && resolved != "CoOpChaz") return false;
    coop = resolved == "CoOpChaz"; return true;
}
void Reset(const X86Context& ctx, uint8_t* base) {
    DarkwatchCharacterSecondaryReset();
    DarkwatchResetWeaponChoices();
    DarkwatchResetSightMode();
    mission.store(0);
    mission_mode = 0;
    local_count = 0; online_ordinal = 2;
    cinematic_mission.store(0);
    unavailable.store(0);
    reported.store(0);
    if (!held.empty() && !GuestCalls(ctx, base)) return;
    Release(ctx); owner = 0;
}
} // namespace

void DarkwatchCharacterResourceHeap(X86Context& ctx, uint8_t* base) {
    uint32_t bytes, caller, initial[4];
    if (base != kernel::g_base || ctx.ecx != ctx.esi || ctx.eax ||
        !Read(base, ctx.esp, bytes) || bytes != 0x16800 ||
        !Read(base, uint64_t(ctx.esp) + 8, caller) || caller != 0x1B6D44 ||
        !Read(base, ctx.esi, initial) ||
        std::any_of(std::begin(initial), std::end(initial), [](uint32_t v) { return v != 0; })) return;
    // Extra character keys need both old and new resource-map rows during native rehash.
    Write(base, ctx.esp, uint32_t(1024 * 1024));
}

void DarkwatchStringHeap(X86Context& ctx, uint8_t* base) {
    uint32_t bytes, caller, initial[3];
    if (base != kernel::g_base || ctx.ecx != 0x4B79F8 || ctx.esi != ctx.ecx || ctx.eax ||
        !Read(base, ctx.esp, bytes) || bytes != 0xC8000 ||
        !Read(base, uint64_t(ctx.esp) + 8, caller) || caller != 0x217D03 ||
        !Read(base, ctx.esi, initial) ||
        std::any_of(std::begin(initial), std::end(initial), [](uint32_t v) { return v != 0; })) return;
    // Expanded content exceeds the original string pool during native table rehash.
    Write(base, ctx.esp, uint32_t(2 * 1024 * 1024));
}

void DarkwatchReferenceMapHeap(X86Context& ctx, uint8_t* base) {
    uint32_t bytes, initial[3], shared[2];
    if (base != kernel::g_base || ctx.ecx != ctx.esi || ctx.eax ||
        !Read(base, ctx.esp, bytes) || bytes != 0xF000 ||
        !Read(base, ctx.esi, initial) || !Read(base, 0x4B7B0C, shared) ||
        shared[0] || shared[1] ||
        std::any_of(std::begin(initial), std::end(initial), [](uint32_t v) { return v != 0; })) return;
    // Expanded character animations need old and new reference-map buckets during rehash.
    Write(base, ctx.esp, uint32_t(1024 * 1024));
}

void DarkwatchCharacterMissionEnd(X86Context& ctx, uint8_t* base) {
    if (ctx.ecx == owner) { DarkwatchResetRespawnWeapons(); Reset(ctx, base); }
}

void DarkwatchCharacterMissionBegin(X86Context& ctx, uint8_t* base) {
    DarkwatchResetRespawnWeapons();
    Reset(ctx, base);
    if (!held.empty()) return;
    uint32_t count, mode;
    if (!Read(base, uint64_t(ctx.esi) + 0x4C, count) || (count != 1 && count != 2) ||
        !Read(base, uint64_t(ctx.esi) + 0xEC, mode)) return;
    if (mode > 1 || (mode == 1 && count != 1)) return;
    mission_mode = mode;
    auto choices = darkwatch::settings::characters();
#ifndef XBE_RELEASE
    unsigned online_local = 2;
    if (!mode && count == 1 && DarkwatchOnlineCharacterChoices(ctx, base, ctx.esi, choices, online_local))
        online_ordinal = online_local;
#endif
    local_count = count;
    if (online_ordinal < 2) count = 2;
    for (auto& choice : choices)
        if (unsigned(choice) >= std::size(presentations)) choice = darkwatch::settings::Character::Jericho;
    const auto cassidy = darkwatch::settings::Character::Cassidy;
    const auto spectral = darkwatch::settings::Character::SpectralCassidy;
    const bool selected[]{choices[0] == cassidy || choices[0] == spectral,
                          choices[1] == cassidy || choices[1] == spectral};
    owner = ctx.esi;
    if (!DarkwatchCharacterContentReady()) {
        const unsigned failed = count == 2 ? 3 : unsigned(choices[0]) ? 1 : 0;
        unavailable.store(failed);
        for (unsigned player = 0; player < count; ++player)
            if (failed & (1u << player)) Reject(base, player, "content", 0,
                presentations[unsigned(choices[player])].solo);
        return;
    }
    // The chapter is assigned before this hook, even when its preload list is cached.
    std::string chapter;
    const bool known_chapter = OwnedString(base, owner, chapter);
    uint32_t cinematic_chapter = 0;
    if (known_chapter && mode == 0) {
        std::string normalized = chapter;
        for (char& c : normalized) if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        const auto route = std::find_if(std::begin(cinematic_files), std::end(cinematic_files),
            [&](const CinematicRoute& r) { return normalized == r.chapter; });
        if (route != std::end(cinematic_files)) cinematic_chapter = unsigned(route - std::begin(cinematic_files)) + 1;
    }
    const bool spectral_two = count == 2 && (choices[1] == spectral ||
        (choices[1] == cassidy && known_chapter &&
         std::find(std::begin(spectral_chapters), std::end(spectral_chapters), Hash(chapter)) != std::end(spectral_chapters)));
    const unsigned state = count | (selected[0] ? 4 : 0) | (count == 2 && selected[1] ? 8 : 0) |
                  (spectral_two ? 16 : 0) | (choices[0] == spectral ? 32 : 0) |
                  (unsigned(choices[0]) >= 3 ? unsigned(choices[0]) << 8 : 0) |
                  (count == 2 && unsigned(choices[1]) >= 3 ? unsigned(choices[1]) << 12 : 0);
    if (cinematic_chapter) cinematic_mission.store((uint64_t(state) << 32) | cinematic_chapter);
    mission.store(state);
}

void DarkwatchCharacterFile(X86Context& ctx, uint8_t* base) {
    const unsigned state = mission.load();
    if (ctx.ebp < 0x108 || !Span(base, uint64_t(ctx.ebp) - 0x108, 0x100)) return;
    std::string path;
    if (!String(base, ctx.ebp - 0x108, path)) return;
    const auto path_hash = Hash(path);
    // Startup's recorded stream embeds the old actor table, before character selection.
    constexpr char startup_path[] = "streaming/set0_resources.str";
    const bool startup = PathEquals(path, startup_path) && DarkwatchCharacterContentReady();
    if (!state && !startup) return;
    if (state && SelectedCinematicPath(path, state)) {
        std::memcpy(base + ctx.ebp - 0x108, path.c_str(), path.size() + 1);
        return;
    }
    const bool cassidy = state & 12;
    const bool roster = Roster(state);
    // Carryable weapons expand every campaign list; missing bundles use ordinary archive reads.
    const bool stream = path.size() >= 15 &&
        Hash(path.substr(path.size() - 15)) == Hash("_streamfile.str");
    const bool audio_stream = path.size() > 9 &&
        Hash(path.substr(path.size() - 9)) == Hash("Audio.str");
    std::string audio_path;
    if (audio_stream) {
        // Audio bundles embed the old bank layout too; use its verified individual-file fallback.
        audio_path = path;
        for (char& c : audio_path) {
            if (c == '\\') c = '/';
            if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        }
        const auto directory = audio_path.rfind("/streaming/");
        if (directory == std::string::npos) return;
        audio_path.replace(directory, 11, "/resources/audio/");
        audio_path.replace(audio_path.size() - 9, 9, ".bblf");
    }
    const auto hash = audio_stream ? Hash(audio_path) :
        stream ? Hash(path.substr(0, path.size() - 15) + "_resources.bxml") : path_hash;
    const auto route = std::find_if(std::begin(routes), std::end(routes), [hash](const Route& r) { return r.hash == hash; });
    if (!startup) {
        if (route == std::end(routes) || (stream && (route->mode != 1 || route->audio)) ||
            (audio_stream && !route->audio)) return;
        if (!cassidy && !roster && !stream && !audio_stream &&
            ((state & 3) != 2 || route->audio || route->mode != 2)) return;
    }
    const bool spectral = !startup && !route->audio && (state & 48);
    std::string suffix = spectral ? "_cassidy_spectral" : startup || cassidy ? "_cassidy" : "_jericho";
    if (!startup && roster) {
        unsigned first = Selection(state, 0), second = Selection(state, 1);
        if ((state & 3) == 2 && first > second) std::swap(first, second);
        suffix = "_roster_" + std::to_string(first);
        if ((state & 3) == 2) suffix += "_" + std::to_string(second);
    }
    const auto dot = path.rfind('.');
    if (dot == std::string::npos || path.size() + suffix.size() > 255) return;
    path.insert(dot, suffix);
    std::memcpy(base + ctx.ebp - 0x108, path.c_str(), path.size() + 1);
}

bool DarkwatchCharacterPrepareOnline(const X86Context& ctx, uint8_t* base) {
    if (online_ordinal == 2) return true;
    const auto state = mission.load();
    uint32_t manager = 0, count = 0; bool coop = false;
    if ((state & 3) != 2 || !owner || !Read(base, uint64_t(owner) + 0x4C, count) || count != 1 ||
        !Read(base, 0x4AD370, manager) || !CoopTemplate(base, manager, coop)) {
        LOGE("Online character preparation: state=%08X owner=%08X count=%u manager=%08X ordinal=%u",
             state, owner, count, manager, online_ordinal);
        return false;
    }
    for (unsigned player = 0; player < 2; ++player) {
        const auto choice = Selection(state, player);
        if (!choice && !coop) continue;
        const auto& p = presentations[choice];
        const char* name = coop ? p.coop : p.solo;
        const char* hands = coop ? p.coop_hands : p.solo_hands;
        const auto family = Family(choice, coop);
        if (!Actor(base, manager, name)) { Reject(base, player, "online-body", family, name); return false; }
        if (!Actor(base, manager, hands)) { Reject(base, player, "online-hands", family, hands); return false; }
        const bool tala = darkwatch::settings::TalaCharacter(darkwatch::settings::Character(choice));
        const char* failure = "-";
        if ((choice == 1 || choice == 2 || tala) && !DarkwatchCharacterAudioReady(base, &failure, tala)) {
            Reject(base, player, "online-audio", family, name, nullptr, 0, failure); return false;
        }
        if (!Acquire(ctx, base, family, player, name)) return false;
    }
    return true;
}

void DarkwatchCharacterSpawn(X86Context& ctx, uint8_t* base) {
    const unsigned state = mission.load();
    uint32_t literal, game, manager, count, mode, actor_manager;
    if (!state || ctx.edi >= (state & 3) || ctx.ebp < 0xD0 || ctx.esp != ctx.ebp - 0xD0 ||
        !Span(base, uint64_t(ctx.ebp) - 0xD0, 0xE8) ||
        !Read(base, ctx.esp, literal) || literal != 0x425814 ||
        !Read(base, uint64_t(ctx.ebp) + 0x10, game) || game != owner ||
        !Read(base, uint64_t(ctx.ebp) - 8, manager) || uint64_t(game) + 0x40 != manager ||
        !Read(base, uint64_t(game) + 0x4C, count) || count != local_count || ctx.edi >= count ||
        !Read(base, uint64_t(game) + 0xEC, mode) || mode != mission_mode ||
        !Read(base, 0x4AD370, actor_manager) || !actor_manager) return;
    const unsigned ordinal = online_ordinal < 2 ? online_ordinal : ctx.edi;
    const unsigned choice = Selection(state, ordinal);
    if (choice >= std::size(presentations)) return;
    const bool cassidy = choice == 1 || choice == 2;
    if (choice || count == 2) unavailable.fetch_or(1u << ctx.edi);
    bool coop;
    if (!CoopTemplate(base, actor_manager, coop)) {
        if (choice || count == 2) Reject(base, ctx.edi, "alias", 0, presentations[choice].solo);
        return;
    }
    if (online_ordinal < 2 && !DarkwatchCharacterPrepareOnline(ctx, base)) return;
    if (!choice && !coop) { unavailable.fetch_and(~(1u << ctx.edi)); return; }
    const unsigned family = Family(choice, coop);
    const auto& presentation = presentations[choice];
    const char* name = coop ? presentation.coop : presentation.solo;
    const char* hands = coop ? presentation.coop_hands : presentation.solo_hands;
    if (!Actor(base, actor_manager, name)) { Reject(base, ctx.edi, "body", family, name); return; }
    if (!Actor(base, actor_manager, hands)) { Reject(base, ctx.edi, "hands", family, hands); return; }
    const char* audio_failure = "-";
    const bool tala = darkwatch::settings::TalaCharacter(darkwatch::settings::Character(choice));
    if ((cassidy || tala) && !DarkwatchCharacterAudioReady(base, &audio_failure, tala)) {
        Reject(base, ctx.edi, "audio", family, name, nullptr, 0, audio_failure); return;
    }
    if (!Acquire(ctx, base, family, ctx.edi, name)) return;
    const uint32_t scratch = ctx.ebp - 0xC0;
    std::memcpy(base + scratch, name, std::strlen(name) + 1);
    Write(base, ctx.esp, scratch);
    unavailable.fetch_and(~(1u << ctx.edi));
}

void DarkwatchCharacterScriptType(X86Context& ctx, uint8_t* base) {
    const unsigned state = mission.load();
    uint32_t actor, count, mode, category, text;
    std::string character;
    if (!state || !owner || ctx.ebp < 4 ||
        !Read(base, uint64_t(owner) + 0x4C, count) || count != local_count ||
        !Read(base, uint64_t(owner) + 0xEC, mode) || mode != mission_mode ||
        !Read(base, uint64_t(ctx.ebp) - 4, actor) || !actor ||
        !Read(base, uint64_t(actor) + 0x98, category) || category != 9 ||
        !Read(base, uint64_t(actor) + 0x50, text) || !text ||
        uint64_t(text) + 2 != ctx.esi || !OwnedString(base, actor + 0x50, character)) return;
    bool solo; unsigned choice;
    if (!PlayerTemplate(character, solo, choice)) return;
    const uint32_t original = solo ? 0x425814 : 0x42581C;
    const char* expected = solo ? "Chaz" : "CoOpChaz";
    const size_t bytes = std::strlen(expected) + 1;
    if (!Span(base, original, bytes) || std::memcmp(base + original, expected, bytes)) return;
    // Authored scripts recognize player classes; visual clones retain their real template names.
    ctx.esi = original;
}

bool DarkwatchCharacterModelAlias(X86Context& ctx, uint8_t* base) {
    const unsigned state = mission.load();
    const unsigned players = state & 3;
    uint32_t count, mode, vtable, actor, category;
    std::string character, alias, requested;
    // The native constructor leaves category 0 through render initialization;
    // player spawn assigns category 9 only after that initialization returns.
    if (!players || players > 2 || !owner ||
        (Selection(state, 0) != 0 && (players != 2 || Selection(state, 1) != 0)) ||
        ctx.ebp < 12 || ctx.esp != ctx.ebp - 12 ||
        !Read(base, uint64_t(owner) + 0x4C, count) || count != local_count ||
        !Read(base, uint64_t(owner) + 0xEC, mode) || mode != mission_mode ||
        !Read(base, ctx.edi, vtable) || vtable != 0x41E25C ||
        !Read(base, uint64_t(ctx.edi) + 0x0C, actor) || !actor ||
        !Read(base, uint64_t(actor) + 0x98, category) || (category != 0 && category != 9) ||
        !OwnedString(base, actor + 0x50, character) ||
        (character != "Chaz" && character != "JerichoCoop") ||
        !Span(base, ctx.esi, 0x108) || !OwnedString(base, ctx.esi + 0x104, requested) || requested != "AsCivilian" ||
        !OwnedString(base, ctx.ebp - 4, alias) || alias != "AsJericho") return false;
    // Keep the selected regular body when a chapter requests the civilian costume.
    // Native lookup, loading and owned-string cleanup still run; explicit Civilian clones are unchanged.
    return true;
}

bool DarkwatchCharacterCostume(X86Context& ctx, uint8_t* base) {
    const unsigned state = mission.load();
    uint32_t actor, item, count, mode, group, scope, scratch;
    std::string name, character;
    bool solo; unsigned choice;
    if (!(state & 12) && !Roster(state)) return false;
    if (!owner || ctx.ebp < 0x34 || ctx.esp != ctx.ebp - 0x34 ||
        !Span(base, ctx.esp, 0x44) ||
        !Read(base, uint64_t(owner) + 0x4C, count) || count != local_count ||
        !Read(base, uint64_t(owner) + 0xEC, mode) || mode != mission_mode ||
        !Read(base, uint64_t(ctx.ebp) + 8, actor) || !actor || !Span(base, actor, 0x70) ||
        !Read(base, uint64_t(ctx.ebp) + 12, item) || item != ctx.edi ||
        !OwnedString(base, item, name) || (name != "cloak" && name != "Civ_cloak") ||
        !OwnedString(base, actor + 0x50, character) ||
        !PlayerTemplate(character, solo, choice) || !choice ||
        !Read(base, uint64_t(actor) + 0x68, group) ||
        !Read(base, uint64_t(actor) + 0x6C, scope) ||
        !Read(base, uint64_t(ctx.ebp) - 4, scratch) || scratch) return false;
    uint32_t arguments[7];
    std::memcpy(arguments, base + ctx.esp, sizeof(arguments));
    const uint32_t expected[]{item, group, scope, 1, 1, ctx.ebp - 4, 1};
    if (!std::equal(std::begin(arguments), std::end(arguments), std::begin(expected))) return false;
    // Riding spawn points grant Jericho's coat separately; other bodies do not wear it.
    // The native null-result path cleans this call and continues the remaining inventory.
    ctx.eax = 0;
    return true;
}

unsigned DarkwatchCharacterUnavailablePlayers() { return unavailable.load(); }

bool DarkwatchCharacterIsCassidyPlayer(const uint8_t* base, uint32_t actor) {
    const unsigned state = mission.load();
    uint32_t count, mode, category;
    std::string character;
    // Check the spawned actor, not the menu choice: a failed selection remains Jericho.
    return (state & 12) && owner && actor &&
        Read(base, uint64_t(owner) + 0x4C, count) && count == local_count &&
        Read(base, uint64_t(owner) + 0xEC, mode) && mode == mission_mode &&
        Read(base, uint64_t(actor) + 0x98, category) && category == 9 &&
        OwnedString(base, actor + 0x50, character) &&
        CassidyActor(character);
}

bool DarkwatchCharacterIsTalaPlayer(const uint8_t* base, uint32_t actor) {
    const unsigned state = mission.load();
    uint32_t count, mode, category;
    std::string character;
    const auto tala = [](unsigned choice) { return darkwatch::settings::TalaCharacter(darkwatch::settings::Character(choice)); };
    bool solo; unsigned choice;
    return (tala(Selection(state, 0)) || ((state & 3) == 2 && tala(Selection(state, 1)))) &&
        owner && actor && Read(base, uint64_t(owner) + 0x4C, count) && count == local_count &&
        Read(base, uint64_t(owner) + 0xEC, mode) && mode == mission_mode &&
        Read(base, uint64_t(actor) + 0x98, category) && category == 9 &&
        OwnedString(base, actor + 0x50, character) && PlayerTemplate(character, solo, choice) && tala(choice);
}
