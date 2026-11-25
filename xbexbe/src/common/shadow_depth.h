#pragma once
#include <cmath>

inline float DarkwatchShadowFarPlane(float requested, float near_z, float far_z) {
    if (!std::isfinite(requested) || !std::isfinite(near_z) || !std::isfinite(far_z) ||
        near_z <= 0 || far_z <= near_z || requested != far_z * 1.1f) return requested;
    // The authored 10% far-plane extension moves distant shadows in front of
    // walls. Retain only one float step in A (about two D24 depth steps).
    const float a = far_z / (far_z - near_z);
    const float biased = std::nextafter(a, 1.f);
    if (!std::isfinite(a) || biased <= 1.f) return far_z;
    const float result = near_z * biased / (biased - 1.f);
    return std::isfinite(result) && result >= far_z && result <= requested ? result : far_z;
}
