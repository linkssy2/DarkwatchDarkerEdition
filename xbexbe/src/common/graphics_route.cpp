#include "graphics_route.h"
#include "native_menu.h"
#include <cstring>
#include <algorithm>
#include <cmath>
#include "kernel/kernel.h"
#include "kernel/memory.h"

namespace darkwatch {
namespace {
constexpr uint32_t kFrontend = 0x004AD664;
constexpr uint32_t kUiManager = 0x004AD314;
constexpr uint32_t kOptionsVtable = 0x0042A3B0;
constexpr uint32_t kPauseVtable = 0x0042B318;
constexpr uint32_t kPauseMainVtable = 0x0042BF8C;
constexpr uint32_t kMainVtable = 0x0042BEF8;
constexpr uint32_t kVisualVtable = 0x0042C08C;
constexpr uint32_t kControlsVtable = 0x0042BE9C;
constexpr uint32_t kAudioVtable = 0x0042BE48;
constexpr uint32_t kControllerConfigVtable = 0x00429C10;

bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || !size || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
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
bool PauseLayoutActive(const uint8_t* base, uint32_t pause, uint32_t visible_layout) {
    uint32_t frontend, depth, layout, type, owner, outgoing;
    if (!Read(base, kFrontend, frontend) || !Field(base, frontend, 8, depth) || depth > 20) return false;
    // F54B0 pushes this kind-0 screen on the frontend stack and records its
    // Pause owner at +64. It does not hide the separately registered Pause.
    if (depth && Field(base, frontend, 8 + depth * 4, layout) &&
        Field(base, layout, 0, type) && type == kControllerConfigVtable &&
        Field(base, layout, 0x64, owner) && owner == pause) return true;
    // E4D03 pops before E4A48's outgoing screen finishes hiding. Only the
    // actual visible higher UI root may extend suppression across that fade.
    return visible_layout && Field(base, frontend, 0x5C, outgoing) && outgoing == visible_layout &&
        Field(base, visible_layout, 0x64, owner) && owner == pause;
}
uint32_t ActivePause(const uint8_t* base) {
    uint32_t manager, list, visible_layout = 0;
    uint16_t count;
    // D9F15 owns Pause at HUD+120 and registers it through C2B36/1E9BD8.
    // It is not pushed onto the frontend stack. Follow the actual 1E96CB
    // input order, including an unfocused visible modal blocking lower roots.
    if (!Read(base, kUiManager, manager) || !manager ||
        !Read(base, uint64_t(manager) + 8, count) || count > 512 ||
        !Field(base, manager, 12, list) || (count && !Span(base, list, count * 4))) return 0;
    for (unsigned i = count; i; --i) {
        uint32_t root, type, kind;
        uint8_t visible, focused, local;
        if (!Read(base, uint64_t(list) + (i - 1) * 4, root) ||
            !Field(base, root, 0, type) || !Field(base, root, 0x3C, kind) ||
            !Read(base, uint64_t(root) + 0x2F, visible) ||
            !Read(base, uint64_t(root) + 0x2E, focused)) return 0;
        if (visible && focused && type == kPauseVtable) {
            uint32_t hud, owned;
            // EFB7C records the reciprocal HUD owner. The HUD itself can be
            // hidden while paused, so its visibility is deliberately not a gate.
            // F03E7/1E8F3D propagate the owning controller mask to Pause.
            // CCE45 decodes this mask; local co-op uses ports zero and one.
            if (!Read(base, uint64_t(root) + 0x24, local) || (local != 1 && local != 2) ||
                !Field(base, root, 0xF4, hud) || !Field(base, hud, 0x120, owned) || owned != root) return 0;
            if (PauseLayoutActive(base, root, visible_layout)) return 0;
            return root;
        }
        if (visible && type == kControllerConfigVtable) visible_layout = root;
        if (visible && kind == 3) break;
    }
    return 0;
}
uint32_t PauseControlsKey(const uint8_t* base, uint32_t options) {
    uint16_t count;
    uint32_t pages, key = 0;
    // EFCD2 registers all three handlers through EBC1F. EBB03 compares the
    // registered widget's owned +30 key, then pushes that handler normally.
    if (!Read(base, uint64_t(options) + 0x58, count) || !count || count > 16 ||
        !Field(base, options, 0x5C, pages) || !Span(base, pages, uint32_t(count) * 4)) return 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t handler, type, owner, widget, value;
        if (!Read(base, uint64_t(pages) + i * 4, handler) || !Field(base, handler, 0, type) ||
            !Field(base, handler, 8, owner) || owner != options || !Field(base, handler, 4, widget) ||
            !Field(base, widget, 0x30, value) || !value) return 0;
        if (type == kControlsVtable) {
            if (key) return 0;
            key = widget + 0x30;
        }
    }
    return key;
}

bool RefIs(const uint8_t* base, uint32_t ref, const char* text) {
    uint32_t data;
    if (!Read(base, ref, data) || !data) return false;
    const auto size = uint32_t(std::strlen(text) + 1);
    return Span(base, uint64_t(data) + 2, size) && !std::memcmp(base + uint64_t(data) + 2, text, size);
}
struct PauseRows {
    const uint8_t* base = nullptr;
    uint32_t owner = 0, main = 0, menu = 0, rows[3]{}, removed[2]{};
    bool consumed = false;
};
PauseRows g_pause_rows[2];

bool PauseMenu(const uint8_t* base, uint32_t owner, uint32_t& main, uint32_t& menu,
               uint32_t& items, uint16_t& count) {
    uint32_t type, parent, selected;
    if (!Field(base, owner, 0xE8, main) || !Field(base, main, 0, type) || type != kPauseMainVtable ||
        !Field(base, main, 8, parent) || parent != owner || !Field(base, main, 4, menu) ||
        !Field(base, menu, 0, type) || type != 0x43C8B8 || !Span(base, menu, 0xA4) ||
        !Read(base, uint64_t(menu) + 0x58, count) || (count != 6 && count != 7) ||
        !Field(base, menu, 0x5C, items) || !Span(base, items, count * 4) ||
        !Field(base, menu, 0x68, selected) || selected >= count) return false;
    // Validate either the untouched authored list or our complete replacement.
    constexpr const char* names[]{"GEN_ResumeGame", "GEN_Lore", "GEN_Options",
        "XBL_XboxLiveOptions", "GEN_RestartMission", "GEN_QuitGame"};
    constexpr const char* added[]{"GEN_ResumeGame", "GEN_Lore", "~GRAPHICS",
        "~CONTROLS", "~AUDIO", "GEN_RestartMission", "GEN_QuitGame"};
    for (unsigned i = 0; i < count; ++i) {
        uint32_t item;
        if (!Read(base, uint64_t(items) + i * 4, item) || !Span(base, item, 0x68) ||
            !Field(base, item, 0, type) || type != 0x43C8F8 ||
            !Field(base, item, 4, parent) || parent != menu) return false;
        if (!RefIs(base, item + 0x30, count == 6 ? names[i] : added[i])) return false;
    }
    return true;
}
bool AddedRows(const PauseRows& rows, const uint8_t* base, uint32_t owner, uint32_t main, uint32_t menu,
               uint32_t items, uint16_t count) {
    if (rows.base != base || rows.owner != owner || rows.main != main ||
        rows.menu != menu || count != 7) return false;
    const auto key = PauseControlsKey(base, owner);
    uint32_t page_key;
    if (!key || !Read(base, key, page_key)) return false;
    constexpr const char* names[]{"~GRAPHICS", "~CONTROLS", "~AUDIO"};
    for (unsigned i = 0; i < 3; ++i) {
        uint32_t item, value;
        if (!Read(base, uint64_t(items) + (2 + i) * 4, item) || item != rows.rows[i] ||
            !RefIs(base, item + 0x30, names[i]) ||
            !Field(base, item, 0x50, value) || value != page_key) return false;
    }
    uint32_t type, parent;
    uint8_t visible, focused;
    for (unsigned i = 0; i < 2; ++i) {
        const auto removed = rows.removed[i];
        if (!Field(base, removed, 0, type) || type != 0x43C8F8 ||
            !Field(base, removed, 4, parent) || parent != menu ||
            !RefIs(base, removed + 0x30, i ? "XBL_XboxLiveOptions" : "GEN_Options") ||
            !Read(base, uint64_t(removed) + 0x2F, visible) || visible ||
            !Read(base, uint64_t(removed) + 0x2E, focused) || focused) return false;
    }
    return true;
}
bool PauseFrame(const uint8_t* base, uint32_t owner, uint32_t menu, uint32_t& frame) {
    uint32_t parent, type;
    return Field(base, owner, 0xF8, frame) && Field(base, menu, 4, parent) && parent == frame &&
        Field(base, frame, 4, parent) && parent == owner && Field(base, frame, 0, type) && type == 0x43C934 &&
        Span(base, frame, 0x44) && RefIs(base, frame + 0x30, "frame") &&
        Span(base, uint64_t(owner) + 0xFC, 16) && Span(base, uint64_t(frame) + 0x10, 16);
}
bool AudioWidgets(const uint8_t* base, uint32_t page, uint32_t (&widgets)[3]) {
    for (unsigned i = 0; i < 3; ++i) {
        int32_t minimum, maximum;
        if (!Field(base, page, 0xC + i * 4, widgets[i]) || !Span(base, widgets[i], 0x88) ||
            !Read(base, uint64_t(widgets[i]) + 0x5C, minimum) || minimum != 0 ||
            !Read(base, uint64_t(widgets[i]) + 0x60, maximum) || maximum != 10) return false;
    }
    return true;
}
}  // namespace

bool HideFrontendSettingsContent(const uint8_t* base, uint32_t options) {
    uint32_t type, depth, page, owner, menu, frame, pages, page_type;
    uint16_t count;
    if (base != kernel::g_base || !Span(base, options, 0xF4) ||
        !Field(base, options, 0, type) || type != kOptionsVtable ||
        !RefIs(base, options + 0x30, "options") ||
        !Field(base, options, 0x60, depth) || depth > 5 ||
        !Field(base, options, 0x60 + std::max(depth, 1u) * 4, page) ||
        !Field(base, page, 0, page_type) ||
        (page_type != kControlsVtable && page_type != kVisualVtable && page_type != kAudioVtable) ||
        !Field(base, page, 8, owner) || owner != options ||
        !Read(base, uint64_t(options) + 0x58, count) || !count || count > 16 ||
        !Field(base, options, 0x5C, pages) || !Span(base, pages, count * 4)) return false;
    // New-profile E9F8F replaces the sole page. EBB76 leaves that last slot
    // intact at depth zero while the original root completes its exit fade.
    bool registered = false;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t entry;
        if (!Read(base, uint64_t(pages) + i * 4, entry)) return false;
        registered |= entry == page;
    }
    const char* name = page_type == kControlsVtable ? "controls_options" :
        page_type == kVisualVtable ? "visual_options" : "audio_options";
    if (!registered || !Field(base, page, 4, menu) || !Span(base, menu, 0xA4) ||
        !Field(base, menu, 0, type) || type != 0x43C8B8 ||
        !RefIs(base, menu + 0x30, name) ||
        !Field(base, menu, 4, frame) || !Field(base, frame, 0, type) || type != 0x43C934 ||
        !RefIs(base, frame + 0x30, "frame") || !Field(base, frame, 4, owner) || owner != options) return false;
    constexpr const char* controls[]{"GEN_InvertLook", "GEN_Vibration", "GEN_LookSensitivity"};
    constexpr const char* audio[]{"GEN_Music", "GEN_FX", "GEN_Speech"};
    const unsigned widgets = page_type == kVisualVtable ? 1 : 3;
    for (unsigned i = 0; i < widgets; ++i) {
        uint32_t widget, label;
        const bool slider = page_type == kAudioVtable || (page_type == kControlsVtable && i == 2);
        // Audio uses the textured slider derived by 1FDCB0, not the base slider.
        const uint32_t widget_type = page_type == kAudioVtable ? 0x43D798 : slider ? 0x43C97C : 0x43C9B0;
        const char* key = page_type == kControlsVtable ? controls[i] :
            page_type == kVisualVtable ? "GEN_Subtitles" : audio[i];
        if (!Field(base, page, 0xC + i * 4, widget) || !Span(base, widget, slider ? 0x88 : 0x90) ||
            !Field(base, widget, 0, type) || type != widget_type ||
            !Field(base, widget, 4, owner) || owner != menu ||
            !RefIs(base, widget + 0x30, key)) return false;
        if (!slider && (!Field(base, widget, 0x58, label) || !Span(base, label, 0x50))) return false;
        if (slider) {
            int32_t minimum, maximum; float value;
            if (!Read(base, uint64_t(widget) + 0x5C, minimum) ||
                !Read(base, uint64_t(widget) + 0x60, maximum) || minimum > maximum ||
                !Read(base, uint64_t(options) + (page_type == kAudioVtable ? 0x8C + i * 4 : 0x80), value) ||
                !std::isfinite(value)) return false;
            if (page_type == kAudioVtable && (minimum != 0 || maximum != 10 || value < 0 || value > 1)) return false;
        }
    }
    return true;
}

void EnsureNativeOptionsEntries(uint8_t* base, uint32_t options) {
    auto* thread = kernel::Current();
    uint32_t type, main, menu, owner, frame, items, shown, selected;
    uint16_t count;
    if (!thread || !thread->ctx || base != kernel::g_base ||
        !Field(base, options, 0, type) || type != kOptionsVtable ||
        !RefIs(base, options + 0x30, "options") ||
        !Field(base, options, 0xF0, main) || !Field(base, main, 0, type) || type != kMainVtable ||
        !Field(base, main, 8, owner) || owner != options || !Field(base, main, 4, menu) ||
        !Span(base, menu, 0xA4) || !Field(base, menu, 0, type) || type != 0x43C8B8 ||
        !RefIs(base, menu + 0x30, "main_options") ||
        !Field(base, menu, 4, frame) || !Field(base, frame, 0, type) || type != 0x43C934 ||
        !Field(base, frame, 4, owner) || owner != options || !RefIs(base, frame + 0x30, "frame") ||
        !Read(base, uint64_t(menu) + 0x58, count) || (count != 5 && count != 4) ||
        !Field(base, menu, 0x5C, items) || !Span(base, items, 20) ||
        !Field(base, menu, 0x64, shown) || shown != count ||
        !Field(base, menu, 0x68, selected) || selected >= count) return;
    constexpr const char* names[]{"GEN_Controls", "GEN_Visual", "GEN_Audio", "XBL_XboxLive", "GEN_Reset"};
    constexpr const char* links[]{"controls_options", "visual_options", "audio_options", "xbox_live_options"};
    uint32_t rows[5];
    for (unsigned i = 0; i < 5; ++i) {
        const unsigned index = count == 4 && i >= 3 ? 7 - i : i;
        if (!Read(base, uint64_t(items) + index * 4, rows[i]) || !Span(base, rows[i], 0x68) ||
            !Field(base, rows[i], 0, type) || type != 0x43C8F8 ||
            !Field(base, rows[i], 4, owner) || owner != menu ||
            !RefIs(base, rows[i] + 0x30, names[i]) ||
            (i < 4 && !RefIs(base, rows[i] + 0x50, links[i]))) return;
    }
    // Keep the removed row owned by the original child list. Retain its pointer
    // outside the active vector so an original parent fade cannot reshow it.
    X86Context call = *thread->ctx;
    if (base[rows[3] + 0x2E]) { call.ecx = rows[3]; kernel::CallGuest(call, 0x1E8E4F, {0}); }
    if (base[rows[3] + 0x2F]) { call.ecx = rows[3]; kernel::CallGuest(call, 0x1E8E77, {0}); }
    if (count == 4) return;
    const uint32_t ordered[]{rows[0], rows[1], rows[2], rows[4], rows[3]};
    std::memcpy(base + items, ordered, sizeof(ordered));
    const uint16_t final_count = 4;
    const uint32_t final_shown = 4, final_selected = std::min(selected, 3u);
    std::memcpy(base + menu + 0x58, &final_count, sizeof(final_count));
    std::memcpy(base + menu + 0x64, &final_shown, sizeof(final_shown));
    std::memcpy(base + menu + 0x68, &final_selected, sizeof(final_selected));
    if (selected == 3) { call.ecx = rows[4]; kernel::CallGuest(call, 0x1E8E4F, {base[menu + 0x2E]}); }
    DarkwatchInvalidateMenuSnapshot();
}

GraphicsRouteState QueryGraphicsMenuRoute(const uint8_t* base) {
    GraphicsRouteState result;
    uint32_t frontend, depth, options, vtable, page_depth, page, owner, main_page;
    options = ActivePause(base);
    result.paused = options != 0;
    if (result.paused) {
        uint8_t mask;
        if (!Read(base, uint64_t(options) + 0x24, mask)) return {};
        result.input_port = mask == 2 ? 1 : 0;
    }
    // Only frontend Options uses E4BDD/E4D03's stack. In-game Pause is an
    // independently registered UI root, selected above from original input scope.
    if (!options && (!Read(base, kFrontend, frontend) || !Field(base, frontend, 8, depth) || !depth || depth > 20 ||
        !Field(base, frontend, 8 + depth * 4, options) || !Field(base, options, 0, vtable) ||
        vtable != kOptionsVtable)) return result;
    if (!Span(base, options, 0xF4)) return {};
    if (
        !Field(base, options, 0x60, page_depth) || !page_depth || page_depth > 5 ||
        !Field(base, options, 0x60 + page_depth * 4, page) || !Field(base, page, 0, vtable) ||
        !Field(base, page, 8, owner) || owner != options) return result;
    if (vtable == (result.paused ? kPauseMainVtable : kMainVtable)) {
        if (!Field(base, options, result.paused ? 0xE8 : 0xF0, main_page) || main_page != page) return {};
        result.route = GraphicsMenuRoute::OptionsMain;
        result.pause_settings_available = result.paused && PauseControlsKey(base, options);
    } else if (!result.paused && vtable == kVisualVtable) {
        result.route = GraphicsMenuRoute::Visual;
        uint32_t widget;
        uint8_t subtitles;
        if (Field(base, page, 0xC, widget) && widget && Read(base, uint64_t(options) + 0x88, subtitles)) {
            result.subtitles_available = Span(base, widget, 0x90);
            result.subtitles = subtitles != 0;
        }
    } else if (!result.paused && vtable == kAudioVtable) {
        result.route = GraphicsMenuRoute::Audio;
    } else if (vtable == kControlsVtable) {
        result.route = GraphicsMenuRoute::Controls;
        uint32_t preset_ref;
        if (Field(base, options, 0x84, preset_ref) && preset_ref) {
            constexpr const char* names[]{"Default", "Chieftain", "Lefty", "Hopalong", "Hoss"};
            char name[10]{};
            for (unsigned i = 0; i < sizeof(name); ++i) {
                if (!Read(base, uint64_t(preset_ref) + 2 + i, name[i])) break;
                if (!name[i]) {
                    for (unsigned n = 0; n < std::size(names); ++n)
                        if (!std::strcmp(name, names[n])) result.controller_preset = int32_t(n);
                    break;
                }
            }
        }
        uint32_t invert_widget, vibration_widget, sensitivity_widget, label1, label2;
        uint8_t invert, vibration;
        float sensitivity;
        if (Field(base, page, 0xC, invert_widget) && Field(base, page, 0x10, vibration_widget) &&
            Field(base, page, 0x14, sensitivity_widget) && Span(base, invert_widget, 0x90) &&
            Span(base, vibration_widget, 0x90) && Span(base, sensitivity_widget, 0x7C) &&
            Field(base, invert_widget, 0x58, label1) && Span(base, label1, 0x50) &&
            Field(base, vibration_widget, 0x58, label2) && Span(base, label2, 0x50) &&
            Read(base, uint64_t(options) + 0x7C, invert) && Read(base, uint64_t(options) + 0x7D, vibration) &&
            Read(base, uint64_t(options) + 0x80, sensitivity) && std::isfinite(sensitivity) &&
            Read(base, uint64_t(sensitivity_widget) + 0x5C, result.sensitivity_min) &&
            Read(base, uint64_t(sensitivity_widget) + 0x60, result.sensitivity_max) &&
            result.sensitivity_min <= result.sensitivity_max) {
            result.invert = invert != 0; result.vibration = vibration != 0;
            result.sensitivity = int32_t(std::clamp(double(sensitivity) * 10.0 + .49,
                                           double(result.sensitivity_min), double(result.sensitivity_max)));
            result.controls_available = true;
        }
    } else return result;
    if (result.paused && result.route == GraphicsMenuRoute::Controls) {
        // Pause owns the same profile settings as frontend Options, but does
        // not construct a Visual handler. Its host Graphics page uses Controls.
        uint8_t subtitles;
        if (Read(base, uint64_t(options) + 0x88, subtitles)) {
            result.subtitles_available = true;
            result.subtitles = subtitles != 0;
        }
    }
    if (result.route == GraphicsMenuRoute::Audio ||
        (result.paused && result.route == GraphicsMenuRoute::Controls)) {
        float values[3]; uint32_t widgets[3];
        if ((result.paused || AudioWidgets(base, page, widgets)) &&
            Read(base, uint64_t(options) + 0x8C, values) &&
            std::all_of(std::begin(values), std::end(values), [](float v) { return std::isfinite(v) && v >= 0 && v <= 1; })) {
            result.audio = {int(std::lround(values[0] * 100)), int(std::lround(values[1] * 100)), int(std::lround(values[2] * 100))};
            result.audio_available = true;
        }
    }
    result.options = options;
    result.page = page;
    return result;
}

bool SetGraphicsSubtitles(uint8_t* base, uint32_t expected_options, bool enabled) {
    const auto route = QueryGraphicsMenuRoute(base);
    auto* thread = kernel::Current();
    if ((route.route != GraphicsMenuRoute::Visual &&
         !(route.paused && route.route == GraphicsMenuRoute::Controls)) ||
        route.options != expected_options || !route.subtitles_available ||
        !thread || !thread->ctx || base != kernel::g_base || thread->ctx->esp < 0x100 ||
        !Span(base, uint64_t(thread->ctx->esp) - 0x100, 0x100) ||
        !Span(base, 0x4B7A42, 1)) return false;
    X86Context call = *thread->ctx;
    if (!route.paused) {
        uint32_t widget, label;
        if (!Field(base, route.page, 0xC, widget) || !Field(base, widget, 0x58, label) ||
            !Span(base, label, 0x50)) return false;
        // Keep the frontend BoolWidget's owned caption in sync. Pause has no
        // subtitle widget; its Controls+0C is Invert Look and must stay intact.
        call.ecx = widget;
        kernel::CallGuest(call, 0x001F0396, {uint32_t(enabled), 0});
        call = *thread->ctx;
    }
    // F65F2 updates the owned profile copy. F017C applies Pause's dirty copy
    // through FA68A when resuming, just as for the original control settings.
    call.ecx = route.options + 0x78;
    kernel::CallGuest(call, 0x000F65F2, {uint32_t(enabled)});
    base[route.options + 0xE4] = 1;  // F6609 marks the Options copy dirty after the same setting call.
    // Gameplay reads the separate global via 21B02C/21B8F7. The original
    // frontend's full apply (CA630) syncs it, but Pause's FA68A only copies the
    // owner's settings. Use the original narrow setter without reapplying audio.
    call = *thread->ctx;
    kernel::CallGuest(call, 0x0021B03C, {uint32_t(enabled)});
    return true;
}

bool SetOriginalControls(uint8_t* base, uint32_t expected_options, bool invert, bool vibration, int32_t sensitivity) {
    const auto route = QueryGraphicsMenuRoute(base);
    auto* thread = kernel::Current();
    if (route.route != GraphicsMenuRoute::Controls || route.options != expected_options ||
        !route.controls_available || !thread || !thread->ctx || base != kernel::g_base) return false;
    uint32_t widgets[3];
    if (!Field(base, route.page, 0xC, widgets[0]) || !Field(base, route.page, 0x10, widgets[1]) ||
        !Field(base, route.page, 0x14, widgets[2])) return false;
    const uint32_t setters[]{0xE7435, 0xE744C};
    const bool values[]{invert, vibration};
    for (unsigned i = 0; i < 2; ++i) {
        X86Context call = *thread->ctx; call.ecx = widgets[i];
        kernel::CallGuest(call, 0x1F0396, {uint32_t(values[i]), 0});
        call = *thread->ctx; call.ecx = route.options + 0x78;
        kernel::CallGuest(call, setters[i], {uint32_t(values[i])});
    }
    sensitivity = std::clamp(sensitivity, route.sensitivity_min, route.sensitivity_max);
    X86Context call = *thread->ctx; call.ecx = widgets[2];
    kernel::CallGuest(call, 0x1F0210, {uint32_t(sensitivity), 0});
    // Read the original widget's normalized value, as F5552 does before E7463.
    int32_t selected;
    if (!Read(base, uint64_t(widgets[2]) + 0x64, selected)) return false;
    float value = float(selected) * .1f; uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    call = *thread->ctx; call.ecx = route.options + 0x78;
    kernel::CallGuest(call, 0xE7463, {bits});
    base[route.options + 0xE4] = 1;
    return true;
}

bool SetOriginalAudio(uint8_t* base, uint32_t expected_options, const AudioSettings& settings) {
    const auto route = QueryGraphicsMenuRoute(base);
    auto* thread = kernel::Current();
    const int values[]{settings.music, settings.effects, settings.speech};
    uint32_t widgets[3]{};
    if (!route.audio_available || route.options != expected_options ||
        !thread || !thread->ctx || base != kernel::g_base ||
        thread->ctx->esp < 0x100 || !Span(base, uint64_t(thread->ctx->esp) - 0x100, 0x100) ||
        std::any_of(std::begin(values), std::end(values), [](int v) { return v < 0 || v > 100; }) ||
        (!route.paused && !AudioWidgets(base, route.page, widgets))) return false;
    // F536E updates these same profile fields; Pause owns the same settings
    // copy but does not construct an Audio handler or its volume widgets.
    constexpr uint32_t setters[]{0xF525B, 0xF5272, 0xF5289};
    for (unsigned i = 0; i < 3; ++i) {
        X86Context call = *thread->ctx;
        if (widgets[i]) {
            call.ecx = widgets[i];
            kernel::CallGuest(call, 0x1F0210, {uint32_t((values[i] + 5) / 10), 0});
            call = *thread->ctx;
        }
        const float value = float(values[i]) / 100.f;
        uint32_t bits; std::memcpy(&bits, &value, sizeof(bits));
        call.ecx = route.options + 0x78;
        kernel::CallGuest(call, setters[i], {bits});
    }
    base[route.options + 0xE4] = 1;
    return true;
}

bool SetControllerPreset(uint8_t* base, uint32_t expected_options, int32_t preset) {
    constexpr const char* names[]{"Default", "Chieftain", "Lefty", "Hopalong", "Hoss"};
    const auto route = QueryGraphicsMenuRoute(base);
    auto* thread = kernel::Current();
    if (preset < 0 || preset >= int(std::size(names)) || route.route != GraphicsMenuRoute::Controls ||
        route.options != expected_options || !route.controls_available || route.controller_preset < 0 ||
        !thread || !thread->ctx || base != kernel::g_base) return false;
    if (route.controller_preset == preset) return true;
    uint32_t name;
    const auto length = uint32_t(std::strlen(names[preset]) + 1);
    if (!Read(base, 0x429BDC + preset * 4, name) || !Span(base, name, length) ||
        std::memcmp(base + name, names[preset], length) || thread->ctx->esp < 0x2000 ||
        !Span(base, uint64_t(thread->ctx->esp) - 0x2000, 0x2000)) return false;
    // E6DE7 uses this owned-string setter and dirty flag before leaving the original diagram.
    const auto scratch = thread->ctx->esp - 0x20;
    std::memset(base + scratch, 0, 4);
    X86Context call = *thread->ctx;
    call.esp = scratch - 0x10;
    call.ecx = scratch;
    kernel::CallGuest(call, 0x138FA, {name});
    call.ecx = route.options + 0x78;
    kernel::CallGuest(call, 0xE6CF1, {scratch});
    call.ecx = scratch;
    kernel::CallGuest(call, 0x11C1A, {});
    base[route.options + 0xE4] = 1;
    return true;
}

bool OpenControllerConfiguration(uint8_t* base, uint32_t expected_options) {
    const auto route = QueryGraphicsMenuRoute(base);
    auto* thread = kernel::Current();
    if (route.route != GraphicsMenuRoute::Controls || route.options != expected_options ||
        !thread || !thread->ctx || base != kernel::g_base) return false;
    // F54B0 is this page's original action: push controller_config and attach its Options owner.
    X86Context call = *thread->ctx; call.ecx = route.page;
    kernel::CallGuest(call, 0xF54B0, {0});
    return true;
}

bool OpenPauseSettings(uint8_t* base, uint32_t expected_options) {
    const auto route = QueryGraphicsMenuRoute(base);
    auto* thread = kernel::Current();
    if (!route.paused || route.route != GraphicsMenuRoute::OptionsMain || route.options != expected_options ||
        !route.pause_settings_available || !thread || !thread->ctx || base != kernel::g_base ||
        thread->ctx->esp < 0x100 || !Span(base, uint64_t(thread->ctx->esp) - 0x100, 0x100)) return false;
    const auto key = PauseControlsKey(base, route.options);
    if (!key) return false;
    X86Context call = *thread->ctx;
    call.ecx = route.options;
    kernel::CallGuest(call, 0x000EBB03, {key});
    const auto opened = QueryGraphicsMenuRoute(base);
    return opened.paused && opened.options == expected_options && opened.route == GraphicsMenuRoute::Controls;
}

bool EnsureNativePauseEntries(uint8_t* base) {
    auto* thread = kernel::Current();
    if (!thread || !thread->ctx || base != kernel::g_base) return false;
    const auto route = QueryGraphicsMenuRoute(base);
    auto& cached = g_pause_rows[route.input_port];
    uint32_t main, menu, items;
    uint16_t count;
    if (!route.paused || route.route != GraphicsMenuRoute::OptionsMain || !route.pause_settings_available ||
        !thread || !thread->ctx || base != kernel::g_base ||
        !PauseMenu(base, route.options, main, menu, items, count)) return false;
    if (AddedRows(cached, base, route.options, main, menu, items, count)) {
        cached.consumed = false; // Observed return to the original main page.
        return true;
    }
    uint32_t options_row, live_row;
    if (count != 6 || !Read(base, uint64_t(items) + 8, options_row) || !RefIs(base, options_row + 0x30, "GEN_Options") ||
        !Read(base, uint64_t(items) + 12, live_row) || !RefIs(base, live_row + 0x30, "XBL_XboxLiveOptions")) return false;
    uint32_t shown, frame;
    float rect[4], baseline[4], live[4];
    if (!Field(base, menu, 0x64, shown) || shown || !Read(base, uint64_t(menu) + 0x10, rect) ||
        rect[0] != 0.f || rect[1] != .29f || rect[2] != .8f || rect[3] != .71f ||
        !PauseFrame(base, route.options, menu, frame) ||
        !Read(base, uint64_t(route.options) + 0xFC, baseline) ||
        !Read(base, uint64_t(frame) + 0x10, live) ||
        baseline[0] != 0.f || baseline[1] != 0.f || baseline[2] != .42f || baseline[3] != .29f ||
        live[0] != baseline[0] || live[1] != baseline[1] || live[3] != baseline[3] ||
        thread->ctx->esp < 0x2000 || !Span(base, uint64_t(thread->ctx->esp) - 0x2000, 0x2000)) return false;
    const auto key = PauseControlsKey(base, route.options);
    if (!key) return false;
    // Reserve local owned references above the cloned call stack. All new
    // objects/strings and their child ownership use the game's original APIs.
    const uint32_t scratch = thread->ctx->esp - 0x80;
    std::memset(base + scratch, 0, 0x80);
    // A leading tilde is the original dynamic-literal contract; unprefixed
    // text is a localization key and an absent key renders an empty string.
    std::memcpy(base + scratch + 0x20, "~GRAPHICS", 10);
    std::memcpy(base + scratch + 0x40, "~CONTROLS", 10);
    std::memcpy(base + scratch + 0x60, "~AUDIO", 7);
    X86Context call = *thread->ctx;
    call.esp = scratch - 0x10;
    uint32_t rows[3]{};
    for (unsigned i = 0; i < 3; ++i) {
        call.ecx = scratch + i * 4;
        kernel::CallGuest(call, 0x138FA, {scratch + 0x20 + i * 0x20});
        const auto allocation = kernel::CallGuest(call, 0x24C546, {0x68});
        if (allocation) {
            call.ecx = allocation;
            rows[i] = kernel::CallGuest(call, 0x1EFB52, {scratch + i * 4, key, scratch + 0x10});
        }
        call.ecx = scratch + i * 4;
        kernel::CallGuest(call, 0x11C1A, {});
        if (!rows[i]) {
            for (unsigned j = 0; j < i; ++j) {
                call.ecx = rows[j]; kernel::CallGuest(call, 0xECB9D, {1});
            }
            return false;
        }
    }
    for (const auto row : rows) {
        call.ecx = menu;
        kernel::CallGuest(call, 0x1EFA66, {row});
    }
    // Replace Options and unused Xbox Live in the navigation vector. Retain
    // both owned children for the original destructor, but hide and unfocus
    // them because base render/input traversal also walks the child list.
    uint32_t ordered[9], selected;
    if (!Field(base, menu, 0x5C, items) || !Read(base, items, ordered) ||
        !Field(base, menu, 0x68, selected) || selected >= 6) return false;
    const uint32_t removed[]{ordered[2], ordered[3]};
    for (const auto row : removed) {
        call.ecx = row;
        kernel::CallGuest(call, 0x1E8E4F, {0});
        call.ecx = row;
        kernel::CallGuest(call, 0x1E8E77, {0});
    }
    const uint32_t final_rows[]{ordered[0], ordered[1], rows[0], rows[1], rows[2],
        ordered[4], ordered[5], 0, 0};
    std::memcpy(base + items, final_rows, sizeof(final_rows));
    const uint16_t final_count = 7;
    std::memcpy(base + menu + 0x58, &final_count, sizeof(final_count));
    // Preserve Restart/Quit selection when the new Audio entry shifts them.
    if (selected >= 4) {
        ++selected;
        std::memcpy(base + menu + 0x68, &selected, sizeof(selected));
    }
    if (selected == 2 || selected == 3) {
        call.ecx = rows[selected - 2];
        kernel::CallGuest(call, 0x1E8E4F, {base[menu + 0x2E]});
    }
    // Original all-row layout fits seven entries within the existing frame/footer.
    cached = {base, route.options, main, menu, {rows[0], rows[1], rows[2]}, {removed[0], removed[1]}, false};
    DarkwatchInvalidateMenuSnapshot();
    return true;
}

uint32_t TakeNativePauseEntry(uint8_t* base, uint32_t expected_options) {
    const auto* thread = kernel::Current();
    if (!thread || !thread->ctx || base != kernel::g_base) return 0;
    const auto route = QueryGraphicsMenuRoute(base);
    auto& cached = g_pause_rows[route.input_port];
    uint32_t main, menu, items, selected;
    uint16_t count;
    if (!route.paused || route.options != expected_options || route.route != GraphicsMenuRoute::Controls ||
        cached.consumed || !PauseMenu(base, route.options, main, menu, items, count) ||
        !AddedRows(cached, base, route.options, main, menu, items, count) ||
        !Field(base, menu, 0x68, selected) || selected < 2 || selected > 4 ||
        !base[cached.rows[selected - 2] + 0x54]) return 0;
    cached.consumed = true;
    return selected - 1;
}
}  // namespace darkwatch

void DarkwatchPauseLiveStatus(X86Context& ctx, uint8_t* base) {
    uint32_t type, status, parent;
    // EFDA5 binds Pause+F0 to the XboxOnly "live_aware" child. F0279
    // checks its visibility before updating the obsolete Xbox Live status.
    if (base != kernel::g_base || !darkwatch::Field(base, ctx.esi, 0, type) ||
        type != darkwatch::kPauseVtable || !darkwatch::Field(base, ctx.esi, 0xF0, status) ||
        !darkwatch::Field(base, status, 0, type) || type != 0x43C36C ||
        !darkwatch::Field(base, status, 4, parent) || parent != ctx.esi ||
        !darkwatch::Span(base, status, 0x34) || !darkwatch::RefIs(base, status + 0x30, "live_aware")) return;
    base[status + 0x2F] = 0;
}

void DarkwatchGraphicsLabel(X86Context& ctx, uint8_t* base) {
    uint32_t key_object, key_data, output;
    char key[11];
    if (!darkwatch::Read(base, uint64_t(ctx.ebp) + 12, key_object) ||
        !darkwatch::Field(base, key_object, 0, key_data) || !key_data ||
        !darkwatch::Read(base, uint64_t(key_data) + 2, key) ||
        (std::memcmp(key, "GEN_Visual", sizeof(key)) && std::memcmp(key, "GEN_VISUAL", sizeof(key))) ||
        !darkwatch::Read(base, uint64_t(ctx.ebp) + 8, output) || !darkwatch::Span(base, output, 4) ||
        ctx.esp < 32 || !darkwatch::Span(base, uint64_t(ctx.esp) - 32, 32) || base != kernel::g_base) return;
    // Keep the title's localization-reference ownership; never overwrite a shared string's bytes.
    X86Context call = ctx;
    call.esp -= 16;
    std::memcpy(base + call.esp, "~Graphics", 10);
    call.ecx = output;
    kernel::CallGuest(call, 0x001E94E6, {call.esp});
}
