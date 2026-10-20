#pragma once
#include <cstdint>

struct X86Context;
// Network co-op: while a guest plays, the two-player layout entries describe full-screen
// views, so each player's camera covers the whole frame instead of a horizontal half.
// FA3BC passes the selected layout entry in edi to F9B1D; the table is rewritten in place
// so the layout readers (FA0FB) agree. A level reload applies a guest joining or leaving.
void DarkwatchCoopViewLayout(X86Context& ctx, uint8_t* base);
// The guest's world camera (F9B57, after the view constructor) and its HUD camera
// (D836A records the HUD's player camera, D83DC sees the new HUD camera) draw into a
// separate full-size frame/Z raster pair instead of the shared frame buffer.
void DarkwatchCoopViewCreated(X86Context& ctx, uint8_t* base);
void DarkwatchCoopHudOwner(X86Context& ctx, uint8_t* base);
void DarkwatchCoopHudCreated(X86Context& ctx, uint8_t* base);
// 21606D, per player camera each frame: F7 on the host gives the other view the
// off-screen rasters (the guest may have confirmed first and own view 0).
void DarkwatchCoopViewFrame(X86Context& ctx, uint8_t* base);
// 1289C7: counts the guest camera's begin-updates; cinematics and movies leave it idle.
void DarkwatchCoopCameraBegin(X86Context& ctx, uint8_t* base);

namespace darkwatch::coop {
// True for a layout entry this module made full screen; `player` is its view index.
// The single-player entry 0x491668 reports player 0 without being a co-op entry.
bool FullscreenLayout(const uint8_t* base, uint32_t entry, uint32_t& player);
// The guest's frame raster while a level created one, else 0.
uint32_t GuestFrameRaster();
// Any thread: guest address of the guest target's pixels (the renderer's target key), else 0.
uint32_t GuestFramePixels();
// Any thread: the guest target's D3D texture header, else 0.
uint32_t GuestFrameTexture();
// Any thread: the guest raster's size inside that target.
void GuestFrameSize(uint32_t& width, uint32_t& height);
// During F9B1D: the view being created belongs to the network guest's controller.
bool CreatingGuestView(bool coop, uint32_t player);
// Game thread, direct mouse: the camera stack of the player on controller `port`.
void NoteCameraStack(unsigned port, uint32_t stack);
// Any thread: how many times the guest's camera began drawing.
uint64_t GuestCameraDraws();
// Port 0's pad poll publishes whether the in-game Pause menu is open; any thread reads it.
void NotePaused(bool paused);
bool Paused();
} // namespace darkwatch::coop
