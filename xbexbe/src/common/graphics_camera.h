#pragma once
#include <cstdint>
#include <array>

struct X86Context;
// Original single-player/two-player camera creation; other layouts are untouched.
void DarkwatchPreparePlayerViewport(X86Context& ctx, uint8_t* base);
void DarkwatchConfigurePlayerCamera(X86Context& ctx, uint8_t* base);
// Correct the separately owned cinematic camera before its first rendered frame.
void DarkwatchConfigureCinematicCamera(X86Context& ctx, uint8_t* base);
// Original camera update: retain cinematic framing and per-player view preferences.
void DarkwatchUpdateCameraView(X86Context& ctx, uint8_t* base);
// Admit only a registered player's current native perspective projection.
bool DarkwatchWorldProjectionMatches(const uint8_t* base, uint32_t camera,
                                    const std::array<float, 16>& projection);
// Keep the third-person reticle centered on its native camera-target aiming ray.
bool DarkwatchThirdPersonReticle(const uint8_t* base, uint32_t player, float& ndc_x, float& ndc_y);
// Live on-foot body visible in third-person or to the other local co-op player.
bool DarkwatchThirdPersonPlayer(const X86Context& ctx, uint8_t* base, uint32_t actor, uint32_t control);
// Body presentation also follows a first-person co-op owner's unmodified native aim.
bool DarkwatchThirdPersonBodyAimTarget(const X86Context& ctx, uint8_t* base, uint32_t actor,
                                      std::array<float, 3>& target);
// Capture the current external view at the original player-death state boundary.
// This render-only view does not make a dead player eligible for aiming or actions.
bool DarkwatchBeginThirdPersonDeath(const X86Context& ctx, uint8_t* base, uint32_t actor);
void DarkwatchEndThirdPersonDeath(uint8_t* base, uint32_t actor);
// Recompute the current collision-swept camera target without advancing hands.
// A zero component resolves the primary weapon; explicit components support offhand fire.
bool DarkwatchThirdPersonAimTarget(const X86Context& ctx, uint8_t* base, uint32_t actor,
                                  uint32_t weapon_component, std::array<float, 3>& target,
                                  uint32_t* target_actor = nullptr);
// Render-only camera scope; native camera ownership stays unchanged.
bool DarkwatchBeginThirdPersonRender(X86Context& ctx, uint8_t* base, uint32_t personal);
void DarkwatchEndThirdPersonRender(X86Context& ctx, uint8_t* base, uint32_t personal);
bool DarkwatchThirdPersonRenderActive(const uint8_t* base, uint32_t camera);
// Flip only the registered on-foot actor's shoulder view; other camera modes ignore it.
bool DarkwatchSwapShoulder(const uint8_t* base, uint32_t actor);
bool DarkwatchShoulderAvailable(const uint8_t* base, uint32_t actor);
// Temporarily use the weapon preference inside the original first-person draw.
void DarkwatchBeginWeaponView(X86Context& ctx, uint8_t* base);
void DarkwatchEndWeaponView(X86Context& ctx, uint8_t* base);
// Preserve the authored rune screen-overlay framing at custom world FOV.
void DarkwatchBeginPowerView(X86Context& ctx, uint8_t* base);
void DarkwatchEndPowerView(X86Context& ctx, uint8_t* base);
void DarkwatchPowerViewProjection(X86Context& ctx, uint8_t* base);
