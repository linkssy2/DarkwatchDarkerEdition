#include "coop_characters.h"
#include "character_selection.h"
#include "character_runtime.h"
#include "campaign_replay.h"
#include "native_menu.h"
#include "app/app.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>
#include <string>

X86_EXTERN_FUNC(__imp__sub_000E77AF);

namespace {
constexpr uint32_t kMenu = 0x43C8B8, kItem = 0x43C8F8;
std::string NativeName(unsigned id) { return "~" + std::string(darkwatch::settings::CharacterName(darkwatch::settings::Character(id))); }
struct Added {
    const uint8_t* base = nullptr;
    uint32_t page = 0;
    std::array<uint32_t, 2> controls{}, choices{};
} added;

bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    if (!base || !at || !size || at + size > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage) - 1); p < at + size; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& out) {
    if (!Span(base, at, sizeof(out))) return false;
    std::memcpy(&out, base + at, sizeof(out)); return true;
}
template<class T> void Write(uint8_t* base, uint32_t at, const T& value) {
    std::memcpy(base + at, &value, sizeof(value));
}
bool RefIs(const uint8_t* base, uint32_t at, const char* text) {
    uint32_t ref;
    const auto size = uint32_t(std::strlen(text) + 1);
    return Read(base, at, ref) && ref && Span(base, uint64_t(ref) + 2, size) &&
        !std::memcmp(base + uint64_t(ref) + 2, text, size);
}
bool Type(const uint8_t* base, uint32_t object, uint32_t type, unsigned size) {
    uint32_t actual;
    return Span(base, object, size) && Read(base, object, actual) && actual == type;
}
bool Owned(const uint8_t* base, uint32_t child, uint32_t root) {
    for (unsigned n = 0; n < 8 && child; ++n) {
        if (child == root) return true;
        uint32_t parent;
        if (!Read(base, uint64_t(child) + 4, parent) || parent == child) return false;
        child = parent;
    }
    return false;
}
bool Rows(const uint8_t* base, uint32_t menu, unsigned expected, uint32_t& rows) {
    uint16_t count;
    return Type(base, menu, kMenu, 0xA8) && Read(base, uint64_t(menu) + 0x58, count) &&
        count == expected && Read(base, uint64_t(menu) + 0x5C, rows) && Span(base, rows, count * 4);
}
bool Page(const uint8_t* base, uint32_t page) {
    return base == kernel::g_base && Type(base, page, 0x429D38, 0x9C) && RefIs(base, page + 0x30, "coop_profile");
}
struct ControlPair {
    uint32_t app = 0, database = 0;
    std::array<uint32_t, 2> profiles{};
    bool operator==(const ControlPair&) const = default;
};
ControlPair SavedControls(const uint8_t* base) {
    ControlPair pair;
    auto& app = pair.app; auto& database = pair.database; auto& profiles = pair.profiles;
    uint32_t count, state, dirty;
    if (base != kernel::g_base || !Read(base, 0x4ACFBC, app) ||
        !Type(base, app, 0x424B3C, 0x6C) || !Read(base, app + 0x68, database) ||
        !Read(base, database, count) || count != 10 ||
        !Type(base, database + 8, 0x4252C4, 0x14) ||
        !Read(base, database + 0xC, dirty) || dirty > 1 ||
        !Read(base, database + 0x10, state) || state != 2 ||
        !Read(base, database + 0x14, profiles) || !profiles[0] || profiles[0] == profiles[1]) return {};
    for (auto profile : profiles) {
        float sensitivity;
        if (!Span(base, profile, 0x6C) || base[profile + 4] > 1 || base[profile + 5] > 1 ||
            !Read(base, profile + 8, sensitivity) || !std::isfinite(sensitivity)) return {};
        bool preset = false;
        for (const auto name : {"Default", "Chieftain", "Lefty", "Hopalong", "Hoss"})
            preset |= RefIs(base, profile + 0xC, name);
        if (!preset) return {};
    }
    return pair;
}
bool ActivePage(const uint8_t* base, uint32_t page) {
    uint32_t frontend, depth, top, manager, list;
    uint16_t count;
    if (!Page(base, page) || !Read(base, 0x4AD664, frontend) || !frontend ||
        !Read(base, uint64_t(frontend) + 8, depth) || !depth || depth > 20 ||
        !Read(base, uint64_t(frontend) + 8 + depth * 4, top) || top != page ||
        !Read(base, 0x4AD314, manager) || !manager || !Read(base, uint64_t(manager) + 8, count) || count > 512 ||
        !Read(base, uint64_t(manager) + 12, list) || !Span(base, list, count * 4)) return false;
    for (unsigned i = count; i; --i) {
        uint32_t root, kind;
        uint8_t visible, focused;
        if (!Read(base, uint64_t(list) + (i - 1) * 4, root) || !root ||
            !Read(base, uint64_t(root) + 0x3C, kind) || !Read(base, uint64_t(root) + 0x2F, visible) ||
            !Read(base, uint64_t(root) + 0x2E, focused)) return false;
        if (root == page) return visible && focused;
        if (visible && kind == 3) return false;
    }
    return false;
}
bool Controls(const uint8_t* base, uint32_t page, unsigned player, unsigned count, uint32_t& menu, uint32_t& rows) {
    const auto record = page + 0x58 + player * 0x20;
    if (!Read(base, record + 8, menu) || !Rows(base, menu, count, rows) || !Owned(base, menu, page) ||
        !RefIs(base, menu + 0x30, "controls_options") || base[menu + 0x24] != (1u << player)) return false;
    // Keep the authored four controls and their profile pointers in their original order.
    constexpr uint32_t fields[]{0xC, 0x14, 0x10, 0x18};
    constexpr uint32_t types[]{0x43C9B0, 0x43C97C, 0x43C9B0, kMenu};
    for (unsigned i = 0; i < 4; ++i) {
        uint32_t widget, original, parent;
        if (!Read(base, uint64_t(rows) + i * 4, widget) || !Read(base, record + fields[i], original) || widget != original ||
            !Type(base, widget, types[i], 0x58) || !Read(base, uint64_t(widget) + 4, parent) || parent != menu) return false;
    }
    return true;
}
bool ChoiceState(const uint8_t* base, uint32_t page, unsigned player, unsigned& selected, bool& available) {
    uint32_t menu, rows, choice, items, parent;
    if (!Controls(base, page, player, 5, menu, rows) || menu != added.controls[player] ||
        !Read(base, rows + 16, choice) || choice != added.choices[player] || !Rows(base, choice, darkwatch::settings::kCharacterCount, items) ||
        base[choice + 0x24] != (1u << player) ||
        !Read(base, uint64_t(choice) + 4, parent) || parent != menu || !RefIs(base, choice + 0x30, "~Character") ||
        !Read(base, uint64_t(choice) + 0x68, selected) || selected >= darkwatch::settings::kCharacterCount) return false;
    available = true;
    for (unsigned i = 0; i < darkwatch::settings::kCharacterCount; ++i) {
        uint32_t row;
        if (!Read(base, uint64_t(items) + i * 4, row) || !Type(base, row, kItem, 0x68) ||
            !RefIs(base, row + 0x30, NativeName(i).c_str()) || base[row + 0x54] > 1 ||
            !Read(base, uint64_t(row) + 4, parent) || parent != choice ||
            ((!i || i == selected) && !base[row + 0x54])) return false;
        if (i && !base[row + 0x54]) available = false;
    }
    return true;
}
darkwatch::CoopSetupState ReadState(const uint8_t* base) {
    darkwatch::CoopSetupState result;
    const auto page = added.page;
    if (added.base != base || !Page(base, page)) return result;
    result.character_available = true;
    for (unsigned i = 0; i < 2; ++i) {
        unsigned selected; bool available;
        const auto record = page + 0x58 + i * 0x20;
        uint8_t ready, connected;
        uint32_t background, message;
        if (!ChoiceState(base, page, i, selected, available) ||
            !Read(base, record, background) || !Span(base, background, 0x48) || !Owned(base, background, page) ||
            !RefIs(base, background + 0x30, "background") ||
            !Read(base, record + 4, message) || !Span(base, message, 0x50) || !Owned(base, message, page) ||
            !RefIs(base, message + 0x30, "message") ||
            !Read(base, record + 0x1C, ready) || ready > 1 ||
            !Read(base, record + 0x1D, connected) || connected > 1) return {};
        result.characters[i] = darkwatch::settings::Character(selected);
        result.ready[i] = ready != 0;
        result.connected[i] = connected != 0;
        result.character_available &= available;
    }
    result.owner = page;
    return result;
}
bool ActionContext(uint8_t* base, X86Context& call) {
    const auto* thread = kernel::Current();
    if (!thread || !thread->ctx || base != kernel::g_base || thread->ctx->esp < 0x2000 ||
        !Span(base, uint64_t(thread->ctx->esp) - 0x2000, 0x2000)) return false;
    call = *thread->ctx;
    return true;
}
void Destroy(X86Context& call, uint32_t menu) {
    if (menu) {call.ecx = menu; kernel::CallGuest(call, 0x1EF765, {1});}
}
void AssignLabel(X86Context& call, uint8_t* base, uint32_t scratch, uint32_t ref, const char* text) {
    Write(base, scratch, uint32_t(0));
    std::strcpy(reinterpret_cast<char*>(base + scratch + 0x20), text);
    call.ecx = scratch; kernel::CallGuest(call, 0x138FA, {scratch + 0x20});
    call.ecx = ref; kernel::CallGuest(call, 0x129DF, {scratch});
    call.ecx = scratch; kernel::CallGuest(call, 0x11C1A, {});
}
uint32_t Create(X86Context& call, uint8_t* base, uint32_t scratch, unsigned selected, bool available) {
    const auto menu = kernel::CallGuest(call, 0x24C546, {0xA8});
    if (!menu) return 0;
    call.ecx = menu; kernel::CallGuest(call, 0x1EF6A2, {});
    AssignLabel(call, base, scratch, menu + 0x30, "~Character");
    Write(base, menu + 0x70, uint32_t(1)); // Native horizontal choice, exactly like controller preset.
    Write(base, menu + 0x64, uint32_t(1));
    for (unsigned i = 0; i < darkwatch::settings::kCharacterCount; ++i) {
        std::memset(base + scratch, 0, 0x80);
        std::strcpy(reinterpret_cast<char*>(base + scratch + 0x20), NativeName(i).c_str());
        call.ecx = scratch; kernel::CallGuest(call, 0x138FA, {scratch + 0x20});
        const auto allocation = kernel::CallGuest(call, 0x24C546, {0x68});
        uint32_t row = 0;
        if (allocation) {
            call.ecx = allocation; row = kernel::CallGuest(call, 0x1EFB52, {scratch, scratch + 4, scratch + 8});
        }
        call.ecx = scratch; kernel::CallGuest(call, 0x11C1A, {});
        if (!row) {Destroy(call, menu); return 0;}
        uint32_t text;
        Read(base, uint64_t(row) + 0x58, text);
        // The long English/Spanish names must stay on one line in the native value column.
        Write(base, text + 0x64, uint32_t(2));
        Write(base, text + 0x6C, .75f);
        base[row + 0x54] = uint8_t(i == 0 || available);
        call.ecx = menu; kernel::CallGuest(call, 0x1EFA66, {row});
    }
    call.ecx = menu; kernel::CallGuest(call, 0x1EF329, {available ? selected : 0});
    return menu;
}
} // namespace

namespace darkwatch {
CoopSetupState QueryCoopSetup(const uint8_t* base) {
    if (added.base != base || !ActivePage(base, added.page)) return {};
    return ReadState(base);
}

bool SetCoopSetupCharacter(uint8_t* base, uint32_t owner, unsigned player, settings::Character character) {
    const auto state = QueryCoopSetup(base);
    X86Context call;
    if (!owner || state.owner != owner || player > 1 || !settings::ValidCharacter(character) ||
        state.ready[player] || !state.connected[player] ||
        (character != settings::Character::Jericho && !state.character_available) ||
        !ActionContext(base, call)) return false;
    call.ecx = added.choices[player];
    kernel::CallGuest(call, 0x1EF329, {unsigned(character)});
    DarkwatchInvalidateMenuSnapshot();
    return true;
}

bool SetCoopSetupReady(uint8_t* base, uint32_t owner, unsigned player, bool ready) {
    const auto state = QueryCoopSetup(base);
    X86Context call;
    if (!owner || state.owner != owner || player > 1 ||
        (ready && (!state.connected[player] || (state.ready[1-player] && !state.connected[1-player]))) ||
        !ActionContext(base, call)) return false;
    if (state.ready[player] == ready) return true;
    // E758C owns both-Ready profile creation, replay cleanup and chapter select.
    // E7368 updates the original ready presentation when cancelling one slot.
    call.ecx = owner;
    kernel::CallGuest(call, ready ? 0xE758C : 0xE7368, {player});
    DarkwatchInvalidateMenuSnapshot();
    return true;
}

bool BackCoopSetup(uint8_t* base, uint32_t owner, unsigned player) {
    const auto state = QueryCoopSetup(base);
    X86Context call;
    if (!owner || state.owner != owner || player > 1 || !ActionContext(base, call)) return false;
    call.ecx = owner;
    kernel::CallGuest(call, 0xE7380, {player});
    DarkwatchInvalidateMenuSnapshot();
    return true;
}
} // namespace darkwatch

bool DarkwatchHideCoopSetupContent(X86Context& ctx, uint8_t* base) {
    // 1EC67F: the original root renderer also draws unfocused fading pages.
    // Leave its timer/visibility tail intact so native transitions can finish.
    return ctx.esi == added.page && ReadState(base).owner != 0;
}

X86_FUNC(sub_000E77AF) {
    const auto entry = ctx;
    // Original setup imports the current solo player's controls for its port.
    // Capture an existing pair before CABDE creates fresh co-op defaults.
    const auto pair = Page(base, entry.ecx) ? SavedControls(base) : ControlPair{};
    __imp__sub_000E77AF(ctx, base);
    if (!pair.profiles[0] || SavedControls(base) != pair || ReadState(base).owner != entry.ecx ||
        entry.esp < 0x2000 || !Span(base, uint64_t(entry.esp) - 0x2000, 0x2000)) return;
    auto call = entry;
    call.esp -= 0x100;
    for (unsigned player = 0; player < 2; ++player) {
        call.ecx = entry.ecx;
        // Ready reads these native widgets back into each loaded profile.
        kernel::CallGuest(call, 0xE74ED, {player, pair.profiles[player]});
    }
}

void DarkwatchCoopCharactersInitialize(X86Context& ctx, uint8_t* base) {
    const auto page = ctx.edi; // E7981, after both native player panels are initialized.
    if (!Page(base, page)) return;
    std::array<uint32_t, 2> menus{}, lists{}, choices{};
    for (unsigned i = 0; i < 2; ++i) {
        float rect[4]; uint32_t shown;
        if (!Controls(base, page, i, 4, menus[i], lists[i]) ||
            !Read(base, uint64_t(menus[i]) + 0x10, rect) ||
            rect[0] != (i ? -.39f : .39f) || rect[1] != .19f || rect[2] != .61f || rect[3] != .48f ||
            !Read(base, uint64_t(menus[i]) + 0x64, shown) || shown != 4) return;
    }
    if (ctx.esp < 0x2000 || !Span(base, uint64_t(ctx.esp) - 0x2000, 0x2000)) return;
    const auto draft = darkwatch::settings::characters();
    const bool available = DarkwatchCharacterContentReady();
    const auto scratch = ctx.esp - 0x80;
    auto call = ctx; call.esp = scratch - 0x10;
    for (unsigned i = 0; i < 2; ++i) {
        choices[i] = Create(call, base, scratch, unsigned(draft[i]), available);
        if (!choices[i]) {for (auto choice : choices) Destroy(call, choice); return;}
    }
    for (unsigned i = 0; i < 2; ++i) {
        call.ecx = menus[i]; kernel::CallGuest(call, 0x1EFA66, {choices[i]});
        // Five rows retain the original row height and top edge; stop above Ready.
        Write(base, menus[i] + 0x14, .07f);
        Write(base, menus[i] + 0x1C, .60f);
        Write(base, menus[i] + 0x64, uint32_t(5));
    }
    added = {base, page, menus, choices};
    DarkwatchInvalidateMenuSnapshot();
}

bool DarkwatchCoopCharactersCommit(X86Context& ctx, uint8_t* base) {
    // Both Ready will replace the live campaign profiles below this hook.
    if (!DarkwatchCampaignReplayFinish(ctx, base)) return true;
    const auto page = ctx.esi; // E75BD, reached only after both native Ready flags are set.
    const auto state = darkwatch::QueryCoopSetup(base);
    if (state.owner != page || !state.ready[0] || !state.ready[1]) return false;
    const auto draft = state.characters;
    // The page survives Back from chapter selection. A later Ready can commit
    // another choice, while repeated unchanged callbacks need no disk write.
    if (draft != darkwatch::settings::characters() && darkwatch::settings::set_characters(draft)) {
        app::Save(); // As with the other settings, save failure keeps the session's choice.
    }
    return false;
}
