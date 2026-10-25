#pragma once
#include "character_selection.h"
#include <imgui.h>
#include <filesystem>

namespace darkwatch::preview {
// Register before the shared font atlas is built; Finalize fills those cells
// after the cursor/skin build, before its first GPU upload. No game actors load.
bool Initialize(ImFontAtlas* atlas, const std::filesystem::path& pack,
                const std::filesystem::path& hd_directory = {});
bool Finalize();
bool Draw(settings::Character character, ImVec2 minimum, ImVec2 maximum,
          double elapsed_seconds, bool hd_enabled = true);
void Reset();
} // namespace darkwatch::preview
