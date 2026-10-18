#pragma once

namespace darkwatch {
// After the window fonts exist, before the first rendered frame. Reads the user's original asset only.
bool InitializeMenuCursor();
// Call last in the title UI frame when pointer mode is active; the caller owns OS cursor visibility.
void DrawMenuCursor();
}
