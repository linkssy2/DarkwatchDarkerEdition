#include "audio_settings.h"
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <string_view>

extern "C" void __imp__sub_001D8F0F(X86Context&, uint8_t*);
extern "C" void __imp__sub_001D8980(X86Context&, uint8_t*);

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
// Mines PP_04 is authored random scream ambience, independent of the tree's speaker.
bool MinesBank(const uint8_t* base, uint32_t definition) {
    uint32_t loader=0,type=0,id=0,buckets=0,count=0,total=0,rows=0;uint16_t size=0;
    if (!Read(base,0x4B4F80,loader) || !Read(base,loader,type) || type!=0x43EDFC ||
        !Read(base,uint64_t(definition)+4,id) || !id ||
        !Read(base,uint64_t(loader)+4,buckets) || !Read(base,uint64_t(loader)+8,count) ||
        !count || count>512 || !Read(base,uint64_t(loader)+12,total) || total>4096 ||
        !Span(base,buckets,count*8)) return false;
    const uint64_t bucket=uint64_t(buckets)+(id%count)*8;
    if (!Read(base,bucket,size) || size>total || !Read(base,bucket+4,rows) ||
        (size && !Span(base,rows,size*8))) return false;
    for (unsigned i=0;i<size;++i) {
        uint32_t key=0,bank=0,state=0;std::array<char,128> path{};
        if (!Read(base,uint64_t(rows)+i*8,key) || key!=id) continue;
        if (!Read(base,uint64_t(rows)+i*8+4,bank) || !Read(base,bank,type) || type!=0x43EDD4 ||
            !Read(base,uint64_t(bank)+4,key) || key!=id ||
            !Read(base,uint64_t(bank)+8,state) || state!=2 || !Name(base,uint64_t(bank)+12,path)) return false;
        const std::string_view name(path.data());
        return name=="audio/emitter_m05a/emitter_m05a.xsb" ||
               name=="audio/emitter_m05b/emitter_m05b.xsb" ||
               name=="audio/emitter_m05c/emitter_m05c.xsb";
    }
    return false;
}
bool DestroyedTreeAmbience(const uint8_t* base, uint32_t sound, uint32_t bank) {
    uint32_t type=0,manager=0,groups=0;uint16_t count=0;
    std::array<float,3> position{};
    if (!Read(base,sound,type) || type!=0x43EEDC || !MinesBank(base,bank) ||
        !Read(base,uint64_t(sound)+0x50,position) ||
        !std::all_of(position.begin(),position.end(),[](float x){return std::isfinite(x);}) ||
        !Read(base,0x4AC118,manager) || !Read(base,manager,count) || count>256 ||
        !Read(base,uint64_t(manager)+4,groups) || (count && !Span(base,groups,count*4))) return false;
    // PP_04's authored audible radius is 24m. Preserve screams nearest a living tree.
    float nearest=24.f*24.f;bool destroyed=false;unsigned visited=0;
    for (unsigned g=0;g<count;++g) {
        uint32_t group=0,rows=0;uint16_t n=0;
        if (!Read(base,uint64_t(groups)+g*4,group) || !Read(base,uint64_t(group)+0x20,n) ||
            n>4096-visited || !Read(base,uint64_t(group)+0x24,rows) ||
            (n && !Span(base,rows,n*4))) return false;
        visited+=n;
        for (unsigned i=0;i<n;++i) {
            uint32_t actor=0,flags=0;uint8_t removed=0;std::array<char,128> name{};std::array<float,3> at{};
            if (!Read(base,uint64_t(rows)+i*4,actor) || !actor ||
                !Read(base,uint64_t(actor)+0x5E,removed) || removed ||
                !Read(base,uint64_t(actor)+0x90,flags) || (flags&2) ||
                !Name(base,uint64_t(actor)+0x50,name)) continue;
            const std::string_view kind(name.data());
            if (kind!="markofevil" && kind!="markofevil_stump") continue;
            if (!Read(base,uint64_t(actor)+0x40,at)) return false;
            float distance=0;
            for (unsigned k=0;k<3;++k) distance+=(at[k]-position[k])*(at[k]-position[k]);
            if (std::isfinite(distance) && (distance<nearest ||
                (distance==nearest && kind=="markofevil"))) {
                nearest=distance;destroyed=kind=="markofevil_stump";
            }
        }
    }
    return destroyed;
}
bool DeadTreeSpeaker(uint8_t* base, uint32_t speaker) {
    uint32_t type=0,actor=0,flags=0,list=0,voices=0;uint16_t count=0,voice_count=0;
    uint8_t map_only=0,ready=0;std::array<char,128> name{};
    if (base!=kernel::g_base || !Read(base,speaker,type) || type!=0x43B114 ||
        !Read(base,uint64_t(speaker)+0xC,actor) || !actor ||
        !Read(base,uint64_t(actor)+0x90,flags) || !(flags&2) ||
        !Name(base,uint64_t(actor)+0x50,name) || std::string_view(name.data())!="markofevil" ||
        !Read(base,uint64_t(speaker)+0x25,map_only) || map_only ||
        !Read(base,uint64_t(speaker)+0x48,type) || type!=0x43E504 ||
        !Read(base,uint64_t(speaker)+0xB9,ready) || (ready&3)!=3 ||
        !Span(base,uint64_t(speaker)+0x48,0x74) ||
        !Read(base,uint64_t(speaker)+0x70,voice_count) || voice_count>128 ||
        !Read(base,uint64_t(speaker)+0x74,voices) ||
        (voice_count && !Span(base,voices,voice_count*24)) ||
        !Read(base,uint64_t(actor)+0x60,count) || !count || count>128 ||
        !Read(base,uint64_t(actor)+0x64,list) || !Span(base,list,count*8)) return false;
    for (unsigned i=0;i<count;++i) {
        uint32_t entry=0;
        if (Read(base,uint64_t(list)+i*8+4,entry) && entry==speaker) return true;
    }
    return false;
}
}

extern "C" void sub_001D8F0F(X86Context& ctx, uint8_t* base) {
    if (DeadTreeSpeaker(base,ctx.ecx) && ctx.esp>=16384 && Span(base,ctx.esp-16384,16384)) {
        // The native dead-owner query stops only one channel. The tree's mapped
        // emitter voices can occupy either embedded channel or its voice list.
        // Keep the separate sound-map-only explosion speaker untouched.
        std::array<uint8_t,16384> saved;
        std::memcpy(saved.data(),base+ctx.esp-saved.size(),saved.size());
        struct Restore {uint8_t* at;const std::array<uint8_t,16384>& bytes;
            ~Restore(){std::memcpy(at,bytes.data(),bytes.size());}} restore{base+ctx.esp-saved.size(),saved};
        X86Context call=ctx;call.esp-=64;
        __imp__sub_001D8980(call,base);
    }
    __imp__sub_001D8F0F(ctx,base);
}

void DarkwatchMonsterVolume(X86Context& ctx, uint8_t* base) {
    const int percent = darkwatch::MonsterScreamsVolume();
    if (base != kernel::g_base || ctx.ebp < 12) return;
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
    if (bank_name=="emitter_base" && std::string_view(cue_text.data())=="pp_04" &&
        DestroyedTreeAmbience(base,ctx.esi,bank)) {
        gain=0;
        std::memcpy(base+ctx.ebp-12,&gain,sizeof gain);
        return;
    }
    if (percent==100) return;
    const Cue key{bank_name, cue_text.data()};
    const auto less = [](const Cue& a, const Cue& b) {
        return a.bank < b.bank || (a.bank == b.bank && a.name < b.name);
    };
    if (!std::binary_search(std::begin(vocals), std::end(vocals), key, less)) return;
    gain *= float(percent) / 100.f;
    std::memcpy(base + ctx.ebp - 12, &gain, sizeof gain);
}
