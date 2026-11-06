#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
#include <string_view>

namespace darkwatch::language {
// Startup only: Load the preference, then Initialize before guest/UI threads start.
void Load(const void* table);
void Save(void* table);
bool Initialize(const std::filesystem::path& executable_directory);
// Validated requested locale; a missing catalogue still falls back to English text.
const char* Code();
// Only a successfully loaded locale may supply optional localized game media.
std::filesystem::path MediaDirectory(const std::filesystem::path& executable_directory);
bool Spanish();
bool Portuguese();
bool Translated();
const char* Text(const char* english);
const char* Guest(const char* english);
// Native localized-text objects store CRC32 of the uppercase ASCII text ID.
uint32_t NativeKey(std::string_view key);
std::string Translate(uint32_t native_key, std::string_view original);
std::string Translate(std::string_view key, std::string_view original);
} // namespace darkwatch::language
