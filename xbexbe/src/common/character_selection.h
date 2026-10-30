#pragma once
#include <array>

namespace darkwatch::settings {
enum class Character {
    Jericho = 0, Cassidy = 1, SpectralCassidy = 2, CivilianJericho = 3,
    Trooper = 4, BlueTrooper = 5, RedTrooper = 6, Tala = 7,
    VampireTala = 8, BossTala = 9
};
inline constexpr std::array<const char*, 10> kCharacterNames{
    "Jericho", "Cassidy", "Spectral Cassidy", "Civilian Jericho",
    "Darkwatch Trooper", "Blue Trooper", "Red Trooper", "Tala",
    "Vampire Tala", "Boss Tala"
};
inline constexpr unsigned kCharacterCount = kCharacterNames.size();
constexpr bool ValidCharacter(Character character) { return unsigned(character) < kCharacterCount; }
constexpr bool TalaCharacter(Character character) {
    return character == Character::Tala || character == Character::VampireTala || character == Character::BossTala;
}
constexpr const char* CharacterName(Character character) {
    return kCharacterNames[ValidCharacter(character) ? unsigned(character) : 0];
}
// Player one's choice is shared by solo and co-op; player two is independent.
std::array<Character, 2> characters();
Character configured_character(unsigned ordinal);
bool set_characters(std::array<Character, 2> choices);
void LoadCharacters(const void* table);
void SaveCharacters(void* table);
} // namespace darkwatch::settings
