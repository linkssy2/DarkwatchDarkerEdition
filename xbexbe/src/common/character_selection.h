#pragma once
#include <array>

namespace darkwatch::settings {
enum class Character { Jericho = 0, Cassidy = 1, SpectralCassidy = 2 };
// Player one's choice is shared by solo and co-op; player two is independent.
std::array<Character, 2> characters();
Character configured_character(unsigned ordinal);
bool set_characters(std::array<Character, 2> choices);
void LoadCharacters(const void* table);
void SaveCharacters(void* table);
} // namespace darkwatch::settings
