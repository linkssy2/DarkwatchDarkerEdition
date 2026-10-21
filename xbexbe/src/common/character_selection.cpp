#include "character_selection.h"
#include <mutex>
#include <string>
#include <toml++/toml.hpp>

namespace darkwatch::settings {
namespace {
std::mutex lock;
std::array<Character, 2> configured{Character::Jericho, Character::Jericho};
constexpr const char* keys[]{"player_one_character", "player_two_character"};
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
        if (choice != Character::Jericho && choice != Character::Cassidy) return false;
    std::lock_guard guard(lock);
    configured = choices;
    return true;
}

void LoadCharacters(const void* table) {
    const auto& t = *static_cast<const toml::table*>(table);
    std::array<Character, 2> choices{Character::Jericho, Character::Jericho};
    for (unsigned i = 0; i < choices.size(); ++i)
        if (t[keys[i]].value_or(std::string{}) == "Cassidy") choices[i] = Character::Cassidy;
    set_characters(choices);
}

void SaveCharacters(void* table) {
    auto& t = *static_cast<toml::table*>(table);
    const auto choices = characters();
    for (unsigned i = 0; i < choices.size(); ++i)
        t.insert_or_assign(keys[i], choices[i] == Character::Cassidy ? "Cassidy" : "Jericho");
}
} // namespace darkwatch::settings
