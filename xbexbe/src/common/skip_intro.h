#pragma once
#include <cstdlib>
#include <cstring>
inline bool DarkwatchSkipIntro() {
    static const bool enabled = [] {
        const char* value = std::getenv("DARKWATCH_SKIP_INTRO");
        return value && std::strcmp(value, "1") == 0;
    }();
    return enabled;
}
