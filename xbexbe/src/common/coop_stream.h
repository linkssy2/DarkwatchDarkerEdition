#pragma once

namespace gpu { class Context; }

namespace darkwatch::coop::stream {
// Render thread, each present: while a network guest plays, copies the guest's off-screen
// target into a readback ring and hands frames that the GPU finished to the encoder
// thread, which sends H.264 to the guest.
void Presenting(gpu::Context& context);
} // namespace darkwatch::coop::stream
