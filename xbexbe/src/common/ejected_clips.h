#pragma once
#include <array>
#include <cstdint>
#include "clip_foot_contact.h"
struct X86Context;

namespace darkwatch::clips {
enum class Kind { Redeemer, DualPistol, Crossbow, Sniper, Rocket };
using Matrix = std::array<float, 16>;
// Native factory/physics only. Call at the guest frame mutation boundary with
// a validated world-space release pose; the loaded area owns the actor lifetime.
uint32_t CreateNativeProp(const X86Context& ctx, uint8_t* base, uint32_t owner,
                          Kind kind, const Matrix& placement);
void KickNativeProp(const X86Context& ctx,uint8_t* base,uint32_t body,
                    const FootBox& foot,Vec previous,float dt);
}

// Draw-local suppression only; spawning is deferred to the native frame update.
bool DarkwatchEjectedClipSkinPalette(X86Context& ctx, uint8_t* base);
void DarkwatchClipFootClock(const X86Context& ctx,uint8_t* base);
bool DarkwatchClipFootPlayer(const uint8_t* base,uint32_t actor);
