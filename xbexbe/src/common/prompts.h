#pragma once
#include <cstdint>
#include "core/input.h"
struct X86Context;
namespace gpu { struct TextureDesc; struct FormatInfo; struct TextureReplacement; }
namespace darkwatch {
enum class ControllerPromptSymbol : uint8_t {
    None, Cross, Circle, Square, Triangle, Plus, Minus, Up, Down, Left, Right,
    LeftStick, RightStick, LeftStickPress, RightStickPress
};
struct ControllerPrompt { const char* label; ControllerPromptSymbol symbol; };
// Physical positions match the guest report; Nintendo lettering must not swap actions.
constexpr ControllerPrompt ControllerPromptInfo(input::ControllerFamily family, input::PcAction action) {
    using S = ControllerPromptSymbol;
    using A = input::PcAction;
    const bool ps = family == input::ControllerFamily::PlayStation;
    const bool sw = family == input::ControllerFamily::Switch;
    switch (action) {
        case A::DpadUp: return {"", S::Up};
        case A::DpadDown: return {"", S::Down};
        case A::DpadLeft: return {"", S::Left};
        case A::DpadRight: return {"", S::Right};
        case A::Start: return {ps ? "OPTIONS" : sw ? "" : "START", sw ? S::Plus : S::None};
        case A::Back: return {ps ? "SHARE" : sw ? "" : "BACK", sw ? S::Minus : S::None};
        case A::LeftThumb: return {ps ? "L3" : "L", ps ? S::None : S::LeftStickPress};
        case A::RightThumb: return {ps ? "R3" : "R", ps ? S::None : S::RightStickPress};
        case A::A: return {ps ? "" : sw ? "B" : "A", ps ? S::Cross : S::None};
        case A::B: return {ps ? "" : sw ? "A" : "B", ps ? S::Circle : S::None};
        case A::X: return {ps ? "" : sw ? "Y" : "X", ps ? S::Square : S::None};
        case A::Y: return {ps ? "" : sw ? "X" : "Y", ps ? S::Triangle : S::None};
        case A::Black: return {ps ? "R1" : sw ? "R" : "RB", S::None};
        case A::White: return {ps ? "L1" : sw ? "L" : "LB", S::None};
        case A::LeftTrigger: return {ps ? "L2" : sw ? "ZL" : "LT", S::None};
        case A::RightTrigger: return {ps ? "R2" : sw ? "ZR" : "RT", S::None};
        case A::MoveForward: case A::MoveBackward: case A::MoveLeft: case A::MoveRight:
            return {"L", S::LeftStick};
        default: return {"", S::None};
    }
}
uint64_t PromptTextureRevision();
bool ReplacePromptTexture(const gpu::TextureDesc&, const gpu::FormatInfo&, const uint8_t*, uint32_t, gpu::TextureReplacement&);
}
void DarkwatchPromptFont(X86Context&, uint8_t*);
void DarkwatchPromptFontDestroy(X86Context&, uint8_t*);
void DarkwatchPromptLocalization(X86Context&, uint8_t*);
void DarkwatchPromptStartToken(X86Context&, uint8_t*);
bool DarkwatchPromptMovementToken(X86Context&, uint8_t*);
