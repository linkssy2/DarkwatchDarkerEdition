#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <imgui.h>
#include <imgui_internal.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <mutex>
#include <vector>
#include "app/app.h"
#include "audio/audio.h"
#include "core/input.h"
#include "core/log.h"
#include "gpu/backend.h"
#include "kernel/memory.h"
#include "common/graphics.h"
#include "common/graphics_route.h"
#include "common/desktop_quit.h"
#include "common/campaign_replay.h"
#include "common/graphics_view.h"
#include "common/graphics_hud.h"
#include "common/hd_ui.h"
#include "common/controls.h"
#include "common/character_selection.h"
#include "common/coop_characters.h"
#include "common/character_preview.h"
#include "common/character_runtime.h"
#include "common/prompts.h"
#include "common/settings_skin.h"
#include "common/language.h"

using namespace darkwatch;

namespace {
std::atomic<bool> g_visual{false}, g_leave{false}, g_configuring{false};
bool g_controls = false, g_subtitles_available = false;
std::atomic<uint64_t> g_set_subtitles{0};
std::atomic<uint32_t> g_pad{0};
std::atomic<uint32_t> g_navigation_port{0};
bool g_gamepad_back_consumed = false;
int g_binding_focus = -1;
uint32_t g_options = 0;
std::atomic<bool> g_released{false}, g_block_release{false};
bool g_open = false, g_confirm = false;
bool g_open_controls = false;
std::atomic<uint32_t> g_characters_owner{0};
std::atomic<int> g_character_choice{-1};
std::atomic<bool> g_character_save_failed{false};
std::atomic<uint32_t> g_quit_owner{0};
// 0: awaiting choice, 1: confirm requested, 2: close queued, 3: close failed.
std::atomic<unsigned> g_quit_choice{0};
bool g_quit = false, g_open_quit = false, g_quit_ready = false;
bool g_characters = false, g_open_characters = false;
bool g_coop = false, g_open_coop = false, g_coop_ui_ready = false;
std::atomic<uint32_t> g_coop_owner{0};
std::array<std::atomic<uint32_t>, 2> g_coop_pressed{};
std::array<uint32_t, 2> g_coop_held{};
std::array<bool, 2> g_coop_released{};
std::array<bool, 2> g_coop_block_release{};
CoopSetupState g_coop_state;
struct CoopRequest {uint32_t owner = 0; int character = -1, ready = -1; bool back = false;};
std::array<CoopRequest, 2> g_coop_requests{};
std::array<double, 2> g_coop_preview_started{};
std::array<settings::Character, 2> g_coop_preview_characters{};
// Each player has an independent highlight: Previous, Next, or Ready.
std::array<unsigned, 2> g_coop_focus{};
std::atomic<bool> g_coop_failed{false};
settings::Character g_character_draft = settings::Character::Jericho;
double g_character_preview_started = 0;
bool g_character_ready = false;
bool g_page_graphics = false;
bool g_audio = false, g_open_audio = false, g_pause_audio = false;
bool g_audio_focus = false, g_audio_returned = false;
bool g_surround_draft = false;
AudioSettings g_audio_draft;
struct AudioRequest { uint32_t options = 0; AudioSettings settings; };
AudioRequest g_audio_request;
std::atomic<bool> g_audio_apply_failed{false};
bool g_controller_layout = false, g_layout_opened = false, g_layout_returned = false;
input::ControllerFamily g_layout_family = input::ControllerFamily::Xbox;
input::PadBindings g_pad_draft = input::DefaultPadBindings();
int g_pad_capture_action = -1, g_pad_binding_focus = -1;
uint32_t g_open_options = 0, g_open_page = 0, g_open_pause_entry = 0;
bool g_subtitles_draft = false;
app::Settings g_draft, g_previous;
view::Settings g_view_draft, g_view_previous;
double g_confirm_until = 0;
const char* g_notice = "";
ImFont *g_body = nullptr, *g_title = nullptr;
float g_font_scale = 1;
std::vector<app::Mode> g_modes;
ControlsSettings g_controls_draft;
darkwatch::GraphicsRouteState g_original_controls, g_original_draft;
std::mutex g_original_lock;
void PublishCoopSetup(const CoopSetupState& state) {
    {std::lock_guard lock(g_original_lock); g_coop_state = state;}
    const auto previous = g_coop_owner.exchange(state.owner);
    if (state.owner) {g_visual = true; g_leave = false;}
    if (previous != state.owner) {
        if (previous && !state.owner) g_coop_block_release = {true, true};
        for (auto& pressed : g_coop_pressed) pressed = 0;
        g_coop_held = {}; g_coop_released = {};
        g_pad = 0; g_released = false; g_block_release = state.owner != 0;
    }
}
uint32_t g_pause_owner = 0, g_pause_page = 0, g_pause_entry = 0;
struct ControlRequest {
    uint32_t options = 0;
    bool invert = false, vibration = false, configure = false;
    int32_t sensitivity = 0;
    bool apply = false;
    int32_t preset = -1;
};
ControlRequest g_control_request;
uint32_t g_return_controls_options = 0, g_return_controls_page = 0, g_capture_key = 0;
int g_capture_action = -1, g_capture_slot = 0, g_conflict_action = -1;
constexpr const char* kActions[] = {"D-PAD UP", "D-PAD DOWN", "D-PAD LEFT", "D-PAD RIGHT",
    "START", "BACK", "LEFT STICK CLICK", "RIGHT STICK CLICK", "A BUTTON", "B BUTTON",
    "X BUTTON", "Y BUTTON", "BLACK BUTTON", "WHITE BUTTON", "LEFT TRIGGER", "RIGHT TRIGGER",
    "MOVE FORWARD", "MOVE BACKWARD", "MOVE LEFT", "MOVE RIGHT"};
constexpr const char* kDescriptions[] = {"Navigate up with the original D-pad.", "Navigate down with the original D-pad.",
    "Navigate left with the original D-pad.", "Navigate right with the original D-pad.",
    "Open the original pause menu.", "Send the original Xbox Back action.",
    "Send the left-stick button action.", "Send the right-stick button action.",
    "Select in menus; gameplay uses your controller layout.", "Go back in menus; gameplay uses your controller layout.",
    "Send the original Xbox X action.", "Send the original Xbox Y action.",
    "Send the original Xbox Black action.", "Send the original Xbox White action.",
    "Send the original left-trigger action.", "Send the original right-trigger action.",
    "Move forward with the left stick.", "Move backward with the left stick.",
    "Strafe left with the left stick.", "Strafe right with the left stick."};
constexpr const char* kPresetNames[]{"Default", "Chieftain", "Lefty", "Hopalong", "Hoss"};
enum ActionMeaning {Unknown, Talk, Cycle, LeanLeft, LeanRight, Pause, Score, Crouch, Sight,
    Interact, Reload, Melee, Jump, SelectPower, ActivatePower, Throw, Shoot};
struct ActionText {const char* name; const char* description;};
constexpr ActionText kMeaning[]{
    {"", ""}, {"MULTIPLAYER TALK", "Talk in multiplayer."}, {"SWITCH WEAPONS", "Swap between your carried weapons."},
    {"LEAN LEFT", "Lean to the left."}, {"LEAN RIGHT", "Lean to the right."},
    {"PAUSE", "Open the pause menu."}, {"MULTIPLAYER SCORE", "Show multiplayer scores."},
    {"CROUCH", "Crouch."}, {"SIGHT MODE", "Use your weapon's sight mode."},
    {"INTERACT", "Interact with objects."}, {"RELOAD", "Reload your weapon."},
    {"MELEE", "Perform a melee attack."}, {"JUMP", "Jump."},
    {"POWER SELECTION", "Select a power."}, {"ACTIVATE POWER", "Activate your selected power."},
    {"THROW", "Throw."}, {"SHOOT", "Fire your weapon."}};
// switchprimary in the original preset tables resolves to Down, except Chieftain's Y.
constexpr ActionMeaning kPresetActions[][16]{
    {Unknown, Cycle, LeanLeft, LeanRight, Pause, Score, Crouch, Sight, Interact, Reload, Melee, Jump, SelectPower, ActivatePower, Throw, Shoot},
    {Unknown, Unknown, LeanLeft, LeanRight, Pause, Score, Crouch, Sight, Jump, Melee, Reload, Cycle, Interact, ActivatePower, Throw, Shoot},
    {Unknown, Cycle, LeanLeft, LeanRight, Pause, Score, Sight, Crouch, Interact, Melee, Reload, Throw, ActivatePower, SelectPower, Shoot, Jump},
    {Unknown, Cycle, LeanLeft, LeanRight, Pause, Score, Crouch, Sight, Interact, Melee, Reload, Throw, SelectPower, ActivatePower, Jump, Shoot},
    {Unknown, Cycle, LeanLeft, LeanRight, Pause, Score, Crouch, Sight, Interact, Jump, Throw, Reload, SelectPower, ActivatePower, Melee, Shoot}};
bool KnownPreset() {return g_original_draft.controller_preset >= 0 && g_original_draft.controller_preset < int(std::size(kPresetNames));}
const char* ActionName(unsigned action) {
    if (action >= 16) {
        constexpr const char* stick[]{"LEFT STICK UP", "LEFT STICK DOWN", "LEFT STICK LEFT", "LEFT STICK RIGHT"};
        constexpr const char* look[]{"LOOK UP", "LOOK DOWN", "LOOK LEFT", "LOOK RIGHT"};
        if (g_original_draft.controller_preset == 2) return look[action - 16];
        if (KnownPreset()) return kActions[action];
        return stick[action - 16];
    }
    if (KnownPreset()) if (auto meaning = kPresetActions[g_original_draft.controller_preset][action]) return kMeaning[meaning].name;
    return kActions[action];
}
const char* ActionDescription(unsigned action) {
    if (action >= 16) {
        constexpr const char* stick[]{"Original left stick up; see controller layout.", "Original left stick down; see controller layout.",
                                     "Original left stick left; see controller layout.", "Original left stick right; see controller layout."};
        constexpr const char* look[]{"Look up with the Lefty layout.", "Look down with the Lefty layout.",
                                    "Look left with the Lefty layout.", "Look right with the Lefty layout."};
        if (g_original_draft.controller_preset == 2) return look[action - 16];
        if (KnownPreset()) return kDescriptions[action];
        return stick[action - 16];
    }
    if (KnownPreset()) if (auto meaning = kPresetActions[g_original_draft.controller_preset][action]) return kMeaning[meaning].description;
    return kDescriptions[action];
}

void Revert() {
    app::Apply(g_previous);
    view::Apply(g_view_previous);
    app::ApplyDisplay();
    g_draft = g_previous;
    g_view_draft = g_view_previous;
    g_confirm = false;
    g_notice = "Previous display settings restored.";
}

void SaveChanges() {
    if (g_subtitles_available) g_set_subtitles = (uint64_t(g_options) << 1) | uint64_t(g_subtitles_draft);
    if (app::Save()) {
        g_notice = "Settings saved.";
    } else {
        g_notice = "Could not save settings. Changes will last for this session only.";
    }
    g_confirm = false;
}

void Close() {
    if (g_confirm) Revert();
    g_open = false;
    const auto quit_owner = g_quit_owner.exchange(0);
    g_quit_choice = 0;
    g_character_choice = -1;
    if (g_characters_owner.exchange(0) || quit_owner) {g_leave = false; g_visual = false;}
    else g_leave = true;
    g_released = false;
    g_block_release = true;
    ControlsCancelCapture(); g_capture_action = -1; g_conflict_action = -1;
    g_pad_capture_action = g_pad_binding_focus = -1;
    g_binding_focus = -1;
    g_return_controls_options = 0;
    g_controller_layout = false;
    g_pause_audio = false;
    g_layout_returned = false;
}

bool PlayerTwoControls() { return g_original_draft.paused && g_original_draft.input_port == 1; }
int ControlsPort() { return PlayerTwoControls() ? 1 : 0; }

void ApplyControls() {
    const bool player_two = PlayerTwoControls();
    if (!player_two && !ControlsApply(g_controls_draft)) {
        g_notice = "Cannot apply these bindings. Check for duplicate or reserved keys.";
        return;
    }
    if (!player_two) g_controls_draft = ControlsSnapshot();
    if (!input::SetPadBindings(ControlsPort(), g_pad_draft)) {
        g_notice = "Cannot apply these controller bindings.";
        return;
    }
    if (g_original_draft.controls_available) {
        std::lock_guard lock(g_original_lock);
        g_control_request = {g_options, g_original_draft.invert, g_original_draft.vibration, false,
                             g_original_draft.sensitivity, true, g_original_draft.controller_preset};
    }
    if (player_two) {
        g_notice = app::Save() ? "Player 2 bindings saved. Resume to save profile settings."
                              : "Could not save controls. Changes will last for this session only.";
        return;
    }
    g_notice = app::Save() ? "Controls saved. Original profile settings save when you leave Options."
                          : "Could not save controls. Changes will last for this session only.";
}

void CaptureBinding() {
    uint32_t key = ControlsTakeCapture();
    if (!key || g_capture_action < 0) return;
    if (key == kCaptureCancelled) {g_capture_action = -1; return;}
    if (key == kCaptureReserved) {g_notice = "That key is reserved. Choose another key.";return;}
    if (key == kCaptureClear) key = 0;
    g_capture_key = key; g_conflict_action = -1;
    if (key) for (unsigned i = 0; i < g_controls_draft.bindings.size(); ++i)
        if (int(i) != g_capture_action) for (auto old : g_controls_draft.bindings[i].keys)
            if (old == key) g_conflict_action = int(i);
    if (g_conflict_action < 0) {
        auto& binding = g_controls_draft.bindings[g_capture_action];
        if (key && binding.keys[1 - g_capture_slot] == key) binding.keys[1 - g_capture_slot] = 0;
        binding.keys[g_capture_slot] = key; g_capture_action = -1;
    }
}

void ReplaceBinding() {
    if (g_capture_action < 0 || g_capture_action >= int(g_controls_draft.bindings.size()) ||
        g_capture_slot < 0 || g_capture_slot > 1 || g_conflict_action < 0) return;
    for (auto& binding : g_controls_draft.bindings)
        for (auto& key : binding.keys) if (key == g_capture_key) key = 0;
    g_controls_draft.bindings[g_capture_action].keys[g_capture_slot] = g_capture_key;
    g_capture_action = -1; g_conflict_action = -1;
}

void ApplyChanges() {
    g_previous = app::Snapshot();
    g_view_previous = view::Snapshot();
    g_draft = app::Normalize(g_draft);
    g_view_draft = view::Normalize(g_view_draft);
    bool display = g_previous.display_mode != g_draft.display_mode ||
        g_previous.width != g_draft.width || g_previous.height != g_draft.height ||
        g_previous.aspect_ratio != g_draft.aspect_ratio;
    app::Apply(g_draft);
    view::Apply(g_view_draft);
    if (display) {
        app::ApplyDisplay();
        g_confirm = true;
        g_confirm_until = ImGui::GetTime() + 15.0;
        g_notice = "";
    } else SaveChanges();
}

void FpsCounter(double fps) {
    if (!view::Snapshot().show_fps || !std::isfinite(fps) || fps < 0) return;
    const auto& io = ImGui::GetIO();
    if (io.DisplaySize.x <= 0 || io.DisplaySize.y <= 0) return;
    const float scale = std::max(.5f, std::min(io.DisplaySize.x / 1280.f, io.DisplaySize.y / 720.f));
    ImFont* font = g_body ? g_body : ImGui::GetFont();
    const float height = 20 * scale, pad = 8 * scale, margin = 16 * scale;
    char text[32]; std::snprintf(text, sizeof(text), "%.0f FPS", std::min(fps, 99999.0));
    ImVec2 size = font->CalcTextSizeA(height, FLT_MAX, 0, text);
    ImVec2 a(std::max(margin, io.DisplaySize.x - margin - size.x - 2 * pad), margin);
    if (DarkwatchHudSplitView()) a.y = std::max(margin, io.DisplaySize.y - margin - size.y - 2 * pad);
    ImVec2 b(a.x + size.x + 2 * pad, a.y + size.y + 2 * pad);
    auto* draw = ImGui::GetForegroundDrawList();
    draw->AddRectFilled(a, b, IM_COL32(12, 15, 19, 210), 2 * scale);
    draw->AddLine({a.x, b.y}, b, IM_COL32(132, 21, 26, 230), scale);
    draw->AddText(font, height, {a.x + pad, a.y + pad}, IM_COL32(235, 235, 222, 255), text);
}

void CharacterNotice() {
    static unsigned previous = 0;
    static double until = 0;
    const unsigned unavailable = DarkwatchCharacterUnavailablePlayers();
    if (unavailable != previous) {previous = unavailable; until = ImGui::GetTime() + 12;}
    static double save_notice_until = 0;
    static double campaign_notice_until = 0;
    if (DarkwatchCampaignReplayTakeFailure()) campaign_notice_until = ImGui::GetTime() + 12;
    const bool campaign_failed = ImGui::GetTime() < campaign_notice_until;
    if (g_character_save_failed.exchange(false)) save_notice_until = ImGui::GetTime() + 10;
    const bool save_failed = ImGui::GetTime() < save_notice_until;
    if (!campaign_failed && !save_failed && (!unavailable || ImGui::GetTime() >= until)) return;
    const char* text = unavailable == 1 ? "PLAYER ONE: CHARACTER UNAVAILABLE. USING ORIGINAL CHARACTER."
        : unavailable == 2 ? "PLAYER TWO: CHARACTER UNAVAILABLE. USING ORIGINAL CHARACTER."
                           : "CHARACTERS UNAVAILABLE. USING ORIGINAL CHARACTERS.";
    text = language::Text(campaign_failed ? "COULD NOT PREPARE CAMPAIGN. RESTART THE GAME AND TRY AGAIN." :
        save_failed ? "CHARACTER SELECTED FOR THIS SESSION. COULD NOT SAVE SETTINGS." : text);
    const auto& io = ImGui::GetIO();
    if (io.DisplaySize.x <= 0 || io.DisplaySize.y <= 0) return;
    const float scale = std::max(.5f, std::min(io.DisplaySize.x / 1280.f, io.DisplaySize.y / 720.f));
    ImFont* font = g_body ? g_body : ImGui::GetFont();
    const float height = 17 * scale, pad = 8 * scale;
    const auto size = font->CalcTextSizeA(height, FLT_MAX, 0, text);
    const ImVec2 a((io.DisplaySize.x - size.x) / 2 - pad, 24 * scale);
    const ImVec2 b(a.x + size.x + 2 * pad, a.y + size.y + 2 * pad);
    auto* draw = ImGui::GetForegroundDrawList();
    draw->AddRectFilled(a, b, IM_COL32(12, 15, 19, 230));
    draw->AddLine({a.x, b.y}, b, IM_COL32(132, 21, 26, 255), scale);
    draw->AddText(font, height, {a.x + pad, a.y + pad}, IM_COL32(235, 235, 222, 255), text);
}

// Keep the real widgets for editing/navigation; draw their original-game art underneath.
struct MenuRow {
    ImDrawList* draw = ImGui::GetWindowDrawList();
    ImDrawListSplitter layers;
    ImVec2 a, b;
    bool selected = false;
    MenuRow(const char* text, float y, float scale) {
        text = language::Text(text);
        const auto pos = ImGui::GetWindowPos();
        a = {pos.x + 70 * scale, pos.y + y * scale - ImGui::GetScrollY()};
        b = {pos.x + 925 * scale, a.y + 46 * scale};
        const auto* window = ImGui::GetCurrentWindow();
        const auto& nav = window->NavRectRel[0];
        const float nav_y = pos.y + nav.GetCenter().y;
        selected = (ImGui::IsWindowHovered() && ImGui::IsMouseHoveringRect(a, b)) ||
            (GImGui->NavWindow == window && GImGui->NavId && nav_y >= a.y && nav_y < b.y);
        layers.Split(draw, 2); layers.SetCurrentChannel(draw, 1);
        ImGui::SetCursorPos({88 * scale, (y + 9) * scale});
        const float font_scale = ImGui::GetCurrentWindow()->FontWindowScale;
        const float available = 330 * scale;
        ImGui::SetWindowFontScale(font_scale * .875f);
        const float width = ImGui::CalcTextSize(text).x;
        if (width > available) ImGui::SetWindowFontScale(font_scale * .875f * available / width);
        ImGui::TextUnformatted(text);
        ImGui::SetWindowFontScale(font_scale);
        ImGui::SameLine(430 * scale);
        ImGui::SetNextItemWidth(470 * scale);
    }
    ~MenuRow() {
        layers.SetCurrentChannel(draw, 0);
        skin::Row(draw, a, b, selected);
        if (ImGui::GetStyle().Alpha < 1)
            draw->AddRectFilled(a, b, IM_COL32(0, 0, 0, int((1 - ImGui::GetStyle().Alpha) * 255)));
        layers.Merge(draw);
    }
};

bool MenuButton(const char* text, ImVec2 size = {}, bool navigation_selected = false) {
    const char* translated = language::Text(text);
    const std::string label = std::string(translated) + "###" + text;
    text = label.c_str();
    auto* draw = ImGui::GetWindowDrawList();
    ImDrawListSplitter layers; layers.Split(draw, 2); layers.SetCurrentChannel(draw, 1);
    ImGui::PushStyleColor(ImGuiCol_Button, {0,0,0,0});
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, {0,0,0,0});
    ImGui::PushStyleColor(ImGuiCol_ButtonActive, {0,0,0,0});
    const float font_scale = ImGui::GetCurrentWindow()->FontWindowScale;
    const float available = size.x < 0 ? ImGui::GetContentRegionAvail().x : size.x;
    const float text_width = ImGui::CalcTextSize(text, nullptr, true).x;
    if (available > 0 && text_width > available - 20)
        ImGui::SetWindowFontScale(font_scale * std::max(.65f, (available - 20) / text_width));
    const bool pressed = ImGui::Button(text, size);
    ImGui::SetWindowFontScale(font_scale);
    const auto a = ImGui::GetItemRectMin(), b = ImGui::GetItemRectMax();
    const bool selected = navigation_selected || ImGui::IsItemHovered(ImGuiHoveredFlags_NoNavOverride) ||
        (!(GImGui->CurrentItemFlags & ImGuiItemFlags_NoNav) && ImGui::IsItemFocused()) || ImGui::IsItemActive();
    layers.SetCurrentChannel(draw, 0); skin::Row(draw, a, b, selected);
    if (ImGui::GetStyle().Alpha < 1)
        draw->AddRectFilled(a, b, IM_COL32(0, 0, 0, int((1 - ImGui::GetStyle().Alpha) * 255)));
    layers.Merge(draw); ImGui::PopStyleColor(3);
    return pressed;
}

void Hint(const char* text) {
    const float font_scale = ImGui::GetCurrentWindow()->FontWindowScale;
    ImGui::SetWindowFontScale(font_scale * .75f);
    ImGui::PushTextWrapPos(912 * std::max(.5f, std::min(ImGui::GetIO().DisplaySize.x / 1280.f,
                                                    ImGui::GetIO().DisplaySize.y / 720.f)));
    ImGui::TextDisabled("%s", language::Text(text));
    ImGui::PopTextWrapPos(); ImGui::SetWindowFontScale(font_scale);
}

std::string BindingLabel(uint32_t key) {
    switch (key) {
        case VK_LEFT: return "\xE2\x86\x90";
        case VK_UP: return "\xE2\x86\x91";
        case VK_RIGHT: return "\xE2\x86\x92";
        case VK_DOWN: return "\xE2\x86\x93";
        default: return ControlsKeyName(key);
    }
}

bool Choice(const char* id, int* selected, const char* english) {
    if (!language::Spanish()) return ImGui::Combo(id, selected, english);
    std::string choices;
    for (const char* item = english; *item; item += std::strlen(item) + 1) {
        choices += language::Text(item); choices += '\0';
    }
    choices += '\0';
    return ImGui::Combo(id, selected, choices.c_str());
}

void Toggle(const char* id, bool& value) {
    int selected = value ? 1 : 0;
    if (Choice(id, &selected, "Off\0On\0")) value = selected != 0;
}

void PadNavigation() {
    auto& io = ImGui::GetIO();
    uint32_t p = g_coop_owner.load() ? 0 : g_pad.load();
    static uint32_t previous = 0;
    // ImGui consumes queued B at NewFrame, before this page can inspect its popup/widget.
    if ((p & 32) && !(previous & 32))
        g_gamepad_back_consumed = GImGui->ActiveId != 0 || !GImGui->OpenPopupStack.empty();
    if (p && p != previous) {
        GImGui->NavDisableHighlight = false;
        GImGui->NavDisableMouseHover = true;
    }
    previous = p;
    constexpr ImGuiKey keys[] = {ImGuiKey_GamepadDpadUp, ImGuiKey_GamepadDpadDown,
        ImGuiKey_GamepadDpadLeft, ImGuiKey_GamepadDpadRight, ImGuiKey_GamepadFaceDown,
        ImGuiKey_GamepadFaceRight};
    for (unsigned i = 0; i < std::size(keys); ++i) io.AddKeyEvent(keys[i], (p & (1u << i)) != 0);
    io.BackendFlags |= ImGuiBackendFlags_HasGamepad;
}

bool GamepadBack() {
    return ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight, false) && !g_gamepad_back_consumed;
}

void EndSettingsChild() {
    // EndChild checks its style-stack balance; hide only the container decoration.
    auto& color = ImGui::GetStyle().Colors[ImGuiCol_NavHighlight];
    const float alpha = color.w; color.w = 0;
    ImGui::EndChild();
    color.w = alpha;
}

void ControllerSymbol(ImDrawList* draw, ImVec2 center, float scale, ControllerPrompt prompt) {
    const auto color = IM_COL32(240, 240, 232, 255);
    const float radius = 10 * scale, stroke = 2 * scale;
    auto line = [&](float x1, float y1, float x2, float y2) {
        draw->AddLine({center.x + x1 * radius, center.y + y1 * radius},
                      {center.x + x2 * radius, center.y + y2 * radius}, color, stroke);
    };
    using Symbol = ControllerPromptSymbol;
    switch (prompt.symbol) {
        case Symbol::Cross: line(-1,-1,1,1); line(-1,1,1,-1); break;
        case Symbol::Circle: draw->AddCircle(center, radius, color, 24, stroke); break;
        case Symbol::Square:
            draw->AddRect({center.x-radius,center.y-radius}, {center.x+radius,center.y+radius}, color, 0, 0, stroke); break;
        case Symbol::Triangle:
            draw->AddTriangle({center.x,center.y-radius}, {center.x+radius,center.y+radius},
                              {center.x-radius,center.y+radius}, color, stroke); break;
        case Symbol::Plus: line(-1,0,1,0); line(0,-1,0,1); break;
        case Symbol::Minus: line(-1,0,1,0); break;
        case Symbol::Up: line(0,1,0,-1); line(-.7f,-.3f,0,-1); line(.7f,-.3f,0,-1); break;
        case Symbol::Down: line(0,-1,0,1); line(-.7f,.3f,0,1); line(.7f,.3f,0,1); break;
        case Symbol::Left: line(1,0,-1,0); line(-.3f,-.7f,-1,0); line(-.3f,.7f,-1,0); break;
        case Symbol::Right: line(-1,0,1,0); line(.3f,-.7f,1,0); line(.3f,.7f,1,0); break;
        case Symbol::LeftStick: case Symbol::RightStick:
        case Symbol::LeftStickPress: case Symbol::RightStickPress:
            draw->AddCircle(center, radius * 1.25f, color, 24, stroke);
            if (prompt.symbol == Symbol::LeftStickPress || prompt.symbol == Symbol::RightStickPress) {
                line(1.7f,-.7f,1.7f,.7f); line(1.3f,.3f,1.7f,.7f); line(2.1f,.3f,1.7f,.7f);
            }
            break;
        default: break;
    }
    if (*prompt.label) {
        auto* font = ImGui::GetFont();
        const float size = 18 * scale;
        const auto extent = font->CalcTextSizeA(size, FLT_MAX, 0, prompt.label);
        draw->AddText(font, size, {center.x-extent.x/2,center.y-extent.y/2}, color, prompt.label);
    }
}

void ControllerLayoutContent(float scale) {
    // A captured button must never also activate the newly revealed footer.
    const bool capturing = g_pad_capture_action >= 0;
    if (capturing) {
        const auto result = input::TakePadCapture();
        if (result) {
            if (result <= 16) {
                auto old = std::find(g_pad_draft.begin(), g_pad_draft.end(), uint8_t(result - 1));
                if (old != g_pad_draft.end()) std::swap(*old, g_pad_draft[g_pad_capture_action]);
                g_notice = "Buttons swapped in this draft. Apply from Controls to save.";
            }
            g_pad_binding_focus = g_pad_capture_action;
            g_pad_capture_action = -1;
            g_released = false; g_pad = 0;
        }
    }
    const auto device = input::GetLastDevice();
    if (PlayerTwoControls()) g_layout_family = input::GetControllerFamily(g_original_draft.input_port);
    else if (device.controller) g_layout_family = device.family;
    ImGui::SetCursorPos({88 * scale, 119 * scale});
    ImGui::SetWindowFontScale(.75f);
    ImGui::TextUnformatted(language::Text(g_layout_family == input::ControllerFamily::PlayStation ? "PLAYSTATION CONTROLLER" :
                          g_layout_family == input::ControllerFamily::Switch ? "SWITCH CONTROLLER" : "XBOX CONTROLLER"));
    ImGui::SameLine(500 * scale); ImGui::SetNextItemWidth(400 * scale);
    ImGui::BeginDisabled(capturing || !g_original_draft.controls_available);
    if (g_layout_opened) {ImGui::SetKeyboardFocusHere(); g_layout_opened = false;}
    Choice("##controller preset", &g_original_draft.controller_preset, "Default\0Chieftain\0Lefty\0Hopalong\0Hoss\0");
    ImGui::EndDisabled(); ImGui::SetWindowFontScale(1);
    ImGui::SetCursorPos({0, 160 * scale});
    ImGui::BeginChild("Controller layout scroll", {938 * scale, 280 * scale}, ImGuiChildFlags_NavFlattened);
    ImGui::BeginDisabled(capturing);
    constexpr unsigned order[]{8,9,10,11,14,15,13,12,6,7,0,1,2,3,4,5,16,17};
    for (unsigned index : order) {
        const bool stick = index >= 16;
        const bool left = index == 16;
        const bool look = (g_original_draft.controller_preset == 2) == left;
        auto prompt = stick ? ControllerPrompt{left ? "L" : "R", left ? ControllerPromptSymbol::LeftStick : ControllerPromptSymbol::RightStick}
                            : ControllerPromptInfo(g_layout_family, input::PcAction(g_pad_draft[index]));
        const char* name = stick ? (look ? "LOOK / AIM" : "MOVE") : ActionName(index);
        const char* description = stick ? "Move the stick in the direction you want to go."
                                        : ActionDescription(index);
        if (stick && look) description = "Turn and aim with this stick.";
        if (!KnownPreset()) {
            name = stick ? (left ? "LEFT STICK" : "RIGHT STICK") : "BUTTON ACTION";
            description = "Choose a known layout to see this action.";
        }
        ImGui::PushID(int(index)); ImGui::SetCursorPosX(70 * scale);
        auto* draw = ImGui::GetWindowDrawList();
        ImDrawListSplitter layers; layers.Split(draw, 2); layers.SetCurrentChannel(draw, 1);
        if (!capturing && g_pad_binding_focus == int(index)) {ImGui::SetKeyboardFocusHere(); g_pad_binding_focus = -1;}
        if (ImGui::Selectable("##layout row", false, ImGuiSelectableFlags_NoPadWithHalfSpacing |
                (stick ? ImGuiSelectableFlags_Disabled : 0), {ImGui::GetContentRegionAvail().x, 52 * scale}) && !stick) {
            ControlsCancelCapture();
            if (input::BeginPadCapture(ControlsPort())) {
                g_pad_capture_action = int(index); g_notice = "";
                g_released = false; g_pad = 0;
            } else g_notice = "Connect this player's controller to change buttons.";
        }
        const auto a = ImGui::GetItemRectMin(), b = ImGui::GetItemRectMax();
        const bool selected = ImGui::IsItemHovered() || ImGui::IsItemFocused();
        ControllerSymbol(draw, {a.x + 79 * scale, (a.y + b.y) / 2}, scale, prompt);
        const auto next = ImGui::GetCursorPos();
        ImGui::SetCursorScreenPos({a.x + 158 * scale, a.y + 6 * scale}); ImGui::SetWindowFontScale(.75f);
        ImGui::TextUnformatted(language::Text(name));
        ImGui::SetCursorScreenPos({a.x + 158 * scale, a.y + 28 * scale}); ImGui::SetWindowFontScale(.6f);
        ImGui::TextDisabled("%s", language::Text(description));
        ImGui::SetWindowFontScale(1); ImGui::SetCursorPos(next);
        layers.SetCurrentChannel(draw, 0); skin::Row(draw, a, b, selected); layers.Merge(draw);
        ImGui::PopID();
    }
    ImGui::EndDisabled(); EndSettingsChild();
    ImGui::SetCursorPos({220 * scale, 455 * scale});
    Hint(capturing ? "Press a controller button. Start + Back or Escape cancels."
                   : "Select an action to change its button. Menu buttons stay unchanged.");
    ImGui::SetCursorPos({220 * scale, 490 * scale}); Hint(g_notice);
    if (capturing) {
        ImGui::SetCursorPos({720 * scale, 542 * scale});
        if (MenuButton("CANCEL", {192 * scale, 39 * scale}) || ImGui::IsKeyPressed(ImGuiKey_Escape, false) ||
            ImGui::IsMouseClicked(ImGuiMouseButton_Right)) {
            g_pad_binding_focus = g_pad_capture_action;
            input::CancelPadCapture(); g_pad_capture_action = -1;
            g_released = false; g_pad = 0;
        }
        return;
    }
    ImGui::SetCursorPos({220 * scale, 542 * scale});
    if (MenuButton("RESET BUTTONS", {300 * scale, 39 * scale})) {
        g_pad_draft = input::DefaultPadBindings();
        g_notice = "Controller buttons reset in this draft. Apply from Controls to save.";
    }
    ImGui::SetCursorPos({720 * scale, 542 * scale});
    bool back = MenuButton("BACK", {192 * scale, 39 * scale});
    if (back || ImGui::IsKeyPressed(ImGuiKey_Escape, false) || GamepadBack() ||
        ImGui::IsMouseClicked(ImGuiMouseButton_Right)) {g_controller_layout = false; g_layout_returned = true;}
}

void ControlsContent(float scale, bool just_opened) {
    const bool player_two = PlayerTwoControls();
    // Keep the capture frame isolated even if the window thread just published its result.
    bool capturing = g_capture_action >= 0 && g_conflict_action < 0;
    if (capturing && ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight, false)) {
        g_binding_focus = g_capture_action * 2 + g_capture_slot;
        ControlsCancelCapture(); g_capture_action = -1; g_notice = "";
    }
    CaptureBinding();
    ImGui::SetCursorPos({0, 132 * scale});
    ImGui::BeginChild("Controls scroll", {938 * scale, 308 * scale}, ImGuiChildFlags_NavFlattened);
    ImGui::BeginDisabled(capturing || g_conflict_action >= 0);
    if (!player_two) {
    { MenuRow row("MOUSE SENSITIVITY", 8, scale);
      float sensitivity = g_controls_draft.mouse_millidegrees / 50.f;
      if (ImGui::SliderFloat("##mouse sensitivity", &sensitivity, .02f, 20.f, "%.2fx", ImGuiSliderFlags_AlwaysClamp | ImGuiSliderFlags_Logarithmic))
          g_controls_draft.mouse_millidegrees = uint32_t(std::lround(sensitivity * 50.f));
      if (just_opened) ImGui::SetItemDefaultFocus(); }
    { MenuRow row("ZOOM SENSITIVITY", 64, scale);
      int zoom = int(g_controls_draft.zoom_sensitivity_percent);
      if (ImGui::SliderInt("##zoom sensitivity", &zoom, 10, 200, "%d%%", ImGuiSliderFlags_AlwaysClamp))
          g_controls_draft.zoom_sensitivity_percent = uint32_t(zoom);
      if (ImGui::IsItemHovered()) ImGui::SetTooltip(language::Text("Mouse speed while zoomed. 100%% keeps your normal speed."));
    }
    { MenuRow row("AIMING ASSISTANCE", 120, scale); Toggle("##aim assistance", g_controls_draft.aim_assistance); }
    { MenuRow row("LOOK CENTERING", 176, scale); Toggle("##look centering", g_controls_draft.aim_centering); }
    ImGui::SetCursorPos({88 * scale, 232 * scale});
    ImGui::PushTextWrapPos(900 * scale);
    Hint("Aiming assistance attracts the view near targets. Look centering recenters your view.");
    ImGui::PopTextWrapPos();
    }
    const float controller_y = player_two ? 8.f : 292.f;
    ImGui::BeginDisabled(!g_original_draft.controls_available);
    { MenuRow row("INVERT LOOK", controller_y, scale); Toggle("##invert look", g_original_draft.invert);
      if (player_two && just_opened) ImGui::SetItemDefaultFocus(); }
    { MenuRow row("PAD VIBRATION", controller_y + 56, scale); Toggle("##vibration", g_original_draft.vibration); }
    { MenuRow row("PAD SENSITIVITY", controller_y + 112, scale);
      ImGui::SliderInt("##controller sensitivity", &g_original_draft.sensitivity,
                      g_original_draft.sensitivity_min, g_original_draft.sensitivity_max); }
    ImGui::EndDisabled();
    ImGui::SetCursorPos({88 * scale, (controller_y + 172) * scale});
    if (!g_original_draft.controls_available) ImGui::TextDisabled(language::Text("Original settings are unavailable on this page."));
    if (g_layout_returned) {ImGui::SetKeyboardFocusHere(); g_layout_returned = false;}
    if (MenuButton("CONTROLLER LAYOUT...")) {
        ControlsCancelCapture(); g_capture_action = -1;
        const auto device = input::GetLastDevice();
        const auto family = player_two ? input::GetControllerFamily(g_original_draft.input_port) :
            device.controller ? device.family : input::GetControllerFamily(0);
        g_layout_family = family;
        g_controller_layout = g_layout_opened = true;
        g_released = false; g_pad = 0;
    }
    if (KnownPreset()) {ImGui::SameLine(); ImGui::TextDisabled(language::Text("Current: %s"), language::Text(kPresetNames[g_original_draft.controller_preset]));}
    if (player_two) {
        ImGui::SetCursorPos({88 * scale, 240 * scale});
        ImGui::PushTextWrapPos(900 * scale);
        Hint("Player 2 settings. Use Controller Layout to change buttons.");
        ImGui::PopTextWrapPos();
    } else {
    ImGui::SetCursorPos({88 * scale, 530 * scale});
    ImGui::BeginGroup(); ImGui::PushTextWrapPos(912 * scale);
    ImGui::TextUnformatted(language::Text("KEYBOARD AND MOUSE BINDINGS"));
    Hint("Select a binding, then press a key, mouse button, or scroll the wheel. Escape cancels; Backspace clears.");
    if (ImGui::BeginTable("Bindings", 3, ImGuiTableFlags_SizingFixedFit | ImGuiTableFlags_RowBg, {824 * scale, 0})) {
        ImGui::TableSetupColumn(language::Text("ACTION"), ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn(language::Text("PRIMARY"), ImGuiTableColumnFlags_WidthFixed, 180 * scale);
        ImGui::TableSetupColumn(language::Text("ALT KEY"), ImGuiTableColumnFlags_WidthFixed, 180 * scale);
        ImGui::TableHeadersRow();
        constexpr unsigned order[]{16,17,18,19,15,14,8,9,10,11,12,13,6,7,4,5,0,1,2,3};
        for (unsigned action : order) {
            ImGui::PushID(int(action)); ImGui::TableNextRow(); ImGui::TableNextColumn();
            ImGui::PushTextWrapPos(0); ImGui::TextUnformatted(language::Text(ActionName(action)));
            const float row_font_scale = ImGui::GetCurrentWindow()->FontWindowScale;
            ImGui::SetWindowFontScale(row_font_scale * .75f);
            ImGui::TextDisabled("%s", language::Text(ActionDescription(action)));
            ImGui::SetWindowFontScale(row_font_scale); ImGui::PopTextWrapPos();
            for (int slot = 0; slot < 2; ++slot) {
                ImGui::TableNextColumn(); ImGui::PushID(slot);
                auto label = BindingLabel(g_controls_draft.bindings[action].keys[slot]);
                bool waiting = capturing && g_capture_action == int(action) && g_capture_slot == slot;
                if (!capturing && g_conflict_action < 0 && g_binding_focus == int(action) * 2 + slot) {
                    ImGui::SetKeyboardFocusHere(); g_binding_focus = -1;
                }
                if (MenuButton(waiting ? "PRESS A KEY..." : label.c_str(), {-1, 38 * scale})) {
                    g_capture_action = int(action); g_capture_slot = slot; g_conflict_action = -1;
                    g_notice = "Press a key, mouse button, or scroll the wheel. Escape cancels; Backspace clears.";
                    ControlsBeginCapture();
                }
                ImGui::PopID();
            }
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
    ImGui::PopTextWrapPos(); ImGui::EndGroup();
    }
    ImGui::EndDisabled(); EndSettingsChild();
    if (g_conflict_action >= 0) {
        ImGui::SetCursorPos({220 * scale, 490 * scale});
        char conflict[256];
        std::snprintf(conflict, sizeof(conflict), language::Text("%s is assigned to %s. Replace that assignment?"),
                      language::Text(BindingLabel(g_capture_key).c_str()), language::Text(ActionName(unsigned(g_conflict_action))));
        Hint(conflict);
        ImGui::SetCursorPos({220 * scale, 541 * scale});
        ImGui::BeginDisabled(capturing);
        if (MenuButton("REPLACE", {260 * scale, 39 * scale})) ReplaceBinding();
        ImGui::SameLine(650 * scale);
        if (MenuButton("CANCEL", {260 * scale, 39 * scale}) || (!capturing &&
            (ImGui::IsKeyPressed(ImGuiKey_Escape, false) || ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight, false) ||
             ImGui::IsMouseClicked(ImGuiMouseButton_Right))))
            {
                if (ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight, false))
                    g_binding_focus = g_capture_action * 2 + g_capture_slot;
                g_capture_action = -1; g_conflict_action = -1;
            }
        ImGui::EndDisabled();
        return;
    }
    ImGui::SetCursorPos({220 * scale, 490 * scale});
    Hint(g_notice);
    ImGui::SetCursorPos({220 * scale, 541 * scale});
    ImGui::BeginDisabled(capturing || g_conflict_action >= 0);
    if (MenuButton("APPLY", {200 * scale, 39 * scale})) ApplyControls();
    if (!player_two) {
        ImGui::SameLine(450 * scale);
        if (MenuButton("RESET DEFAULTS", {250 * scale, 39 * scale})) {
            g_controls_draft = ControlsDefaults(); g_notice = "PC defaults restored in this draft. Select Apply to save.";
        }
    }
    ImGui::SameLine(720 * scale);
    if (MenuButton("BACK", {192 * scale, 39 * scale})) Close();
    ImGui::EndDisabled();
    if (!capturing && g_conflict_action < 0 &&
        (ImGui::IsKeyPressed(ImGuiKey_Escape, false) || GamepadBack() ||
         ImGui::IsMouseClicked(ImGuiMouseButton_Right))) Close();
}

void AudioContent(float scale, bool just_opened) {
    if (g_audio_apply_failed.exchange(false)) g_notice = "Could not apply audio settings. Reopen Audio and try again.";
    ImGui::SetCursorPos({0, 132 * scale});
    ImGui::BeginChild("Audio scroll", {938 * scale, 308 * scale}, ImGuiChildFlags_NavFlattened);
    ImGui::BeginDisabled(!g_original_draft.audio_available);
    { MenuRow row("MUSIC VOLUME", 8, scale);
      if (just_opened || g_audio_focus) {ImGui::SetKeyboardFocusHere(); g_audio_focus = false;}
      ImGui::SliderInt("##music", &g_audio_draft.music, 0, 100, "%d%%", ImGuiSliderFlags_AlwaysClamp | ImGuiSliderFlags_NoInput); }
    { MenuRow row("EFFECTS VOLUME", 64, scale);
      ImGui::SliderInt("##effects", &g_audio_draft.effects, 0, 100, "%d%%", ImGuiSliderFlags_AlwaysClamp | ImGuiSliderFlags_NoInput); }
    { MenuRow row("SPEECH VOLUME", 120, scale);
      ImGui::SliderInt("##speech", &g_audio_draft.speech, 0, 100, "%d%%", ImGuiSliderFlags_AlwaysClamp | ImGuiSliderFlags_NoInput); }
    ImGui::EndDisabled();
    { MenuRow row("SOUND OUTPUT", 176, scale);
      int output = g_surround_draft ? 1 : 0;
      if (Choice("##sound output", &output, "Stereo\0Surround\0")) g_surround_draft = output != 0; }
    ImGui::SetCursorPos({88 * scale, 236 * scale});
    Hint(audio::SurroundAvailable() ? "Surround uses your device's 5.1 or 7.1 speakers."
        : "Surround unavailable. Set up 5.1 or 7.1 speakers, then restart.");
    EndSettingsChild();
    ImGui::SetCursorPos({220 * scale, 490 * scale}); Hint(g_notice);
    ImGui::SetCursorPos({220 * scale, 541 * scale});
    if (MenuButton("APPLY", {200 * scale, 39 * scale})) {
        if (g_original_draft.audio_available) {
            std::lock_guard lock(g_original_lock);
            g_audio_request = {g_options, g_audio_draft};
        }
        audio::SetSurroundEnabled(g_surround_draft);
        g_notice = app::Save() ? "Audio applied. Profile volumes save when you leave Options."
                              : "Could not save settings. Changes will last for this session only.";
    }
    ImGui::SameLine(450 * scale);
    if (MenuButton("RESET DEFAULTS", {250 * scale, 39 * scale})) {
        g_audio_draft = {}; g_surround_draft = false;
        g_notice = "Audio defaults restored in this draft. Select Apply to save.";
    }
    ImGui::SameLine(720 * scale);
    if (MenuButton("BACK", {192 * scale, 39 * scale}) || ImGui::IsKeyPressed(ImGuiKey_Escape, false) ||
        GamepadBack() || ImGui::IsMouseClicked(ImGuiMouseButton_Right)) {
        if (g_pause_audio) {g_pause_audio = false; g_audio_returned = true; g_notice = ""; g_released = false; g_pad = 0;}
        else Close();
    }
}

void CoopContent(float scale, bool just_opened, const CoopSetupState& state) {
    const auto& io = ImGui::GetIO();
    if (!just_opened && !io.MouseDown[0] && !ImGui::IsKeyDown(ImGuiKey_Enter) &&
        !ImGui::IsKeyDown(ImGuiKey_KeypadEnter) && !ImGui::IsKeyDown(ImGuiKey_Space) &&
        !ImGui::IsKeyDown(ImGuiKey_GamepadFaceDown)) g_coop_ui_ready = true;
    if (g_coop_failed.exchange(false)) g_notice = "Could not change co-op selection. Try again.";
    const auto position = ImGui::GetWindowPos();
    auto* draw = ImGui::GetWindowDrawList();
    // Cover the retained native settings; their profile/Ready flow still owns this page.
    draw->AddRectFilled({position.x + 68 * scale, position.y + 120 * scale},
                       {position.x + 925 * scale, position.y + 525 * scale}, IM_COL32(12, 13, 15, 255));
    draw->AddLine({position.x + 495 * scale, position.y + 132 * scale},
                  {position.x + 495 * scale, position.y + 475 * scale}, IM_COL32(95, 96, 95, 255));
    // ImGui has one navigation cursor. The co-op page needs one per player.
    ImGui::PushItemFlag(ImGuiItemFlags_NoNav, true);
    for (unsigned player = 0; player < 2; ++player) {
        bool pending;
        {std::lock_guard lock(g_original_lock); pending = g_coop_requests[player].owner != 0;}
        const float x = player ? 510.f : 80.f;
        ImGui::PushID(int(player));
        auto centered = [&](const char* text, float y, float font_scale) {
            ImGui::SetWindowFontScale(font_scale);
            const char* translated = language::Text(text);
            const float width = ImGui::CalcTextSize(translated).x;
            if (width > 390 * scale) ImGui::SetWindowFontScale(font_scale * 390 * scale / width);
            ImGui::SetCursorPos({(x + 200) * scale - ImGui::CalcTextSize(translated).x / 2, y * scale});
            ImGui::TextUnformatted(translated); ImGui::SetWindowFontScale(1);
        };
        centered(player ? "PLAYER TWO" : "PLAYER ONE", 133, .8f);
        if (just_opened || g_coop_preview_characters[player] != state.characters[player]) {
            g_coop_preview_characters[player] = state.characters[player];
            g_coop_preview_started[player] = ImGui::GetTime();
        }
        if (!preview::Draw(state.characters[player], {position.x + (x + 25) * scale, position.y + 170 * scale},
                {position.x + (x + 375) * scale, position.y + 365 * scale},
                ImGui::GetTime() - g_coop_preview_started[player], view::Snapshot().hd_textures))
            centered("Preview unavailable.", 268, .6f);
        centered(settings::CharacterName(state.characters[player]), 370, .72f);
        auto pressed = g_coop_pressed[player].exchange(0);
        if (!player && g_coop_ui_ready) {
            for (const auto [key, bit] : {std::pair{ImGuiKey_UpArrow, 1u}, {ImGuiKey_DownArrow, 2u},
                    {ImGuiKey_LeftArrow, 4u}, {ImGuiKey_RightArrow, 8u}, {ImGuiKey_Enter, 16u},
                    {ImGuiKey_KeypadEnter, 16u}, {ImGuiKey_Space, 16u}, {ImGuiKey_Escape, 32u}})
                if (ImGui::IsKeyPressed(key, false)) pressed |= bit;
        }
        CoopRequest request;
        const bool editable = g_coop_ui_ready && state.connected[player] && !pending;
        const bool character_editable = !state.ready[player] && state.character_available;
        auto& focus = g_coop_focus[player];
        if (just_opened) focus = 0;
        if (!character_editable) focus = 2;
        if (editable) {
            if ((pressed & 1) && character_editable) focus = 0;
            if (pressed & 2) focus = 2;
            if (focus < 2 && character_editable) {
                if (pressed & 4) focus = 0;
                if (pressed & 8) focus = 1;
            }
        }
        ImGui::BeginDisabled(!editable || state.ready[player] || !state.character_available);
        ImGui::SetCursorPos({x * scale, 400 * scale});
        int step = 0;
        if (MenuButton("PREVIOUS", {190 * scale, 36 * scale}, character_editable && focus == 0)) {step = -1; focus = 0;}
        ImGui::SameLine((x + 210) * scale);
        if (MenuButton("NEXT", {190 * scale, 36 * scale}, character_editable && focus == 1)) {step = 1; focus = 1;}
        ImGui::EndDisabled();
        if (editable && character_editable) {
            if ((pressed & 16) && focus < 2) step = focus == 0 ? -1 : 1;
            if (step) request.character = (int(state.characters[player]) + step + int(settings::kCharacterCount)) % int(settings::kCharacterCount);
        }
        ImGui::BeginDisabled(!editable);
        ImGui::SetCursorPos({(x + 60) * scale, 442 * scale});
        const bool ready = MenuButton(state.ready[player] ? "CANCEL READY" : "READY", {280 * scale, 36 * scale}, focus == 2);
        ImGui::EndDisabled();
        if (editable && (ready || ((pressed & 16) && focus == 2))) {request.ready = state.ready[player] ? 0 : 1; focus = 2;}
        if (editable && (pressed & 32)) {request = {}; request.back = true;}
        if (!state.connected[player]) centered("CONNECT CONTROLLER", 485, .5f);
        else {
            const float hint_y = player ? 485.f : 482.f;
            ImGui::SetWindowFontScale(.42f);
            ImGui::SetCursorPos({(x + 12) * scale, hint_y * scale}); ImGui::TextUnformatted(language::Text("D-PAD: MOVE"));
            const auto family = input::GetControllerFamily(int(player));
            ControllerSymbol(draw, {position.x + (x + 185) * scale, position.y + (hint_y + 7) * scale}, .6f * scale,
                             ControllerPromptInfo(family, input::PcAction::A));
            ImGui::SetCursorPos({(x + 200) * scale, hint_y * scale}); ImGui::TextUnformatted(language::Text("SELECT"));
            ControllerSymbol(draw, {position.x + (x + 300) * scale, position.y + (hint_y + 7) * scale}, .6f * scale,
                             ControllerPromptInfo(family, input::PcAction::B));
            ImGui::SetCursorPos({(x + 315) * scale, hint_y * scale}); ImGui::TextUnformatted(language::Text("BACK"));
            ImGui::SetWindowFontScale(1);
            if (!player) centered("ARROWS: MOVE   ENTER: SELECT   ESC: BACK", 497, .38f);
        }
        if (request.character >= 0 || request.ready >= 0 || request.back) {
            g_notice = "";
            request.owner = state.owner;
            std::lock_guard lock(g_original_lock); g_coop_requests[player] = request;
        }
        ImGui::PopID();
    }
    draw->AddRectFilled({position.x + 210 * scale, position.y + 535 * scale},
                        {position.x + 705 * scale, position.y + 580 * scale}, IM_COL32(12, 13, 15, 255));
    ImGui::SetCursorPos({220 * scale, 539 * scale});
    ImGui::SetWindowFontScale(.6f);
    ImGui::PushTextWrapPos(700 * scale);
    ImGui::TextUnformatted(language::Text(*g_notice ? g_notice : "Both players ready to continue."));
    ImGui::PopTextWrapPos();
    ImGui::SetWindowFontScale(1);
    ImGui::SetCursorPos({720 * scale, 541 * scale});
    if (g_coop_ui_ready && (MenuButton("BACK", {192 * scale, 39 * scale}) ||
        ImGui::IsMouseClicked(ImGuiMouseButton_Right))) {
        std::lock_guard lock(g_original_lock); g_coop_requests[0] = {state.owner, -1, -1, true};
    }
    ImGui::PopItemFlag();
}

void CharactersContent(float scale, bool just_opened) {
    const auto& io = ImGui::GetIO();
    if (!just_opened && g_released && !io.MouseDown[0] &&
        !ImGui::IsKeyDown(ImGuiKey_Enter) && !ImGui::IsKeyDown(ImGuiKey_KeypadEnter) &&
        !ImGui::IsKeyDown(ImGuiKey_Space) && !ImGui::IsKeyDown(ImGuiKey_GamepadFaceDown))
        g_character_ready = true;
    const auto position = ImGui::GetWindowPos();
    if (!preview::Draw(g_character_draft, {position.x + 100 * scale, position.y + 125 * scale},
            {position.x + 450 * scale, position.y + 450 * scale},
            ImGui::GetTime() - g_character_preview_started, view::Snapshot().hd_textures)) {
        ImGui::SetCursorPos({110 * scale, 285 * scale});
        ImGui::PushTextWrapPos(430 * scale);
        ImGui::SetWindowFontScale(.65f);
        ImGui::TextWrapped("%s", language::Text("Preview unavailable. Verify files in the launcher."));
        ImGui::SetWindowFontScale(1);
        ImGui::PopTextWrapPos();
    }
    ImGui::SetCursorPos({500 * scale, 185 * scale});
    ImGui::SetWindowFontScale(.85f);
    const char* name = language::Text(settings::CharacterName(g_character_draft));
    const float name_width = ImGui::CalcTextSize(name).x;
    if (name_width > 390 * scale) ImGui::SetWindowFontScale(.85f * 390 * scale / name_width);
    ImGui::TextUnformatted(name);
    ImGui::SetWindowFontScale(1);
    ImGui::BeginDisabled(!g_character_ready || g_character_choice.load() >= 0);
    ImGui::SetCursorPos({490 * scale, 248 * scale});
    int step = MenuButton("PREVIOUS", {180 * scale, 39 * scale}) ? -1 : 0;
    if (just_opened) ImGui::SetItemDefaultFocus();
    ImGui::SameLine(710 * scale);
    if (MenuButton("NEXT", {180 * scale, 39 * scale})) step = 1;
    if (step) {
        g_character_draft = settings::Character((int(g_character_draft) + step + int(settings::kCharacterCount)) % int(settings::kCharacterCount));
        g_character_preview_started = ImGui::GetTime();
    }
    ImGui::SetCursorPos({490 * scale, 330 * scale});
    Hint("Choose your single-player character.");
    ImGui::SetCursorPos({490 * scale, 385 * scale});
    Hint("Continue to choose a chapter or resume your save.");
    if (g_character_choice.load() == -2) g_notice = "Could not open Single Player. Try again.";
    ImGui::SetCursorPos({220 * scale, 490 * scale}); Hint(g_notice);
    ImGui::SetCursorPos({220 * scale, 541 * scale});
    if (MenuButton("CONTINUE", {230 * scale, 39 * scale})) g_character_choice = int(g_character_draft);
    ImGui::EndDisabled();
    ImGui::SameLine(720 * scale);
    if (MenuButton("BACK", {192 * scale, 39 * scale}) || ImGui::IsKeyPressed(ImGuiKey_Escape, false) ||
        GamepadBack() || ImGui::IsMouseClicked(ImGuiMouseButton_Right)) Close();
}
} // namespace

void DarkwatchCharactersOpen(uint32_t owner) {
    if (!owner) return;
    g_character_choice = -1;
    g_characters_owner = owner;
    g_leave = false; g_visual = true; g_released = false; g_pad = 0;
}

void DarkwatchDesktopQuitOpen(uint32_t owner) {
    if (!owner || g_quit_owner.load() == owner) return;
    g_quit_choice = 0;
    g_quit_owner = owner;
    g_leave = false; g_visual = true; g_released = false; g_pad = 0;
}

void DarkwatchGraphicsInit() {
    std::error_code error;
    if (!std::filesystem::exists(app::ExeDir() / app::kGame.settings, error))
        app::Get().aspect_ratio = app::AspectRatio::Wide16x9;
}

void DarkwatchGraphicsWindow(void* window) {
    auto& io = ImGui::GetIO();
    g_font_scale = 1;
    std::filesystem::path package;
    for (auto dir = app::ExeDir(); !dir.empty();) {
        auto candidate = dir / "assets" / "packfile.pck";
        if (std::filesystem::exists(candidate)) { package = std::move(candidate); break; }
        auto parent = dir.parent_path(); if (parent == dir) break; dir = std::move(parent);
    }
    const auto fonts = skin::Initialize(io.Fonts, app::ExeDir() / "hd-ui.pack", package);
    preview::Initialize(io.Fonts, app::ExeDir() / "character-previews.pack", app::ExeDir() / "gameplay-hd");
    g_body = fonts.body; g_title = fonts.title;
    if (!g_body) { ImFontConfig font; font.SizePixels = 22; g_body = io.Fonts->AddFontDefault(&font); }
    if (!g_title) g_title = g_body;
    MONITORINFOEXW monitor{}; monitor.cbSize = sizeof(monitor);
    if (GetMonitorInfoW(MonitorFromWindow(static_cast<HWND>(window), MONITOR_DEFAULTTOPRIMARY), &monitor)) {
        DEVMODEW mode{}; mode.dmSize = sizeof(mode);
        for (DWORD i = 0; EnumDisplaySettingsW(monitor.szDevice, i, &mode); ++i)
            if (mode.dmBitsPerPel >= 24 && mode.dmPelsWidth >= 640 && mode.dmPelsHeight >= 480 &&
                mode.dmPelsWidth <= 8192 && mode.dmPelsHeight <= 8192)
                g_modes.push_back({mode.dmPelsWidth, mode.dmPelsHeight});
    }
    g_modes.push_back(app::Desktop());
    std::sort(g_modes.begin(), g_modes.end(), [](auto a, auto b) {return a.width == b.width ? a.height < b.height : a.width < b.width;});
    g_modes.erase(std::unique(g_modes.begin(), g_modes.end(), [](auto a, auto b) {return a.width == b.width && a.height == b.height;}), g_modes.end());
}

void DarkwatchCoopSetupRefresh(uint8_t* base) {
    PublishCoopSetup(darkwatch::QueryCoopSetup(base));
}

void DarkwatchGraphicsPad(int port, input::Pad& pad) {
    if (port == 0) {
        darkwatch::EnsureDesktopQuitEntry(mem::Base());
        auto coop = darkwatch::QueryCoopSetup(mem::Base());
        std::array<CoopRequest, 2> coop_requests;
        {std::lock_guard lock(g_original_lock); coop_requests = g_coop_requests; g_coop_requests = {};}
        for (unsigned player = 0; player < 2; ++player) {
            const auto& request = coop_requests[player];
            if (!request.owner) continue;
            bool applied = request.owner == coop.owner;
            if (applied && request.back) applied = BackCoopSetup(mem::Base(), request.owner, player);
            else if (applied) {
                if (request.character >= 0) applied = SetCoopSetupCharacter(mem::Base(), request.owner, player, settings::Character(request.character));
                if (applied && request.ready >= 0) applied = SetCoopSetupReady(mem::Base(), request.owner, player, request.ready != 0);
            }
            if (!applied && request.owner == coop.owner) g_coop_failed = true;
            coop = darkwatch::QueryCoopSetup(mem::Base());
        }
        PublishCoopSetup(coop);
        auto state = darkwatch::QueryGraphicsMenuRoute(mem::Base());
        const auto character_owner = g_characters_owner.load();
        if (character_owner && darkwatch::CharacterMenuOwner(mem::Base()) != character_owner) {
            g_characters_owner = 0;
            g_character_choice = -1;
            g_block_release = true;
        } else if (character_owner) {
            const int choice = g_character_choice.exchange(-1);
            if (choice >= 0 && settings::ValidCharacter(settings::Character(choice))) {
                const auto previous = settings::characters();
                auto selected = previous;
                selected[0] = settings::Character(choice);
                settings::set_characters(selected);
                if (darkwatch::ContinueSinglePlayer(mem::Base(), character_owner)) {
                    if (!app::Save()) g_character_save_failed = true;
                    g_characters_owner = 0;
                    g_block_release = true;
                    state = darkwatch::QueryGraphicsMenuRoute(mem::Base());
                } else {
                    settings::set_characters(previous);
                    g_character_choice = -2;
                }
            } else if (choice == -2) g_character_choice = -2;
        }
        const auto quit_owner = g_quit_owner.load();
        if (quit_owner && darkwatch::CharacterMenuOwner(mem::Base()) != quit_owner) {
            g_quit_owner = 0;
            g_quit_choice = 0;
            g_block_release = true;
        } else if (quit_owner && g_quit_choice.load() == 1) {
            g_quit_choice = darkwatch::ConfirmDesktopQuit(mem::Base(), quit_owner) ? 2 : 3;
        }
        darkwatch::EnsureNativePauseEntries(mem::Base());
        const auto entry = darkwatch::TakeNativePauseEntry(mem::Base(), state.options);
        bool controls = state.route == darkwatch::GraphicsMenuRoute::Controls;
        bool visual = state.route == darkwatch::GraphicsMenuRoute::Visual || state.route == GraphicsMenuRoute::Audio ||
                      controls || g_characters_owner.load() || g_quit_owner.load() || coop.owner;
        const uint32_t owner_port = coop.owner || g_characters_owner.load() || g_quit_owner.load() ? 0 : state.paused ? state.input_port :
            state.route == GraphicsMenuRoute::Hidden ? g_navigation_port.load() : 0;
        if (g_navigation_port.exchange(owner_port) != owner_port) {
            g_pad = 0; g_released = false;
        }
        ControlRequest request;
        AudioRequest audio_request;
        {
            std::lock_guard lock(g_original_lock);
            // Publish the owned entry with its route; keep it across temporary modal pages.
            if (state.route != GraphicsMenuRoute::Hidden &&
                (!controls || !state.paused || state.options != g_pause_owner || state.page != g_pause_page)) {
                g_pause_owner = g_pause_page = g_pause_entry = 0;
            }
            if (controls && state.paused && entry >= 1 && entry <= 2) {
                g_pause_owner = state.options; g_pause_page = state.page; g_pause_entry = entry;
            }
            g_original_controls = state;
            request = g_control_request; g_control_request = {};
            audio_request = g_audio_request; g_audio_request = {};
        }
        g_visual = visual;
        if (audio_request.options && !darkwatch::SetOriginalAudio(mem::Base(), audio_request.options, audio_request.settings))
            g_audio_apply_failed = true;
        if (request.options && controls) {
            if (request.apply) {
                darkwatch::SetOriginalControls(mem::Base(), request.options,
                    request.invert, request.vibration, request.sensitivity);
                darkwatch::SetControllerPreset(mem::Base(), request.options, request.preset);
            }
            if (request.configure) {
                if (!darkwatch::OpenControllerConfiguration(mem::Base(), request.options)) g_configuring = false;
            }
        }
        if (!controls) g_configuring = false;
        uint64_t requested = g_set_subtitles.exchange(0);
        if (requested && visual) darkwatch::SetGraphicsSubtitles(mem::Base(), uint32_t(requested >> 1), (requested & 1) != 0);
        if (g_leave && !visual) g_leave = false;
    }
    if (g_coop_owner && port >= 0 && port < 2) {
        uint32_t keys = (pad.buttons & 15) | (pad.analog[0] ? 16 : 0) | (pad.analog[1] ? 32 : 0);
        if (pad.ly > 16000) keys |= 1;
        if (pad.ly < -16000) keys |= 2;
        if (pad.lx < -16000) keys |= 4;
        if (pad.lx > 16000) keys |= 8;
        if (!keys) g_coop_released[port] = true;
        if (g_coop_released[port]) g_coop_pressed[port].fetch_or(keys & ~g_coop_held[port]);
        g_coop_held[port] = keys;
        const bool connected = pad.connected; pad = {}; pad.connected = connected;
        input::SetActive(false);
        return;
    }
    // Either player may have pressed Ready last; release both before chapter navigation.
    if (port >= 0 && port < 2 && g_coop_block_release[port] && !g_coop_owner) {
        if (!pad.buttons && std::all_of(std::begin(pad.analog), std::end(pad.analog), [](uint8_t value) {return value == 0;}) &&
            std::abs(int(pad.lx)) < 8000 && std::abs(int(pad.ly)) < 8000 &&
            std::abs(int(pad.rx)) < 8000 && std::abs(int(pad.ry)) < 8000) g_coop_block_release[port] = false;
        const bool connected = pad.connected; pad = {}; pad.connected = connected;
        input::SetActive(false);
        return;
    }
    // Only the player who opened Pause drives its host page or receives Back.
    // Port-zero polling still owns guest UI publication and queued mutations.
    if (port == int(g_navigation_port.load())) {
        const bool visual = g_visual.load();
        uint32_t keys = (pad.buttons & 15) | (pad.analog[0] ? 16 : 0) | (pad.analog[1] ? 32 : 0);
        if (pad.ly > 16000) keys |= 1;
        if (pad.ly < -16000) keys |= 2;
        if (pad.lx < -16000) keys |= 4;
        if (pad.lx > 16000) keys |= 8;
        if (visual || g_leave) {
            if (!keys) g_released = true;
            g_pad = g_released ? keys : 0;
        } else { g_pad = 0; g_released = false; }
        if (!visual && g_block_release && !pad.buttons &&
            std::all_of(std::begin(pad.analog), std::end(pad.analog), [](uint8_t value) {return value == 0;}) &&
            std::abs(int(pad.lx)) < 8000 && std::abs(int(pad.ly)) < 8000) g_block_release = false;
    }
    if (g_visual || g_leave || g_block_release) {
        bool connected = pad.connected;
        pad = {}; pad.connected = connected;
        if (port == int(g_navigation_port.load()) && g_leave && g_visual) pad.analog[1] = 255;
        input::SetActive(false);
    }
}

bool DarkwatchGraphicsVisible() {return g_visual && !g_leave && !g_configuring;}
void DarkwatchGraphicsUi(double fps) {
    FpsCounter(fps);
    CharacterNotice();
    PadNavigation();
    GraphicsRouteState state;
    CoopSetupState coop;
    uint32_t pause_entry = 0;
    {
        std::lock_guard lock(g_original_lock);
        state = g_original_controls;
        coop = g_coop_state;
        if (state.paused && state.options == g_pause_owner && state.page == g_pause_page)
            pause_entry = g_pause_entry;
    }
    g_coop = coop.owner != 0;
    g_controls = state.route == GraphicsMenuRoute::Controls;
    g_audio = state.route == GraphicsMenuRoute::Audio;
    g_characters = g_characters_owner.load() != 0;
    g_quit = g_quit_owner.load() != 0;
    g_options = g_coop ? coop.owner : g_characters ? g_characters_owner.load() : state.options;
    g_subtitles_available = state.subtitles_available;
    bool visible = (state.route == GraphicsMenuRoute::Visual || g_controls || g_audio || g_characters || g_quit || g_coop) && !g_leave && !g_configuring;
    if (!visible) {
        if (g_confirm) Revert();
        g_open = false;
        g_pause_audio = false;
        g_controller_layout = false;
        g_layout_returned = false;
        ControlsCancelCapture(); g_capture_action = -1; g_conflict_action = -1;
        g_pad_capture_action = g_pad_binding_focus = -1;
        g_binding_focus = -1;
        ImGui::GetIO().MouseDrawCursor = false;
        ImGui::GetIO().FontGlobalScale = 1 / g_font_scale;
        return;
    }
    bool just_opened = !g_open || g_open_coop != g_coop || g_open_quit != g_quit || g_open_controls != g_controls || g_open_audio != g_audio || g_open_characters != g_characters || g_open_options != g_options ||
                       g_open_page != state.page || g_open_pause_entry != pause_entry;
    if (just_opened) {
        g_controller_layout = false;
        g_layout_returned = false;
        ControlsCancelCapture(); g_capture_action = -1; g_conflict_action = -1;
        g_pad_capture_action = g_pad_binding_focus = -1;
        g_binding_focus = -1;
        if (g_confirm) Revert();
        g_open = true; g_draft = app::Snapshot();
        g_open_characters = g_characters;
        g_open_coop = g_coop; g_coop_ui_ready = false;
        g_open_quit = g_quit; g_quit_ready = false;
        g_open_audio = g_audio; g_pause_audio = false; g_audio_focus = g_audio_returned = false;
        g_audio_draft = state.audio; g_surround_draft = audio::SurroundEnabled();
        if (g_characters) {
            g_character_draft = settings::configured_character(0);
            g_character_preview_started = ImGui::GetTime();
            g_character_ready = false;
        }
        g_view_draft = view::Snapshot();
        const bool returning = g_return_controls_options && g_return_controls_options == g_options &&
                               g_return_controls_page == state.page;
        g_page_graphics = pause_entry == 1;
        g_open_controls = g_controls; g_open_options = g_options;
        g_open_page = state.page; g_open_pause_entry = pause_entry;
        g_subtitles_draft = state.subtitles;
        if (g_controls || g_audio) {
            if (!returning) {
                g_controls_draft = ControlsSnapshot();
                g_pad_draft = input::GetPadBindings(state.paused ? int(state.input_port) : 0);
            }
            g_return_controls_options = 0;
            auto draft = g_original_draft;
            g_original_draft = state;
            if (returning) {
                g_original_draft.invert = draft.invert; g_original_draft.vibration = draft.vibration;
                if (g_original_draft.controls_available)
                    g_original_draft.sensitivity = std::clamp(draft.sensitivity,
                        g_original_draft.sensitivity_min, g_original_draft.sensitivity_max);
            }
        }
        g_notice = "";
    }
    if (g_confirm && ImGui::GetTime() >= g_confirm_until) Revert();
    auto& io = ImGui::GetIO();
    io.MouseDrawCursor = false; // The shared menu cursor is drawn after both original and host pages.
    ImGui::SetNextFrameWantCaptureKeyboard(true);
    ImGui::SetNextFrameWantCaptureMouse(true);
    float scale = std::min(io.DisplaySize.x / 1280.f, io.DisplaySize.y / 720.f);
    scale = std::max(scale, .5f);
    io.FontGlobalScale = scale / g_font_scale;
    ImVec2 size = g_quit ? ImVec2(720 * scale, 360 * scale) : ImVec2(960 * scale, 600 * scale);
    ImVec2 pos((io.DisplaySize.x - size.x) / 2, (io.DisplaySize.y - size.y) / 2);
    ImGui::GetBackgroundDrawList()->AddRectFilled({0, 0}, io.DisplaySize, IM_COL32(4, 6, 10, g_coop ? 255 : 210));
    ImGui::SetNextWindowPos(pos); ImGui::SetNextWindowSize(size);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, {0, 0});
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, {10 * scale, 4 * scale});
    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, 0);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0);
    ImGui::PushStyleVar(ImGuiStyleVar_GrabMinSize, 14 * scale);
    const ImVec4 white(.94f,.94f,.91f,1), red(.55f,.025f,.035f,1);
    ImGui::PushStyleColor(ImGuiCol_Text, white);
    ImGui::PushStyleColor(ImGuiCol_NavHighlight, white);
    ImGui::PushStyleColor(ImGuiCol_WindowBg, {0,0,0,0});
    ImGui::PushStyleColor(ImGuiCol_FrameBg, {.015f,.015f,.015f,.78f});
    ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, {.04f,.015f,.015f,.82f});
    ImGui::PushStyleColor(ImGuiCol_FrameBgActive, {.08f,.01f,.01f,.86f});
    ImGui::PushStyleColor(ImGuiCol_Button, {.22f,.025f,.035f,1});
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, red);
    ImGui::PushStyleColor(ImGuiCol_ButtonActive, {.65f,.04f,.045f,1});
    ImGui::PushStyleColor(ImGuiCol_Header, red);
    ImGui::PushStyleColor(ImGuiCol_HeaderHovered, {.62f,.045f,.05f,1});
    ImGui::PushStyleColor(ImGuiCol_HeaderActive, red);
    ImGui::PushStyleColor(ImGuiCol_PopupBg, {.06f,.07f,.085f,1});
    ImGui::PushStyleColor(ImGuiCol_SliderGrab, {.43f,.015f,.025f,1});
    ImGui::PushStyleColor(ImGuiCol_SliderGrabActive, {.65f,.035f,.045f,1});
    ImGui::PushStyleColor(ImGuiCol_CheckMark, {.9f,.20f,.18f,1});
    ImGui::PushStyleColor(ImGuiCol_TableHeaderBg, {.04f,.04f,.04f,1});
    ImGui::PushStyleColor(ImGuiCol_TableRowBg, {0,0,0,0});
    ImGui::PushStyleColor(ImGuiCol_TableRowBgAlt, {.12f,.12f,.12f,.3f});
    ImGui::PushStyleColor(ImGuiCol_ScrollbarBg, {0,0,0,0});
    ImGui::PushStyleColor(ImGuiCol_ScrollbarGrab, {.45f,.45f,.43f,1});
    ImGui::PushStyleColor(ImGuiCol_TextDisabled, {.72f,.72f,.70f,1});
    ImGui::PushStyleColor(ImGuiCol_TextSelectedBg, {.55f,.04f,.05f,.8f});
    ImGui::PushFont(g_body);
    const bool controls_page = g_controls && !g_page_graphics;
    ImGui::Begin(g_coop ? "Co-op" : g_quit ? "Quit to Desktop" : g_characters ? "Characters" : g_audio ? "Audio" : g_controls ? "Controls" : "Graphics", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings);
    ImGui::SetWindowFontScale(1);
    skin::Frame(ImGui::GetWindowDrawList(), {pos.x, pos.y + 60 * scale}, {size.x, size.y - 60 * scale});
    ImGui::PushFont(g_title);
    if (g_controller_layout) ImGui::SetWindowFontScale(.75f);
    const char* title = language::Text(g_coop ? "CO-OP" : g_quit ? "QUIT TO DESKTOP" : g_characters ? "CHOOSE CHARACTER" : g_audio || g_pause_audio ? "AUDIO" : g_controller_layout ? "CONTROLLER LAYOUT" : controls_page ? "CONTROLS" : "GRAPHICS");
    const float title_width = ImGui::CalcTextSize(title).x;
    const float title_room = size.x - 128 * scale;
    if (title_width > title_room) ImGui::SetWindowFontScale(ImGui::GetCurrentWindow()->FontWindowScale * title_room / title_width);
    // The original accent artwork extends above the capitals; reserve that ink.
    float title_inset = 0;
    if (language::Spanish()) for (const auto& glyph : ImGui::GetFont()->Glyphs)
        title_inset = std::max(title_inset, -glyph.Y0);
    title_inset *= ImGui::GetFontSize() / ImGui::GetFont()->FontSize;
    ImGui::SetCursorPos({96 * scale, title_inset});
    ImGui::TextUnformatted(title);
    ImGui::SetWindowFontScale(1); ImGui::PopFont();
    if (g_quit) {
        // Require the opening click/key/pad press to be released before accepting a choice.
        const bool ready_before = g_quit_ready;
        if (!just_opened && g_released && !io.MouseDown[0] &&
            !ImGui::IsKeyDown(ImGuiKey_Enter) && !ImGui::IsKeyDown(ImGuiKey_KeypadEnter) && !ImGui::IsKeyDown(ImGuiKey_Space) &&
            !ImGui::IsKeyDown(ImGuiKey_GamepadFaceDown)) g_quit_ready = true;
        const auto choice = g_quit_choice.load();
        ImGui::SetCursorPos({96 * scale, 140 * scale});
        ImGui::TextUnformatted(language::Text(choice == 3 ? "Could not quit. Try again." : "Quit to desktop?"));
        ImGui::BeginDisabled(!g_quit_ready || choice == 1 || choice == 2);
        ImGui::SetCursorPos({180 * scale, 285 * scale});
        if (g_quit_ready && !ready_before) {
            ImGui::SetKeyboardFocusHere();
            GImGui->NavDisableHighlight = false;
        }
        const bool cancel = MenuButton("CANCEL", {210 * scale, 39 * scale});
        ImGui::SameLine(430 * scale);
        const bool accept = MenuButton("QUIT", {210 * scale, 39 * scale});
        ImGui::EndDisabled();
        if (choice != 2 && (cancel || ImGui::IsKeyPressed(ImGuiKey_Escape, false) ||
            GamepadBack() || ImGui::IsMouseClicked(ImGuiMouseButton_Right))) Close();
        else if (accept) g_quit_choice = 1;
        ImGui::End(); ImGui::PopFont(); ImGui::PopStyleColor(23); ImGui::PopStyleVar(5);
        return;
    }
    if (g_coop || g_characters || controls_page || g_audio || g_pause_audio) {
        if (g_coop) CoopContent(scale, just_opened, coop);
        else if (g_audio || g_pause_audio) AudioContent(scale, just_opened);
        else if (g_characters) CharactersContent(scale, just_opened);
        else if (g_controller_layout) ControllerLayoutContent(scale);
        else ControlsContent(scale, just_opened);
        ImGui::End(); ImGui::PopFont(); ImGui::PopStyleColor(23); ImGui::PopStyleVar(5);
        return;
    }
    ImGui::BeginDisabled(g_confirm);
    ImGui::SetCursorPos({0, 132 * scale});
    ImGui::BeginChild("Graphics scroll", {938 * scale, 308 * scale}, ImGuiChildFlags_NavFlattened);
    char text[96];
    { MenuRow row("DISPLAY MODE", 8, scale);
    int mode = int(g_draft.display_mode);
    if (just_opened) ImGui::SetKeyboardFocusHere();
    if (Choice("##display", &mode, "Fullscreen\0Borderless\0Windowed\0")) g_draft.display_mode = app::DisplayMode(mode);
    }
    { MenuRow row("RESOLUTION", 64, scale);
    bool borderless = g_draft.display_mode == app::DisplayMode::Borderless;
    app::Mode resolution = borderless || !g_draft.width || !g_draft.height ? app::Desktop() : app::Mode{g_draft.width,g_draft.height};
    std::snprintf(text, sizeof(text), "%u x %u%s", resolution.width, resolution.height, borderless ? language::Text("  (Desktop)") : "");
    ImGui::BeginDisabled(borderless);
    if (ImGui::BeginCombo("##resolution", text)) {
        for (auto item : g_modes) {
            std::snprintf(text, sizeof(text), "%u x %u", item.width, item.height);
            bool selected = resolution.width == item.width && resolution.height == item.height;
            if (ImGui::Selectable(text, selected)) {g_draft.width = item.width; g_draft.height = item.height;}
            if (selected) ImGui::SetItemDefaultFocus();
        }
        ImGui::EndCombo();
    }
    ImGui::EndDisabled();
    }
    { MenuRow row("ASPECT RATIO", 120, scale);
    int aspect = int(g_draft.aspect_ratio);
    if (Choice("##aspect", &aspect, "Automatic\0Widescreen 16:9\0Original 4:3\0")) g_draft.aspect_ratio = app::AspectRatio(aspect);
    }
    { MenuRow row("RENDER RESOLUTION", 176, scale);
    int percent = int(g_draft.render_percent);
    if (ImGui::SliderInt("##internal", &percent, 25, 200, "%d%%", ImGuiSliderFlags_AlwaysClamp)) g_draft.render_percent = uint32_t(percent);
    auto render = app::RenderSize(g_draft);
    ImGui::SetCursorPos({430 * scale, 222 * scale});
    std::snprintf(text, sizeof(text), language::Text("%u x %u rendering"), render.width, render.height); Hint(text);
    }
    { MenuRow row("FIELD OF VIEW", 265, scale);
    int fov = int(g_view_draft.fov_percent);
    if (ImGui::SliderInt("##fov", &fov, 50, 200, "%d%%", ImGuiSliderFlags_AlwaysClamp)) g_view_draft.fov_percent = uint32_t(fov);
    ImGui::SetCursorPos({430 * scale, 311 * scale});
    Hint("100% = original view. Zoom is preserved.");
    }
    { MenuRow row("WEAPON FOV", 354, scale);
    int weapon_fov = int(g_view_draft.viewmodel_fov_percent);
    if (ImGui::SliderInt("##weapon_fov", &weapon_fov, 50, 150, "%d%%", ImGuiSliderFlags_AlwaysClamp)) g_view_draft.viewmodel_fov_percent = uint32_t(weapon_fov);
    ImGui::SetCursorPos({430 * scale, 400 * scale});
    Hint("Changes gun and hand framing.");
    }
    { MenuRow row("RETICLE SIZE", 443, scale);
    int reticle = int(g_view_draft.reticle_percent);
    if (ImGui::SliderInt("##reticle", &reticle, 50, 200, "%d%%", ImGuiSliderFlags_AlwaysClamp)) g_view_draft.reticle_percent = uint32_t(reticle);
    }
    { MenuRow row("CUTSCENE BORDERS", 499, scale);
    Toggle("##cutscene_borders", g_view_draft.cutscene_borders);
    ImGui::SetCursorPos({430 * scale, 545 * scale});
    Hint("Level cutscenes only.");
    ImGui::SetCursorPos({430 * scale, 588 * scale});
    if (MenuButton("RESET VIEW DEFAULTS", {482 * scale, 39 * scale})) {
        g_view_draft.fov_percent = g_view_draft.reticle_percent = g_view_draft.viewmodel_fov_percent = 100;
        g_view_draft.cutscene_borders = true;
    }
    }
    { MenuRow row("FPS COUNTER", 644, scale);
    int fps_enabled = g_view_draft.show_fps ? 1 : 0;
    if (Choice("##fps", &fps_enabled, "Off\0On\0")) g_view_draft.show_fps = fps_enabled != 0;
    }
    { MenuRow row("VERTICAL SYNC", 700, scale);
    int vsync = g_draft.vsync ? 1 : 0;
    if (Choice("##vsync", &vsync, "Off\0On\0")) g_draft.vsync = vsync != 0;
    }
    { MenuRow row("FPS LIMIT", 756, scale);
    if (g_draft.fps_cap) std::snprintf(text, sizeof(text), "%u FPS", g_draft.fps_cap);
    else std::snprintf(text, sizeof(text), "%s", language::Text("Unlimited"));
    if (ImGui::BeginCombo("##cap", text)) {
        for (uint32_t cap : {30u, 60u, 90u, 120u, 144u, 165u, 240u, 0u}) {
            char choice[32];
            if (cap) std::snprintf(choice, sizeof(choice), "%u FPS", cap);
            else std::snprintf(choice, sizeof(choice), "%s", language::Text("Unlimited"));
            bool selected = cap == g_draft.fps_cap;
            if (ImGui::Selectable(choice, selected)) g_draft.fps_cap = cap;
            if (selected) ImGui::SetItemDefaultFocus();
        }
        ImGui::EndCombo();
    }
    }
    { MenuRow row("MSAA", 812, scale);
    int msaa = g_draft.msaa_samples == 4 ? 2 : g_draft.msaa_samples == 2 ? 1 : 0;
    if (Choice("##msaa", &msaa, "Off\0" "2x\0" "4x\0")) g_draft.msaa_samples = 1u << msaa;
    ImGui::SetCursorPos({430 * scale, 858 * scale});
    const uint32_t active_samples = gpu::MsaaSamples();
    std::snprintf(text, sizeof(text), language::Text("Active: %s - GPU support required"), active_samples == 4 ? "4x" : active_samples == 2 ? "2x" : language::Text("Off")); Hint(text);
    }
    { MenuRow row("TEXTURE FILTERING", 901, scale);
    constexpr uint32_t aniso_values[]{0, 1, 2, 4, 8, 16};
    int aniso = 0;
    for (unsigned i = 0; i < std::size(aniso_values); ++i) if (g_draft.aniso == aniso_values[i]) aniso = int(i);
    if (Choice("##aniso", &aniso, "Original\0" "1x\0" "2x\0" "4x\0" "8x\0" "16x\0")) g_draft.aniso = aniso_values[aniso];
    }
    { MenuRow row("HD ARTWORK", 957, scale);
    int hd_ui = g_view_draft.hd_ui ? 1 : 0;
    if (Choice("##hd_ui", &hd_ui, "Off\0On\0")) g_view_draft.hd_ui = hd_ui != 0;
    ImGui::SetCursorPos({430 * scale, 1003 * scale});
    Hint("HD menus, fonts and HUD.");
    }
    { MenuRow row("SUBTITLES", 1046, scale);
    ImGui::BeginDisabled(!g_subtitles_available);
    Toggle("##subtitles", g_subtitles_draft);
    ImGui::EndDisabled();
    }
    { MenuRow row("BRIGHTNESS", 1102, scale);
    int brightness = int(g_draft.brightness_percent);
    if (ImGui::SliderInt("##brightness", &brightness, 50, 150, "%d%%", ImGuiSliderFlags_AlwaysClamp))
        g_draft.brightness_percent = uint32_t(brightness);
    ImGui::SetCursorPos({430 * scale, 1148 * scale});
    Hint("100% = original. Lower is darker.");
    }
    { const bool available = GameplayTexturesAvailable();
    ImGui::BeginDisabled(!available);
    { MenuRow row("HD TEXTURES", 1191, scale);
    bool enabled = available && g_view_draft.hd_textures;
    Toggle("##hd_textures", enabled);
    if (available) g_view_draft.hd_textures = enabled;
    }
    ImGui::EndDisabled();
    ImGui::SetCursorPos({430 * scale, 1237 * scale});
    Hint(available ? "Installed gameplay textures. UI unchanged." : "Install the HD texture pack in the launcher.");
    }
    if (state.paused) {
        ImGui::SetCursorPos({88 * scale, 1295 * scale});
        if (g_audio_returned) {ImGui::SetKeyboardFocusHere(); g_audio_returned = false;}
        if (MenuButton("AUDIO...", {824 * scale, 39 * scale})) {
            g_audio_draft = state.audio; g_surround_draft = audio::SurroundEnabled();
            g_original_draft = state; g_pause_audio = true; g_audio_focus = true; g_notice = "";
            g_released = false; g_pad = 0;
        }
    }
    ImGui::Dummy({1, 12 * scale});
    EndSettingsChild();
    ImGui::SetCursorPos({220 * scale, 507 * scale});
    Hint("Restart after changing aspect ratio.");
    ImGui::EndDisabled();
    ImGui::SetCursorPos({220 * scale, 450 * scale});
    Hint(g_notice);
    // Disabled overlapping buttons still claim hover; submit only one footer per frame.
    if (g_confirm) {
        ImGui::SetCursorPos({220 * scale, 448 * scale});
        std::snprintf(text, sizeof(text), language::Text("Keep display settings? Reverting in %d seconds."), std::max(1, int(std::ceil(g_confirm_until - ImGui::GetTime())))); Hint(text);
        ImGui::SetCursorPos({220 * scale, 541 * scale});
        if (MenuButton("KEEP", {310 * scale, 39 * scale})) SaveChanges();
        ImGui::SameLine(550 * scale);
        if (MenuButton("REVERT", {362 * scale, 39 * scale}) || ImGui::IsKeyPressed(ImGuiKey_Escape, false) || GamepadBack() || ImGui::IsMouseClicked(ImGuiMouseButton_Right)) Revert();
    } else {
        ImGui::SetCursorPos({220 * scale, 541 * scale});
        if (MenuButton("APPLY", {300 * scale, 39 * scale})) ApplyChanges();
        ImGui::SameLine(650 * scale);
        if (MenuButton("BACK", {262 * scale, 39 * scale})) Close();
        if (!g_confirm && (ImGui::IsKeyPressed(ImGuiKey_Escape, false) || GamepadBack() ||
            ImGui::IsMouseClicked(ImGuiMouseButton_Right))) Close();
    }
    ImGui::End(); ImGui::PopFont(); ImGui::PopStyleColor(23); ImGui::PopStyleVar(5);
}
