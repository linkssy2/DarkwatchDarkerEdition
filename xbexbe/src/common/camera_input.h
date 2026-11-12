#pragma once
#include <cstdint>
namespace input {struct Pad;}
void DarkwatchCycleCameraInput(int port, input::Pad& pad, bool on_foot, uint32_t actor);
void DarkwatchShoulderInput(int port, input::Pad& pad, bool on_foot, uint32_t actor);
