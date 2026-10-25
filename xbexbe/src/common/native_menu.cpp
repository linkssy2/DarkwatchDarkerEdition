#include "native_menu.h"
#include "coop_characters.h"
#include "graphics_route.h"
#include "common/graphics.h"
#include "common/menu_cursor.h"
#include "app/app.h"
#include "core/input.h"
#include "core/diag.h"
#include "core/log.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <imgui.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <mutex>
#include <vector>

namespace {
constexpr uint32_t kMenu = 0x43C8B8, kBar = 0x43C87C;
constexpr uint32_t kInteger = 0x43C97C, kBool = 0x43C9B0;
constexpr uint32_t kPressStart = 0x42AE08;
constexpr uint32_t kCarousel = 0x429B80;
constexpr uint32_t kLoading = 0x42A4C0;
constexpr uint32_t kKeyboard = 0x42B068;
constexpr unsigned kLimit = 512;
using Clock = std::chrono::steady_clock;
struct Rect {float x, y, w, h;};
struct Hit {uint32_t menu, widget, index, kind; Rect rect;};
struct Scope {uint32_t manager = 0; std::vector<uint32_t> roots;};
struct Snapshot {
    Scope scope;
    std::vector<Hit> hits;
    std::vector<uint32_t> bars;
    Clock::time_point time;
};
struct Collection {uint32_t manager = 0; std::vector<Hit> rows;};
thread_local Collection collecting;
std::mutex snapshot_lock;
Snapshot published;
struct PointerState {
    input::PointerSnapshot previous;
    Scope scope;
    int64_t wheel = 0;
    uint32_t title = 0;
};
thread_local PointerState pointer;

bool Span(const uint8_t* base, uint64_t at, uint32_t size) {
    const uint64_t end = at + size;
    if (!base || !at || !size || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = at & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base + at, sizeof(value)); return true;
}
template<class T> bool Field(const uint8_t* base, uint32_t object, uint32_t offset, T& value) {
    return object && Read(base, uint64_t(object) + offset, value);
}
bool Visible(const uint8_t* base, uint32_t object) {
    uint8_t visible;
    return Field(base, object, 0x2F, visible) && visible;
}
bool Focused(const uint8_t* base, uint32_t object) {
    uint8_t focus;
    return Field(base, object, 0x2E, focus) && focus;
}
bool LocalInput(const uint8_t* base, uint32_t object) {
    uint8_t players;
    return Field(base, object, 0x24, players) && (players & 1);
}
bool Finite(Rect r) {
    return std::isfinite(r.x) && std::isfinite(r.y) && std::isfinite(r.w) && std::isfinite(r.h) &&
           r.w > 0 && r.h > 0 && r.w <= 8 && r.h <= 8 && std::abs(r.x) <= 16 && std::abs(r.y) <= 16;
}
bool SameScope(const Scope& a, const Scope& b) {return a.manager == b.manager && a.roots == b.roots;}
// Original 1E96CB walks active roots backwards, stopping at a visible modal (kind3).
Scope InputScope(const uint8_t* base, uint32_t manager) {
    Scope result;
    uint16_t count; uint32_t list;
    if (!Field(base, manager, 8, count) || count > kLimit ||
        !Field(base, manager, 12, list) || (count && !Span(base, list, count * 4))) return result;
    result.manager = manager;
    for (unsigned i = count; i; --i) {
        uint32_t root, kind;
        if (!Read(base, uint64_t(list) + (i - 1) * 4, root)) return {};
        if (Focused(base, root) && Visible(base, root)) result.roots.push_back(root);
        if (!Field(base, root, 0x3C, kind)) return {};
        if (Visible(base, root) && kind == 3) break;
    }
    return result;
}
bool Children(const uint8_t* base, uint32_t object, std::vector<uint32_t>& children) {
    uint16_t count; uint32_t list;
    if (!Field(base, object, 8, count) || count > kLimit || !Field(base, object, 12, list) ||
        (count && !Span(base, list, count * 4))) return false;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t child, parent;
        if (!Read(base, uint64_t(list) + i * 4, child) || !Field(base, child, 4, parent) || parent != object) return false;
        children.push_back(child);
    }
    return true;
}
bool Descendant(const uint8_t* base, uint32_t widget, uint32_t root) {
    for (unsigned depth = 0; depth < 32; ++depth) {
        if (widget == root) return true;
        uint32_t parent;
        if (!Visible(base, widget) || !Field(base, widget, 4, parent) || parent == widget) return false;
        std::vector<uint32_t> children;
        if (!Children(base, parent, children) || std::find(children.begin(), children.end(), widget) == children.end()) return false;
        widget = parent;
    }
    return false;
}
bool Row(const uint8_t* base, const Hit& hit, bool require_visible = true) {
    uint32_t type, list, row, selected, parent, row_type; uint16_t count; uint8_t enabled;
    return Field(base, hit.menu, 0, type) && type == kMenu && Focused(base, hit.menu) && Visible(base, hit.menu) && LocalInput(base, hit.menu) &&
        Field(base, hit.menu, 0x58, count) && count <= kLimit && hit.index < count &&
        Field(base, hit.menu, 0x68, selected) && selected < count &&
        Field(base, hit.menu, 0x5C, list) && Read(base, uint64_t(list) + hit.index * 4, row) && row == hit.widget &&
        Field(base, hit.widget, 4, parent) && parent == hit.menu && Field(base, hit.widget, 0, row_type) && row_type == hit.kind &&
        Field(base, hit.widget, 0x54, enabled) && enabled && (!require_visible || Visible(base, hit.widget));
}
// A single-value horizontal Menu inside a vertical Menu is a native choice
// control (co-op preset/character). Its inner value can be the foremost hit.
bool ChoiceRow(const uint8_t* base, const Hit& hit, Hit& owner) {
    const auto choice = hit.kind == kMenu ? hit.widget : hit.menu;
    uint32_t orientation, shown, parent, type, list, selected;
    uint16_t count, choices;
    uint8_t navigation;
    if (!Field(base, choice, 0, type) || type != kMenu ||
        !Field(base, choice, 0x70, orientation) || orientation != 1 ||
        !Field(base, choice, 0x64, shown) || shown != 1 ||
        !Field(base, choice, 0xA1, navigation) || !navigation ||
        !Field(base, choice, 0x58, choices) || choices < 2 || choices > kLimit ||
        !Field(base, choice, 0x68, selected) || selected >= choices ||
        !Field(base, choice, 4, parent) || !Field(base, parent, 0, type) || type != kMenu ||
        !Field(base, parent, 0x70, orientation) || orientation ||
        !Field(base, parent, 0x58, count) || count > kLimit ||
        !Field(base, parent, 0x5C, list) || !Span(base, list, count * 4)) return false;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t child;
        if (!Read(base, uint64_t(list) + i * 4, child)) return false;
        if (child == choice) {
            owner = {parent, choice, i, kMenu, hit.rect};
            return Row(base, owner);
        }
    }
    return false;
}
// Traverse only the actual active/visible tree, rejecting cycles or oversized structures.
bool Collect(const uint8_t* base, const Scope& scope, const std::vector<Hit>& rows, Snapshot& out) {
    std::vector<uint32_t> visited;
    for (uint32_t root : scope.roots) {
        struct Node {uint32_t object; bool visited;};
        std::vector<Node> pending{{root, false}};
        while (!pending.empty()) {
            const auto node = pending.back(); pending.pop_back();
            const uint32_t object = node.object;
            if (!node.visited) {
                if (visited.size() >= kLimit || std::find(visited.begin(), visited.end(), object) != visited.end()) return false;
                visited.push_back(object);
                if (!Visible(base, object) || !Focused(base, object)) continue;
                pending.push_back({object, true});
                std::vector<uint32_t> children;
                if (!Children(base, object, children)) return false;
                for (uint32_t child : children) pending.push_back({child, false});
                continue;
            }
            uint32_t type;
            if (!Field(base, object, 0, type)) return false;
            if (type == kPressStart && LocalInput(base, object)) {
                uint32_t movie, widget; uint8_t exiting; Rect rect;
                // EDC83 consumes action9 only before an attract movie and before leaving this screen.
                if (Field(base, object, 0x58, movie) && !movie && Field(base, object, 0x7C, exiting) && !exiting &&
                    Field(base, object, 0x78, widget) && Descendant(base, widget, object) &&
                    Field(base, widget, 0x34, rect) && Finite(rect))
                    out.hits.push_back({object, widget, 9, kPressStart, rect});
            }
            if (type == kLoading && LocalInput(base, object)) {
                uint32_t state, widget; uint8_t automatic; Rect rect;
                // EA6CD reveals this prompt only after load completion; EA5EC then consumes action4.
                if (Field(base, object, 0x70, state) && state == 1 && Field(base, object, 0x78, automatic) && !automatic &&
                    Field(base, object, 0x5C, widget) && Descendant(base, widget, object) &&
                    Field(base, widget, 0x34, rect) && Finite(rect))
                    out.hits.push_back({object, widget, 4, kLoading, rect});
            }
            if (type == kKeyboard && LocalInput(base, object)) {
                uint32_t columns, rows, grid, column, row;
                if (Field(base, object, 0x5C, columns) && (columns == 10 || columns == 12) &&
                    Field(base, object, 0x60, rows) && rows == 5 && Field(base, object, 0x64, grid) &&
                    Span(base, grid, columns * 4) && Field(base, object, 0x74, column) && column < columns &&
                    Field(base, object, 0x78, row) && row < rows) {
                    std::vector<uint32_t> seen;
                    for (unsigned x = 0; x < columns; ++x) {
                        uint32_t cells;
                        if (!Read(base, uint64_t(grid) + x * 4, cells) || !Span(base, cells, rows * 4)) return false;
                        for (unsigned y = 0; y < rows; ++y) {
                            uint32_t widget; Rect rect;
                            if (!Read(base, uint64_t(cells) + y * 4, widget)) return false;
                            if (!widget || std::find(seen.begin(), seen.end(), widget) != seen.end()) continue;
                            seen.push_back(widget); // Space, Backspace and Done share multiple grid cells.
                            if (Descendant(base, widget, object) && Field(base, widget, 0x34, rect) && Finite(rect))
                                out.hits.push_back({object, widget, (x << 16) | y, kKeyboard, rect});
                        }
                    }
                }
            }
            if (type == kCarousel && LocalInput(base, object)) {
                uint32_t menu, menu_type, orientation; uint16_t count; uint8_t navigation;
                if (Field(base, object, 0x58, menu) && Descendant(base, menu, object) &&
                    Field(base, menu, 0, menu_type) && menu_type == kMenu && Focused(base, menu) && LocalInput(base, menu) &&
                    Field(base, menu, 0x70, orientation) && orientation && Field(base, menu, 0xA1, navigation) && navigation &&
                    Field(base, menu, 0x58, count) && count > 1 && count <= kLimit) {
                    for (unsigned side = 0; side < 2; ++side) {
                        uint32_t widget; uint8_t enabled; Rect rect;
                        // E68E8 sets each authored arrow glow's +5C according to selection bounds.
                        if (Field(base, object, 0x74 + side * 4, widget) && Descendant(base, widget, object) &&
                            Field(base, widget, 0x5C, enabled) && Field(base, widget, 0x34, rect) && Finite(rect))
                            out.hits.insert(std::find_if(out.hits.begin(), out.hits.end(), [menu](const Hit& hit) {return hit.menu == menu;}),
                                            {object, widget, enabled ? side + 2 : 16, kCarousel, rect});
                    }
                }
            }
            if (type == kMenu && Focused(base, object)) {
                for (const auto& row : rows) if (row.menu == object && Row(base, row)) out.hits.push_back(row);
            }
            if (type == kBar && Focused(base, object) && LocalInput(base, object)) {
                out.bars.push_back(object);
                for (unsigned action = 0; action < 16; ++action) {
                    const uint64_t slot = uint64_t(object) + 0x48 + action * 0x1C;
                    uint8_t enabled, callback; uint32_t widget, parent; Rect rect;
                    if (Read(base, slot, enabled) && enabled && Read(base, slot + 0x14, callback) && callback &&
                        Read(base, slot + 0x18, widget) && Field(base, widget, 4, parent) && parent == object &&
                        Visible(base, widget) && Field(base, widget, 0x34, rect) && Finite(rect))
                        out.hits.push_back({object, widget, action, kBar, rect});
                }
            }
        }
    }
    return true;
}
bool Fresh(const Snapshot& value) {return Clock::now() - value.time < std::chrono::milliseconds(500);}
Snapshot Get() {std::lock_guard lock(snapshot_lock); return published;}
bool Contains(Rect r, float x, float y) {return x >= r.x - r.w && x <= r.x + r.w && y >= r.y - r.h && y <= r.y + r.h;}
bool Point(const input::PointerSnapshot& p, float& x, float& y) {
    if (!p.width || !p.height) return false;
    const float aspect = app::Widescreen() ? 16.f / 9.f : 4.f / 3.f;
    const float width = std::min(float(p.width), float(p.height) * aspect), height = width / aspect;
    const float left = (p.width - width) * .5f, top = (p.height - height) * .5f;
    if (p.x < left || p.x >= left + width || p.y < top || p.y >= top + height) return false;
    x = (p.x - left) * 2.f / width - 1.f; y = 1.f - (p.y - top) * 2.f / height;
    return true;
}
} // namespace

void DarkwatchInvalidateMenuSnapshot() {
    collecting = {};
    input::SetTitleScreen(false);
    std::lock_guard lock(snapshot_lock);
    published = {};
}

bool DarkwatchHideReplacedMenuContent(X86Context& ctx, uint8_t* base) {
    darkwatch::EnsureNativeOptionsEntries(base, ctx.esi);
    return DarkwatchHideCoopSetupContent(ctx, base) ||
           darkwatch::HideFrontendSettingsContent(base, ctx.esi);
}

void DarkwatchMenuRenderBegin(X86Context& ctx, uint8_t* base) {
    // A page can open after input polling. Publish its host replacement before
    // the original manager submits that page's first frame.
    DarkwatchCoopSetupRefresh(base);
    collecting = {}; collecting.manager = ctx.ecx;
}

void DarkwatchMenuRow(X86Context& ctx, uint8_t* base) {
    if (!collecting.manager || collecting.rows.size() >= kLimit) return;
    Hit hit{ctx.ebx, ctx.esi, 0, 0, {}}; Rect local, parent;
    if (!Read(base, uint64_t(ctx.ebp) + 0x6C, hit.index) || !Read(base, uint64_t(ctx.ebp) + 0x38, local) ||
        !Field(base, hit.menu, 0x34, parent) || !Field(base, hit.widget, 0, hit.kind) || !Row(base, hit, false)) return;
    // Capture before original renderer splits name/value regions. Compose exactly as 1E8CA7.
    hit.rect = {local.x * parent.w + parent.x, local.y * parent.h + parent.y, local.w * parent.w, local.h * parent.h};
    if (Finite(hit.rect)) collecting.rows.push_back(hit);
}

void DarkwatchMenuRenderEnd(X86Context& ctx, uint8_t* base) {
    if (collecting.manager != ctx.esi) return;
    Snapshot value; value.scope = InputScope(base, ctx.esi); value.time = Clock::now();
    if (!value.scope.manager || !Collect(base, value.scope, collecting.rows, value)) value = {};
    input::SetTitleScreen(std::any_of(value.hits.begin(), value.hits.end(), [](const Hit& hit) {return hit.kind == kPressStart;}));
    collecting = {};
    std::lock_guard lock(snapshot_lock);
    if (diag::Perf()) {
        static Scope logged;
        static unsigned lines = 0;
        if (!SameScope(logged, value.scope)) {
            if (lines < 32) {
                uint32_t roots[3]{}, types[3]{};
                for (unsigned i = 0; i < std::min<size_t>(3, value.scope.roots.size()); ++i) {
                    roots[i] = value.scope.roots[i]; Field(base, roots[i], 0, types[i]);
                }
                LOGR("menu pointer scope manager=%08X roots=%zu hits=%zu bars=%zu root0=%08X/%08X root1=%08X/%08X root2=%08X/%08X",
                     value.scope.manager, value.scope.roots.size(), value.hits.size(), value.bars.size(),
                     roots[0], types[0], roots[1], types[1], roots[2], types[2]);
                ++lines;
            }
            logged = value.scope;
        }
    }
    published = std::move(value);
}

void DarkwatchMenuInput(X86Context& ctx, uint8_t* base) {
    const auto now = input::GetPointerSnapshot();
    if (!now.active) {
        // Consume inactive edges without copying a snapshot or traversing guest menus.
        pointer.previous = now; pointer.scope = {}; pointer.wheel = 0; pointer.title = 0;
        return;
    }
    const auto state = Get();
    const auto scope = InputScope(base, ctx.esi);
    const auto previous = pointer.previous;
    const bool reset = !now.active || !previous.active || now.epoch != previous.epoch ||
                       !SameScope(scope, pointer.scope) || DarkwatchGraphicsVisible();
    pointer.previous = now; pointer.scope = scope;
    if (!Fresh(state) || !SameScope(scope, state.scope) || state.hits.empty()) {pointer.wheel = 0; pointer.title = 0; return;}
    // Rebuild the membership check at the original input boundary; never trust a previous frame's pointer alone.
    Snapshot checked;
    if (!Collect(base, scope, state.hits, checked) || checked.hits.empty()) {pointer.wheel = 0; pointer.title = 0; return;}
    const auto title = std::find_if(checked.hits.begin(), checked.hits.end(), [](const Hit& hit) {return hit.kind == kPressStart;});
    const uint32_t previous_title = pointer.title;
    pointer.title = title != checked.hits.end() ? title->widget : 0;
    if (reset) {pointer.wheel = 0; return;}
    if (pointer.title) {
        // Entering/revealing the title establishes a baseline; loading/attract/focus edges cannot start it.
        pointer.wheel = 0;
        if (pointer.title != previous_title) return;
        if (now.key_presses != previous.key_presses) {ctx.eax |= 0x200; return;}
        auto click = now;
        click.x = now.left_x; click.y = now.left_y; click.width = now.left_width; click.height = now.left_height;
        float x, y;
        if (now.left_presses != previous.left_presses && click.width == now.width && click.height == now.height && Point(click, x, y))
            ctx.eax |= 0x200;
        return;
    }
    if (now.right_presses != previous.right_presses || now.back_presses != previous.back_presses) {
        ctx.eax |= 0x20; pointer.wheel = 0; return; // Original semantic Back, independent of PC B binding.
    }
    const bool click = now.left_presses != previous.left_presses;
    auto location = now;
    if (click) {
        location.x = now.left_x; location.y = now.left_y;
        location.width = now.left_width; location.height = now.left_height;
        // The SDK invalidates the epoch on resize; reject a mismatched snapshot defensively too.
        if (location.width != now.width || location.height != now.height) return;
    }
    float x, y;
    if (!Point(location, x, y)) {pointer.wheel = 0; return;}
    const bool moved = now.x != previous.x || now.y != previous.y;
    const Hit* selected = nullptr;
    for (const auto& hit : checked.hits) if (Contains(hit.rect, x, y)) {selected = &hit; break;}
    const uint64_t wheel_bits = uint64_t(now.wheel) - uint64_t(previous.wheel);
    int64_t wheel_delta; std::memcpy(&wheel_delta, &wheel_bits, sizeof(wheel_delta));
    pointer.wheel = std::clamp(pointer.wheel + std::clamp(wheel_delta, int64_t(-960), int64_t(960)), int64_t(-960), int64_t(960));
    if (!selected) {pointer.wheel = 0; return;}
    if (selected->kind == kKeyboard) {
        pointer.wheel = 0;
        if ((moved || click) && Span(base, uint64_t(selected->menu) + 0x74, 8)) {
            // EE1A0's original navigation state is exactly these two indices; EE8E3 owns text/actions.
            const uint32_t indices[]{selected->index >> 16, selected->index & 0xFFFF};
            std::memcpy(base + selected->menu + 0x74, indices, sizeof(indices));
            if (click) ctx.eax |= 0x10;
        }
        return;
    }
    if (selected->kind == kBar || selected->kind == kPressStart || selected->kind == kCarousel || selected->kind == kLoading) {
        pointer.wheel = 0;
        if (click && selected->index < 16) ctx.eax |= 1u << selected->index;
        return;
    }
    Hit choice;
    const bool horizontal_choice = ChoiceRow(base, *selected, choice);
    if (horizontal_choice) selected = &choice;
    const bool adjustable = horizontal_choice || selected->kind == kInteger || selected->kind == kBool;
    uint32_t current;
    if (!Field(base, selected->menu, 0x68, current)) return;
    if ((moved || click || (wheel_delta && adjustable)) && current != selected->index) {
        if (ctx.esp < 32 || !Span(base, uint64_t(ctx.esp) - 32, 32) || base != kernel::g_base) return;
        // Preserve the original focus and selection callback contracts, including the caller's x87 state.
        X86Context call = ctx; call.ecx = selected->menu;
        kernel::CallGuest(call, 0x1EF329, {selected->index});
        if (!SameScope(scope, InputScope(base, ctx.esi)) || !Row(base, *selected)) return;
    }
    if (click) {
        unsigned action = (horizontal_choice || selected->kind == kInteger) ? (x < selected->rect.x ? 2 : 3) : selected->kind == kBool ? 3 : 4;
        ctx.eax |= 1u << action;
    } else if (pointer.wheel >= 120 || pointer.wheel <= -120) {
        const bool up = pointer.wheel > 0;
        pointer.wheel += up ? -120 : 120;
        const unsigned action = adjustable ? (up ? 3 : 2) : (up ? 0 : 1);
        ctx.eax |= 1u << action;
    }
}

void DarkwatchRefreshMenuBars(uint8_t* base, uint64_t revision) {
    thread_local uint64_t previous = 0;
    thread_local std::vector<uint32_t> previous_bars;
    Snapshot state;
    {
        std::lock_guard lock(snapshot_lock);
        if (previous == revision && previous_bars == published.bars) return;
        state = published;
    }
    if (!Fresh(state) || !SameScope(state.scope, InputScope(base, state.scope.manager))) return;
    Snapshot checked;
    if (!Collect(base, state.scope, state.hits, checked)) return;
    for (uint32_t bar : checked.bars) if (Span(base, uint64_t(bar) + 0x20C, 1)) base[bar + 0x20C] = 1;
    previous = revision;
    previous_bars = checked.bars;
}

void DarkwatchMenuUi(double) {
    const auto state = Get();
    const bool host = DarkwatchGraphicsVisible();
    const bool menu = Fresh(state) && !state.hits.empty();
    if (!menu || host) input::SetTitleScreen(false);
    app::SetMenuPointer(host || menu);
    if ((host || menu) && !ImGui::GetIO().AppFocusLost) darkwatch::DrawMenuCursor();
}
