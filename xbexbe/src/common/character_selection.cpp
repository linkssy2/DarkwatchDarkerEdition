#include "character_selection.h"
#include <mutex>
#include <string>
#include <toml++/toml.hpp>

namespace darkwatch::settings {
namespace {
std::mutex lock;
std::array<Character, 2> configured{Character::Jericho, Character::Jericho};
constexpr const char* keys[]{"player_one_character", "player_two_character"};
std::array<Character, 4> versus{Character::Trooper, Character::Trooper, Character::Trooper, Character::Trooper};
constexpr const char* versus_keys[]{"versus_player_one_character", "versus_player_two_character",
    "versus_player_three_character", "versus_player_four_character"};
}

std::array<Character, 2> characters() {
    std::lock_guard guard(lock);
    return configured;
}

Character configured_character(unsigned ordinal) {
    const auto choices = characters();
    return ordinal < choices.size() ? choices[ordinal] : Character::Jericho;
}

bool set_characters(std::array<Character, 2> choices) {
    for (auto choice : choices)
        if (!ValidCharacter(choice)) return false;
    std::lock_guard guard(lock);
    configured = choices;
    return true;
}

std::array<Character, 4> versus_characters() {
    std::lock_guard guard(lock);
    return versus;
}

bool set_versus_characters(std::array<Character, 4> choices) {
    for (auto choice : choices)
        if (!ValidCharacter(choice)) return false;
    std::lock_guard guard(lock);
    versus = choices;
    return true;
}

void LoadCharacters(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    std::array<Character, 2> choices{Character::Jericho, Character::Jericho};
    for (unsigned i = 0; i < choices.size(); ++i) {
        const auto choice = t[keys[i]].value_or(std::string{});
        for (unsigned id = 0; id < kCharacterCount; ++id)
            if (choice == kCharacterNames[id]) { choices[i] = Character(id); break; }
    }
    set_characters(choices);
    std::array<Character, 4> multiplayer{Character::Trooper, Character::Trooper, Character::Trooper, Character::Trooper};
    for (unsigned i = 0; i < multiplayer.size(); ++i) {
        const auto choice = t[versus_keys[i]].value_or(std::string{});
        for (unsigned id = 0; id < kCharacterCount; ++id)
            if (choice == kCharacterNames[id]) { multiplayer[i] = Character(id); break; }
    }
    set_versus_characters(multiplayer);
}

void SaveCharacters(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    const auto choices = characters();
    for (unsigned i = 0; i < choices.size(); ++i)
        t.insert_or_assign(keys[i], CharacterName(choices[i]));
    const auto multiplayer = versus_characters();
    for (unsigned i = 0; i < multiplayer.size(); ++i)
        t.insert_or_assign(versus_keys[i], CharacterName(multiplayer[i]));
}
} // namespace darkwatch::settings
