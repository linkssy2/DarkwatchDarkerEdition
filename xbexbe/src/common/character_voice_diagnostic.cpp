#include "character_voice_diagnostic.h"

#ifdef XBE_RELEASE
// Public builds cannot enable private observers through inherited environment variables.
void DarkwatchCharacterVoiceQuery(X86Context&, uint8_t*) {}
void DarkwatchCharacterVoiceQueryResult(X86Context&, uint8_t*) {}
void DarkwatchCharacterVoiceSpeaker(X86Context&, uint8_t*) {}
void DarkwatchCharacterVoiceLocal(X86Context&, uint8_t*) {}
void DarkwatchCharacterVoiceDispatch(X86Context&, uint8_t*) {}
void DarkwatchCharacterVoiceCreated(X86Context&, uint8_t*) {}
void DarkwatchCharacterVoiceMelee(X86Context&, uint8_t*) {}
#else

#include "character_runtime.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>

namespace {
constexpr unsigned kLimit = 32;
using Text = std::array<char, 64>;
std::mutex trace_mutex;
unsigned query_count = 0, dispatch_count = 0;
unsigned result_count = 0, speaker_count = 0, melee_count = 0;
unsigned local_count = 0, created_count = 0;

const char* Output() {
    // Only the private session runner supplies this explicit output path.
    static const char* path = std::getenv("DARKWATCH_CHARACTER_VOICE_TRACE");
    return path && *path ? path : nullptr;
}
bool Span(const uint8_t* base, uint64_t address, uint32_t bytes) {
    if (!base || !address || !bytes || address + bytes > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~uint64_t(mem::kPage - 1); page < address + bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t address, T& value) {
    if (!Span(base, address, sizeof(value))) return false;
    std::memcpy(&value, base + address, sizeof(value)); return true;
}
bool Name(const uint8_t* base, uint32_t ref, Text& text) {
    if (!ref) return false;
    for (unsigned i = 0; i < text.size(); ++i) {
        char c;
        if (!Read(base, uint64_t(ref) + 2 + i, c)) return false;
        if (!c) return true;
        if (i + 1 == text.size()) return false;
        if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
        // Diagnostic identifiers are ASCII; sanitize malformed JSON characters.
        text[i] = c < 32 || c > 126 || c == '"' || c == '\\' ? '?' : c;
    }
    return false;
}
bool Slot(const uint8_t* base, uint64_t slot, Text& text) {
    uint32_t ref;
    return Read(base, slot, ref) && Name(base, ref, text);
}
bool Player(const uint8_t* base, uint32_t actor, Text& name) {
    return actor && Slot(base, uint64_t(actor) + 0x50, name) &&
        (!std::strcmp(name.data(), "CASSIDYSOLO") || !std::strcmp(name.data(), "CASSIDYPLAYERTWO") ||
         !std::strcmp(name.data(), "CHAZ") || !std::strcmp(name.data(), "COOPCHAZ") ||
         !std::strcmp(name.data(), "JERICHOCOOP"));
}
uint32_t Speaker(const uint8_t* base, uint32_t actor) {
    uint16_t count; uint32_t rows, found = 0;
    if (!Read(base, uint64_t(actor) + 0x60, count) || count > 128 ||
        !Read(base, uint64_t(actor) + 0x64, rows) || (count && !Span(base, rows, 8u * count))) return 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t component, vtable, owner;
        if (!Read(base, uint64_t(rows) + 8u * i + 4, component) || !Read(base, component, vtable)) return 0;
        if (vtable != 0x43B114) continue;
        if (found || !Read(base, uint64_t(component) + 12, owner) || owner != actor) return 0;
        found = component;
    }
    return found;
}
bool Relevant(const Text& text) {
    return std::strstr(text.data(), "DAMAGE") || std::strstr(text.data(), "DMG") ||
           std::strstr(text.data(), "MELEE") || std::strstr(text.data(), "ATTK") ||
           std::strstr(text.data(), "HIT") || !std::strcmp(text.data(), "DEATH");
}
bool SoundCaller(uint32_t caller) {
    return caller == 0x208519 || caller == 0x20859C || caller == 0x208633 ||
           caller == 0x2086D7 || caller == 0x20877B || caller == 0x208A23;
}
void Record(const uint8_t* base, const char* phase, unsigned& count, uint32_t actor, uint32_t speaker,
            uint32_t caller, const Text& name, const Text& event, const Text& bank, const Text& cue,
            uint32_t handle = 0, int result = -1, const char* reason = "", uint32_t weapon_component = 0) {
    std::lock_guard<std::mutex> lock(trace_mutex);
    if (count == kLimit) return;
    const uint64_t state = uint64_t(speaker) + 0x48;
    uint16_t map_count = 0, voice_count = 0; uint32_t map = 0, voices = 0;
    uint8_t flags = 0, voice_index = 255; Text alias{}, mapped_bank{}, mapped_cue{};
    uint8_t disabled = 255, map_only = 255, query_mask = 255;
    uint32_t category = 0, weapon = 0, sound_object = 0, sound_reference = 0, voice_object = 0, ambient_object = 0;
    uint16_t effect_slots = 0;
    Text weapon_name{};
    Read(base, uint64_t(actor) + 0x5E, disabled); Read(base, uint64_t(actor) + 0x98, category);
    if (speaker) Read(base, uint64_t(speaker) + 0x25, map_only);
    Read(base, state + 0x28, effect_slots); Read(base, state + 0x30, voice_object); Read(base, state + 0x48, ambient_object);
    if (handle) { Read(base, handle, sound_object); Read(base, uint64_t(handle) + 4, sound_reference); }
    if (weapon_component && Read(base, uint64_t(weapon_component) + 12, weapon))
        Slot(base, uint64_t(weapon) + 0x50, weapon_name);
    // Match the original actor dispatcher's type-mask test for query message 0x42.
    uint32_t registry, types, offset, components; uint16_t component_count;
    if (Read(base, 0x4B784C, registry) && Read(base, uint64_t(registry) + 4, types) &&
        Read(base, uint64_t(types) + 0x42 * 8 + 4, offset) && offset < 4096 &&
        Read(base, uint64_t(actor) + 0x60, component_count) && component_count <= 128 &&
        Read(base, uint64_t(actor) + 0x64, components)) {
        for (unsigned i = 0; i < component_count; ++i) {
            uint32_t current, descriptor;
            if (Read(base, uint64_t(components) + 8u*i + 4, current) && current == speaker &&
                Read(base, uint64_t(components) + 8u*i, descriptor)) {
                Read(base, uint64_t(descriptor) + offset, query_mask); break;
            }
        }
    }
    Read(base, state + 0x71, flags); Read(base, state + 0x70, voice_index);
    if (Read(base, state + 0x68, voice_count) && voice_count <= 32 && voice_index < voice_count &&
        Read(base, state + 0x6C, voices)) Slot(base, uint64_t(voices) + 4u * voice_index, alias);
    bool match = false;
    if (Read(base, state + 0x60, map_count) && map_count <= 256 &&
        Read(base, state + 0x64, map) && (!map_count || Span(base, map, 16u * map_count))) {
        for (unsigned i = 0; *event.data() && i < map_count; ++i) {
            Text key{}; const uint64_t row = uint64_t(map) + 16u * i;
            if (Slot(base, row, key) && !std::strcmp(key.data(), event.data())) {
                match = Slot(base, row + 4, mapped_bank) && Slot(base, row + 8, mapped_cue); break;
            }
        }
    }
    const std::filesystem::path path(Output());
    if (!path.is_absolute()) return;
    FILE* file = _wfopen(path.c_str(), L"ab");
    if (!file) return;
    ++count;
    std::fprintf(file, "{\"phase\":\"%s\",\"number\":%u,\"actor\":%u,\"template\":\"%s\","
        "\"speaker\":%u,\"caller\":%u,\"event\":\"%s\",\"bank\":\"%s\",\"cue\":\"%s\","
        "\"map_count\":%u,\"map_match\":%s,\"mapped_bank\":\"%s\",\"mapped_cue\":\"%s\","
        "\"voice_alias\":\"%s\",\"flags\":%u,\"sound_handle_slot\":%u,"
        "\"actor_disabled\":%u,\"map_only\":%u,\"query_mask\":%u,\"result\":%d,\"reason\":\"%s\","
        "\"weapon_component\":%u,\"weapon\":%u,\"weapon_template\":\"%s\",\"category\":%u,\"sound_object\":%u,\"sound_reference\":%u,"
        "\"effect_slots\":%u,\"voice_object\":%u,\"ambient_object\":%u}\n",
        phase, count, actor, name.data(), speaker, caller, event.data(), bank.data(), cue.data(),
        map_count, match ? "true" : "false", mapped_bank.data(), mapped_cue.data(), alias.data(), flags, handle,
        disabled, map_only, query_mask, result, reason, weapon_component, weapon, weapon_name.data(), category, sound_object, sound_reference,
        effect_slots, voice_object, ambient_object);
    std::fclose(file);
}
} // namespace

void DarkwatchCharacterVoiceQuery(X86Context& ctx, uint8_t* base) {
    if (!Output()) return;
    uint32_t actor, event_slot, caller; Text name{}, event{}, empty{};
    if (!Read(base, ctx.esp, caller) || !Read(base, uint64_t(ctx.esp) + 4, actor) ||
        !Read(base, uint64_t(ctx.esp) + 8, event_slot) || !Player(base, actor, name) ||
        !Slot(base, event_slot, event) || !Relevant(event)) return;
    const uint32_t speaker = Speaker(base, actor);
    Record(base, "query", query_count, actor, speaker, caller, name, event, empty, empty);
}

void DarkwatchCharacterVoiceDispatch(X86Context& ctx, uint8_t* base) {
    if (!Output() || ctx.esi < 0x48) return;
    const uint32_t speaker = ctx.esi - 0x48;
    uint32_t vtable, actor, caller; Text name{}, bank{}, cue{}, empty{};
    // At 207F60 entry, the local-map and explicit-bank callers retain the speaker
    // state in ESI. Include local playback; query->1D9017 is network replication.
    if (!Read(base, ctx.esp, caller) || !SoundCaller(caller) || !Read(base, speaker, vtable) || vtable != 0x43B114 ||
        !Read(base, uint64_t(speaker) + 12, actor) || !Player(base, actor, name) ||
        Speaker(base, actor) != speaker || !Slot(base, uint64_t(ctx.esp) + 8, bank) ||
        !Slot(base, uint64_t(ctx.esp) + 12, cue) || !Relevant(cue)) return;
    const char* lane = ctx.ecx == ctx.esi + 0x30 ? "voice" : ctx.ecx == ctx.esi + 0x48 ? "ambient" : "effects";
    Record(base, "dispatch", dispatch_count, actor, speaker, caller, name, empty, bank, cue, ctx.ecx, -1, lane);
}

void DarkwatchCharacterVoiceCreated(X86Context& ctx, uint8_t* base) {
    if (!Output() || ctx.ebp < 0x54) return;
    uint32_t state, caller, actor, vtable, output; int32_t code; Text name{}, bank{}, cue{}, empty{};
    if (!Read(base, uint64_t(ctx.ebp) + 4, caller) || !SoundCaller(caller) ||
        !Read(base, ctx.ebp - 0x54, state) || state < 0x48 ||
        !Read(base, state - 0x48, vtable) || vtable != 0x43B114 ||
        !Read(base, state - 0x48 + 12, actor) || !Player(base, actor, name) || Speaker(base, actor) != state - 0x48 ||
        !Slot(base, uint64_t(ctx.ebp) + 12, bank) || !Slot(base, uint64_t(ctx.ebp) + 16, cue) || !Relevant(cue) ||
        !Read(base, uint64_t(ctx.ebp) + 8, output) || !Read(base, uint64_t(output) + 16, code)) return;
    const char* lane = ctx.esi == state + 0x30 ? "voice" : ctx.esi == state + 0x48 ? "ambient" : "effects";
    Record(base, "created", created_count, actor, state - 0x48, caller, name, empty, bank, cue, output, code, lane);
}

void DarkwatchCharacterVoiceQueryResult(X86Context& ctx, uint8_t* base) {
    if (!Output() || ctx.ebp < 0x18) return;
    uint32_t actor, event_slot, caller; uint8_t found; Text name{}, event{}, bank{}, cue{};
    if (!Read(base, uint64_t(ctx.ebp) + 4, caller) || !Read(base, uint64_t(ctx.ebp) + 8, actor) ||
        !Read(base, uint64_t(ctx.ebp) + 12, event_slot) || !Player(base, actor, name) ||
        !Slot(base, event_slot, event) || !Relevant(event) || !Read(base, ctx.ebp - 0x10, found)) return;
    Slot(base, ctx.ebp - 8, bank); Slot(base, ctx.ebp - 4, cue);
    Record(base, "query-result", result_count, actor, Speaker(base, actor), caller, name, event, bank, cue, 0, found);
}

void DarkwatchCharacterVoiceSpeaker(X86Context& ctx, uint8_t* base) {
    if (!Output()) return;
    const uint32_t speaker = ctx.ecx;
    uint32_t vtable, actor, message, caller; Text name{}, bank{}, cue{}, empty{};
    if (!Read(base, speaker, vtable) || vtable != 0x43B114 ||
        !Read(base, uint64_t(speaker) + 12, actor) || !Player(base, actor, name) ||
        Speaker(base, actor) != speaker || !Read(base, ctx.esp, caller) ||
        !Read(base, uint64_t(ctx.esp) + 4, message) ||
        !Slot(base, uint64_t(message) + 8, bank) || !Slot(base, uint64_t(message) + 12, cue) || !Relevant(cue)) return;
    Record(base, "speaker-entry", speaker_count, actor, speaker, caller, name, empty, bank, cue);
}

void DarkwatchCharacterVoiceLocal(X86Context& ctx, uint8_t* base) {
    if (!Output()) return;
    const uint32_t speaker = ctx.ecx;
    uint32_t vtable, actor, message, caller, event_slot; Text name{}, event{}, empty{};
    if (!Read(base, speaker, vtable) || vtable != 0x43B114 ||
        !Read(base, uint64_t(speaker) + 12, actor) || !Player(base, actor, name) ||
        Speaker(base, actor) != speaker || !Read(base, ctx.esp, caller) ||
        !Read(base, uint64_t(ctx.esp) + 4, message) ||
        !Read(base, uint64_t(message) + 8, event_slot) || !Slot(base, event_slot, event) || !Relevant(event)) return;
    Record(base, "local-entry", local_count, actor, speaker, caller, name, event, empty, empty);
}

void DarkwatchCharacterVoiceMelee(X86Context& ctx, uint8_t* base) {
    if (!Output()) return;
    uint32_t actor = 0, event = 0, caller = 0, component = 0, weapon = 0, argument = 0; Text name{}, empty{};
    const char* reason = "dispatch";
    if (base != kernel::g_base || ctx.ebp < 0x14 ||
        !Read(base, uint64_t(ctx.ebp) - 0x14, component) ||
        !Read(base, uint64_t(component) + 12, weapon) || weapon != ctx.esi ||
        !Read(base, ctx.esp, argument) || argument != weapon ||
        !Read(base, uint64_t(ctx.ebp) - 8, event) || !Read(base, uint64_t(event) + 4, event) || event != 0x17C ||
        !Read(base, uint64_t(component) + 0x58, actor)) reason = "invalid-frame";
    else if (!DarkwatchCharacterIsCassidyPlayer(base, actor)) reason = "identity";
    else if (ctx.esp < 0x2000 || !Span(base, ctx.esp - 0x2000, 0x2000)) reason = "stack";
    else if (!DarkwatchCharacterAudioReady(base, &reason)) { /* Exact readiness failure is retained. */ }
    else reason = "dispatch";
    if (!Player(base, actor, name)) return;
    Read(base, uint64_t(ctx.ebp) + 4, caller);
    Record(base, "melee-entry", melee_count, actor, Speaker(base, actor), caller, name, empty, empty, empty,
           0, event, reason ? reason : "audio unavailable", component);
}

#endif
