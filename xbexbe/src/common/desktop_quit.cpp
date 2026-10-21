#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstring>
#include "desktop_quit.h"
#include "native_menu.h"
#include "graphics.h"
#include "coop.h"
#include "app/app.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"

namespace darkwatch {
namespace {
constexpr const char* kLabels[]{"~CHARACTERS", "~QUIT TO DESKTOP"};
constexpr const char* kLinks[]{"~darkwatch_characters", "~darkwatch_desktop_quit"};
constexpr float kHeight = .21f * (7.f / 5.f);
constexpr float kCenter = -.68f + kHeight;
// The longer exit caption needs more room at Main's original 1.4 font scale.
// Extend rightward, retaining the authored left edge (.57 - .29).
constexpr float kHalfWidth = .34f;
constexpr float kCenterX = .28f + kHalfWidth;
struct AddedRow {
    const uint8_t* base = nullptr;
    uint32_t root = 0, menu = 0, character = 0, row = 0;
    bool posted = false;
} added;

bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const auto end = address + size;
    if (!base || !address || !size || end > (uint64_t(1) << 32)) return false;
    for (auto page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t address, T& value) {
    if (!Span(base, address, sizeof(T))) return false;
    std::memcpy(&value, base + address, sizeof(T));
    return true;
}
bool Field(const uint8_t* base, uint32_t object, uint32_t offset, uint32_t& value) {
    return object && Read(base, uint64_t(object) + offset, value);
}
bool RefIs(const uint8_t* base, uint32_t ref, const char* text) {
    uint32_t data;
    const auto size = uint32_t(std::strlen(text) + 1);
    return Read(base, ref, data) && data && Span(base, uint64_t(data) + 2, size) &&
        !std::memcmp(base + uint64_t(data) + 2, text, size);
}
uint32_t ActiveMain(const uint8_t* base) {
    uint32_t frontend, depth, main, type, manager, list;
    uint16_t count;
    if (!Read(base, 0x4AD664, frontend) || !Field(base, frontend, 8, depth) || !depth || depth > 20 ||
        !Field(base, frontend, 8 + depth * 4, main) || !Field(base, main, 0, type) || type != 0x42A608 ||
        !RefIs(base, main + 0x30, "main") ||
        !Read(base, 0x4AD314, manager) || !manager || !Read(base, uint64_t(manager) + 8, count) ||
        count > 512 || !Field(base, manager, 12, list) || !Span(base, list, count * 4)) return 0;
    // Match the original UI input order: even an unfocused visible modal blocks Main.
    for (unsigned i = count; i; --i) {
        uint32_t root, kind;
        uint8_t visible, focused, local;
        if (!Read(base, uint64_t(list) + (i - 1) * 4, root) || !Field(base, root, 0x3C, kind) ||
            !Read(base, uint64_t(root) + 0x2F, visible) || !Read(base, uint64_t(root) + 0x2E, focused)) return 0;
        if (root == main)
            return visible && focused && Read(base, uint64_t(root) + 0x24, local) && (local & 1) ? main : 0;
        if (visible && kind == 3) return 0;
    }
    return 0;
}
bool MainMenu(const uint8_t* base, uint32_t root, uint32_t& menu, uint32_t& rows, uint16_t& count,
              bool require_visible = true) {
    uint32_t type, parent, selected, shown;
    uint8_t visible;
    if (!Field(base, root, 0x58, menu) || !Span(base, menu, 0xA4) ||
        !Field(base, menu, 0, type) || type != 0x43C8B8 ||
        !Field(base, menu, 4, parent) || parent != root ||
        !Read(base, uint64_t(menu) + 0x2F, visible) || (require_visible && !visible) ||
        !Read(base, uint64_t(menu) + 0x58, count) || (count != 5 && count != 7) ||
        !Field(base, menu, 0x5C, rows) || !Span(base, rows, count * 4) ||
        !Field(base, menu, 0x64, shown) || shown ||
        !Field(base, menu, 0x68, selected) || selected >= count) return false;
    constexpr const char* names[]{"GEN_SinglePlayer", "GEN_Multiplayer", "GEN_Options",
        "PROFILE_ProfileScreenTitle", "GEN_Extras", kLabels[0], kLabels[1]};
    constexpr const char* links[]{"chapter_select", "multiplayer_main", "options", "profile_select", "extras", kLinks[0], kLinks[1]};
    for (unsigned i = 0; i < count; ++i) {
        uint32_t row;
        if (!Read(base, uint64_t(rows) + i * 4, row) || !Span(base, row, 0x68) ||
            !Field(base, row, 0, type) || type != 0x43C8F8 ||
            !Field(base, row, 4, parent) || parent != menu ||
            !RefIs(base, row + 0x30, names[i]) || !RefIs(base, row + 0x50, links[i])) return false;
    }
    return true;
}
bool IsAdded(const uint8_t* base, uint32_t root, uint32_t menu, uint32_t rows, uint16_t count) {
    uint32_t character, row;
    return count == 7 && added.base == base && added.root == root && added.menu == menu &&
        Read(base, uint64_t(rows) + 5 * 4, character) && character == added.character &&
        Read(base, uint64_t(rows) + 6 * 4, row) && row == added.row;
}
} // namespace

uint32_t CharacterMenuOwner(const uint8_t* base) { return ActiveMain(base); }

bool ConfirmDesktopQuit(uint8_t* base, uint32_t owner) {
    uint32_t menu, rows, selected;
    uint16_t count;
    if (!owner || base != kernel::g_base || ActiveMain(base) != owner ||
        !MainMenu(base, owner, menu, rows, count) || !IsAdded(base, owner, menu, rows, count) ||
        !Field(base, menu, 0x68, selected) || selected != 6 ||
        !base[added.row + 0x54] || !base[added.row + 0x2F]) return false;
    // Revalidate the owner on the guest thread before using the existing shutdown path.
    if (!added.posted) {
        const auto window = static_cast<HWND>(app::Window());
        added.posted = window && PostMessageW(window, WM_CLOSE, 0, 0);
    }
    return added.posted;
}

namespace {
bool EnsureMainEntries(uint8_t* base, uint32_t root, const X86Context& context, bool require_visible) {
    uint32_t menu, rows, root_type;
    uint16_t count;
    if (!root || base != kernel::g_base || !Field(base, root, 0, root_type) || root_type != 0x42A608 ||
        !RefIs(base, root + 0x30, "main") ||
        !MainMenu(base, root, menu, rows, count, require_visible)) return false;
    ResetCoopInput();
    if (IsAdded(base, root, menu, rows, count)) return true;
    uint32_t peer, text, type, scale_mode;
    float rect[4], scale;
    if (count != 5 || !Read(base, uint64_t(menu) + 0x10, rect) ||
        rect[0] != .57f || rect[1] != -.48f || rect[2] != .29f || rect[3] != .21f ||
        !Read(base, rows, peer) || !Field(base, peer, 0x58, text) ||
        !Field(base, text, 0, type) || type != 0x43C36C ||
        !Field(base, text, 0x64, scale_mode) || scale_mode != 2 ||
        !Read(base, uint64_t(text) + 0x6C, scale) || scale != 1.4f ||
        context.esp < 0x2000 || !Span(base, uint64_t(context.esp) - 0x2000, 0x2000)) return false;

    // Keep reference ownership, child destruction, focus and glow in the original MenuItem APIs.
    const auto scratch = context.esp - 0x80;
    X86Context call = context;
    call.esp = scratch - 0x10;
    uint32_t created[2]{};
    for (unsigned n = 0; n < 2; ++n) {
        std::memset(base + scratch, 0, 0x80);
        std::memcpy(base + scratch + 0x20, kLabels[n], std::strlen(kLabels[n]) + 1);
        std::memcpy(base + scratch + 0x40, kLinks[n], std::strlen(kLinks[n]) + 1);
        for (unsigned i = 0; i < 2; ++i) {
            call.ecx = scratch + i * 4;
            kernel::CallGuest(call, 0x138FA, {scratch + 0x20 + i * 0x20});
        }
        const auto allocation = kernel::CallGuest(call, 0x24C546, {0x68});
        if (allocation) {
            call.ecx = allocation;
            created[n] = kernel::CallGuest(call, 0x1EFB52, {scratch, scratch + 4, scratch + 8});
        }
        for (unsigned i = 0; i < 2; ++i) {
            call.ecx = scratch + i * 4;
            kernel::CallGuest(call, 0x11C1A, {});
        }
        if (!created[n] || !Field(base, created[n], 0x58, text) || !Span(base, text, 0x80) ||
            !Field(base, text, 0, type) || type != 0x43C36C) {
            for (const auto row : created) if (row) {
                call.ecx = row; kernel::CallGuest(call, 0xECB9D, {1});
            }
            return false;
        }
        // Match Main's scaled-font mode as well as its authored font scale.
        std::memcpy(base + text + 0x64, &scale_mode, sizeof(scale_mode));
        std::memcpy(base + text + 0x6C, &scale, sizeof(scale));
    }
    for (const auto row : created) {
        call.ecx = menu;
        kernel::CallGuest(call, 0x1EFA66, {row});
    }
    // Keep the original row/font size and the footer's lower edge.
    std::memcpy(base + menu + 0x10, &kCenterX, sizeof(kCenterX));
    std::memcpy(base + menu + 0x14, &kCenter, sizeof(kCenter));
    std::memcpy(base + menu + 0x18, &kHalfWidth, sizeof(kHalfWidth));
    std::memcpy(base + menu + 0x1C, &kHeight, sizeof(kHeight));
    added = {base, root, menu, created[0], created[1], false};
    DarkwatchInvalidateMenuSnapshot();
    return true;
}
} // namespace

bool EnsureDesktopQuitEntry(uint8_t* base) {
    auto* thread = kernel::Current();
    return thread && thread->ctx && EnsureMainEntries(base, ActiveMain(base), *thread->ctx, true);
}
} // namespace darkwatch

void DarkwatchMainMenuInitialize(X86Context& ctx, uint8_t* base) {
    // Main's authored children and footer exist here, before its first layout.
    // Construction precedes registration/focus, unlike input and confirmation.
    auto* thread = kernel::Current();
    if (thread && thread->ctx) darkwatch::EnsureMainEntries(base, ctx.esi, ctx, false);
}

bool DarkwatchDesktopQuit(X86Context& ctx, uint8_t* base) {
    using namespace darkwatch;
    const auto root = ActiveMain(base);
    uint32_t menu, rows, selected;
    uint16_t count;
    if (!root || base != kernel::g_base || ctx.edi != root ||
        !MainMenu(base, root, menu, rows, count) || !IsAdded(base, root, menu, rows, count) ||
        ctx.eax != menu || !Field(base, menu, 0x68, selected) ||
        (selected != 5 && selected != 6)) return false;
    const auto row = selected == 5 ? added.character : added.row;
    if (ctx.ecx != row || !base[row + 0x54] || !base[row + 0x2F]) return false;
    if (selected == 5) {
        DarkwatchCharactersOpen(root);
        return true;
    }
    DarkwatchDesktopQuitOpen(root);
    return true; // Never pass our private link to the original page factory.
}
