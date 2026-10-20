#pragma once

namespace gpu { class Context; struct Target; }

namespace darkwatch::coop::stream {
// Render thread, each present: while a network guest plays, copies the guest's off-screen
// target into a readback ring and hands frames that the GPU finished to the encoder
// thread, which sends H.264 to the guest. While the guest's camera stops drawing (in-level
// cinematics, movies) the presented frame `front` is sent instead.
void Presenting(gpu::Context& context, gpu::Target* front);
} // namespace darkwatch::coop::stream
