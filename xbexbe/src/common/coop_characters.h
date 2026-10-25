#pragma once
#include "character_selection.h"
#include <array>
#include <cstdint>
struct X86Context;

namespace darkwatch {
struct CoopSetupState {
    uint32_t owner = 0; // Zero unless the original co-op setup owns the frontend.
    std::array<settings::Character, 2> characters{};
    std::array<bool, 2> ready{}, connected{};
    bool character_available = false;
};
// Guest-thread bridge. The drawing thread uses a copied snapshot and queues
// actions with its owner; every action rejects stale pages and modal overlays.
CoopSetupState QueryCoopSetup(const uint8_t* base);
bool SetCoopSetupCharacter(uint8_t* base, uint32_t owner, unsigned player, settings::Character character);
bool SetCoopSetupReady(uint8_t* base, uint32_t owner, unsigned player, bool ready);
bool BackCoopSetup(uint8_t* base, uint32_t owner, unsigned player);
}

// Native co-op controls own their draft. Both Ready commits; Back discards it.
void DarkwatchCoopCharactersInitialize(X86Context& ctx, uint8_t* base);
// True cancels Ready before native profile replacement if replay cleanup failed.
bool DarkwatchCoopCharactersCommit(X86Context& ctx, uint8_t* base);
// Hide only the replaced page's native contents; its fade lifecycle still runs.
bool DarkwatchHideCoopSetupContent(X86Context& ctx, uint8_t* base);
