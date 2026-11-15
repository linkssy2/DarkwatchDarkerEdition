#include "audio_settings.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <string_view>

namespace {
struct Cue { std::string_view bank, name; };
constexpr Cue vocals[]{
#include "monster_vocals.inc"
};
bool Span(const uint8_t* base, uint64_t at, unsigned bytes) {
    if (!base || !at || at + bytes > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~uint64_t(mem::kPage - 1); page < at + bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof value)) return false;
    std::memcpy(&value, base + at, sizeof value); return true;
}
bool Name(const uint8_t* base, uint64_t slot, std::array<char,128>& text) {
    uint32_t ref;
    if (!Read(base, slot, ref) || !ref) return false;
    for (unsigned i=0; i<text.size(); ++i) {
        char c;
        if (!Read(base, uint64_t(ref)+2+i, c)) return false;
        if (!c) return i != 0;
        if (c < 32 || c > 126 || i+1 == text.size()) return false;
        text[i] = c == '\\' ? '/' : c >= 'A' && c <= 'Z' ? c+'a'-'A' : c;
    }
    return false;
}
}

void DarkwatchMonsterVolume(X86Context& ctx, uint8_t* base) {
    const int percent = darkwatch::MonsterScreamsVolume();
    if (percent == 100 || base != kernel::g_base || ctx.ebp < 12) return;
    uint32_t prototype, bank, type;
    std::array<char,128> bank_text{}, cue_text{};
    float gain;
    // 208F7C binds prototype +28 to its cue ID and +10 to the owning bank.
    // 210A31 follows the original combined gain spill, before its native clamp.
    if (!Read(base, uint64_t(ctx.esi)+0x20, prototype) || !prototype ||
        !Read(base, uint64_t(prototype)+0x10, bank) || !bank ||
        !Read(base, bank, type) || type != 0x43ED44 ||
        !Name(base, uint64_t(bank)+0x10, bank_text) ||
        !Name(base, uint64_t(prototype)+0x28, cue_text) ||
        !Read(base, uint64_t(ctx.ebp)-12, gain) || !std::isfinite(gain) || gain < 0) return;
    std::string_view bank_name(bank_text.data());
    const auto slash = bank_name.find_last_of('/');
    if (slash != bank_name.npos) bank_name.remove_prefix(slash+1);
    for (auto suffix : {std::string_view(".babf"), std::string_view(".xsb")})
        if (bank_name.ends_with(suffix)) bank_name.remove_suffix(suffix.size());
    const Cue key{bank_name, cue_text.data()};
    const auto less = [](const Cue& a, const Cue& b) {
        return a.bank < b.bank || (a.bank == b.bank && a.name < b.name);
    };
    if (!std::binary_search(std::begin(vocals), std::end(vocals), key, less)) return;
    gain *= float(percent) / 100.f;
    std::memcpy(base + ctx.ebp - 12, &gain, sizeof gain);
}
