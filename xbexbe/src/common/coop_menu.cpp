// Experimental co-op campaign entry. The front-end main menu's Multiplayer item links to
// multiplayer_profile_select_ps2 on PS2 and to multiplayer_main on Xbox (packfile "main"
// page, Ps2Only/XboxOnly). The menu page (EA9B7) opens the original Versus/Co-op
// "GEN_SelectMode" dialog only for the PS2 link (EAA79). With coop_campaign set, that
// comparison and the dialog's Versus choice (EA94B) use the Xbox link instead, so
// Multiplayer offers the retained co-op campaign and Versus reaches the original menu.
#include <atomic>
#include <cstdint>
#include <cstring>
#include "common/coop.h"
#include "core/log.h"
#include "cpu/x86_context.h"
#include "kernel/memory.h"

namespace {
constexpr uint32_t kPs2Link = 0x004298F8;   // "multiplayer_profile_select_ps2"
constexpr uint32_t kXboxLink = 0x0042A674;  // "multiplayer_main"

// Both call sites pass the page name as the only stack argument to the name hash (138FA).
void UseXboxLink(X86Context& ctx, uint8_t* base) {
    if (!darkwatch::coop::Snapshot().campaign || !mem::IsCommitted(ctx.esp & ~(mem::kPage - 1u))) return;
    uint32_t name;
    std::memcpy(&name, base + ctx.esp, 4);
    if (name != kPs2Link || std::memcmp(base + kXboxLink, "multiplayer_main", 17)) return;
    std::memcpy(base + ctx.esp, &kXboxLink, 4);
}
} // namespace

void DarkwatchCoopModeDialog(X86Context& ctx, uint8_t* base) {UseXboxLink(ctx, base);}
void DarkwatchCoopVersusPage(X86Context& ctx, uint8_t* base) {UseXboxLink(ctx, base);}

// EFA10 warns for each port in the session's required-controller mask (byte read into cl
// at EFA81 and EFAAC) that is not connected. The PS2 co-op path leaves ports 3 and 4 in it
// on Xbox, and building their warning faults; with the co-op campaign on, only the two
// players' ports are checked, also after a network guest leaves (port 2 then idles).
void DarkwatchCoopRequiredPorts(X86Context& ctx, uint8_t*) {
    static std::atomic<uint32_t> last{0x100};
    const uint32_t mask = ctx.ecx & 0xFF;
    if (last.exchange(mask) != mask) LOGR("coop: required controller ports %02X", mask);
    if (!darkwatch::coop::Snapshot().campaign) return;
    if ((mask & 0x03) == 0x03 && (mask & ~0x03u)) ctx.ecx = (ctx.ecx & ~0xFFu) | 0x03;
}
