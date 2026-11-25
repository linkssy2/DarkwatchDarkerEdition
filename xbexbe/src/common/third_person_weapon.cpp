#include "third_person_weapon.h"
#include "ejected_clips.h"
#include "character_secondary.h"
#include "graphics_camera.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <cmath>
#include <cstring>

extern "C" void __imp__sub_00260D40(X86Context&, uint8_t*);

namespace {
struct Part { const char* weapon; uint32_t bones, bone; std::array<float, 3> seat; float scale; };
constexpr Part parts[]{
#define MECHANICAL_RELOAD_PART(name, count, bone, x, y, z, scale) {name, count, bone, {x,y,z}, scale},
#include "../../../launcher/body_reload_parts.inc"
#undef MECHANICAL_RELOAD_PART
};
bool Span(const uint8_t* base, uint64_t at, uint64_t bytes) {
    if (!base || !at || !bytes || at + bytes > (uint64_t(1) << 32)) return false;
    for (auto page = at & ~(uint64_t(mem::kPage)-1); page < at+bytes; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& value) {
    if (!Span(base, at, sizeof(value))) return false;
    std::memcpy(&value, base+at, sizeof(value)); return true;
}
bool Name(const uint8_t* base, uint64_t at, const char* text) {
    uint32_t pointer = 0;
    const auto size = std::strlen(text)+1;
    return Read(base, at, pointer) && pointer && Span(base, uint64_t(pointer)+2, size) &&
        !std::memcmp(base+uint64_t(pointer)+2, text, size);
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    uint16_t count = 0; uint32_t list = 0, result = 0;
    if (!actor || !Read(base, uint64_t(actor)+0x60, count) || !count || count>128 ||
        !Read(base, uint64_t(actor)+0x64, list) || !Span(base, list, count*8)) return 0;
    for (unsigned i=0; i<count; ++i) {
        uint32_t component=0, type=0, owner=0;
        if (!Read(base, uint64_t(list)+i*8+4, component) || !Read(base, component, type)) return 0;
        if (type!=wanted) continue;
        if (result || !Read(base, uint64_t(component)+0xC, owner) || owner!=actor) return 0;
        result=component;
    }
    return result;
}
bool Reloading(const uint8_t* base, uint32_t controller) {
    // Native 232551 supplies the blend-slot count; 23413B/232E7D queue the
    // row's numeric key. Match a weighted clock, not the row's static flags.
    constexpr unsigned slot_counts[]{4,14,24};
    uint32_t owner=0, mode=0, slots=0, groups=0; uint16_t count=0;
    if (!Read(base, uint64_t(controller)+0xE4, owner) || owner!=controller ||
        !Read(base, uint64_t(controller)+0x160, mode) || mode>=3 ||
        !Read(base, uint64_t(controller)+0xE0, slots) || !Span(base, slots, slot_counts[mode]*0x3C) ||
        !Read(base, uint64_t(controller)+0x28, count) || !count || count>8 ||
        !Read(base, uint64_t(controller)+0x2C, groups) || !Span(base, groups, count*0x3C)) return false;
    for (unsigned g=0; g<count; ++g) {
        uint32_t resource=0, rows=0, group_owner=0; uint16_t row_count=0;
        const uint64_t group=uint64_t(groups)+g*0x3C;
        if (!Read(base, group+0xC, group_owner) || group_owner!=controller ||
            !Read(base, group+0x14, resource) || !resource ||
            !Read(base, resource, row_count) || !row_count || row_count>128 ||
            !Read(base, uint64_t(resource)+4, rows) || !Span(base, rows, row_count*0x8C)) return false;
        for (unsigned r=0; r<row_count; ++r) {
            const uint64_t row=uint64_t(rows)+r*0x8C;
            if (!Name(base, row+0x70, "RELOAD")) continue;
            uint32_t key=0;
            if (!Read(base, row+0x6C, key) || !key) return false;
            for (unsigned s=0; s<slot_counts[mode]; ++s) {
                const uint64_t slot=uint64_t(slots)+s*0x3C;
                uint32_t active=0, clock=0; float weight=0;
                if (!Read(base, slot+0x10, active) || active!=key) continue;
                if (Read(base, slot, weight) && std::isfinite(weight) && weight>0 && weight<=1.001f &&
                    Read(base, slot+0x20, clock) && clock && Span(base, clock, 0x38)) return true;
            }
        }
    }
    return false;
}
const Part* WeaponPart(const uint8_t* base, uint32_t actor, uint32_t hierarchy, uint32_t bones) {
    const uint32_t inventory=Component(base, actor, 0x41F29C);
    uint32_t mode=0, slots=0, categories=0, category=0, slot=0, type=0, owner=0, weapon=0, parent=0;
    uint16_t count=0, categories_count=0;
    if (!inventory || !Read(base, uint64_t(inventory)+0x64, mode) || mode!=0 ||
        !Read(base, uint64_t(inventory)+0x88, count) || !count || count>64 ||
        !Read(base, uint64_t(inventory)+0x8C, slots) || !Span(base, slots, count*4) ||
        !Read(base, uint64_t(inventory)+0x78, categories_count) || !categories_count || categories_count>4 ||
        !Read(base, uint64_t(inventory)+0x7C, categories) || !Read(base, categories, category) || category>=count ||
        !Read(base, uint64_t(slots)+category*4, slot) || !Read(base, slot, type) || type!=0x41F570 ||
        !Read(base, uint64_t(slot)+8, owner) || owner!=inventory ||
        !Name(base, uint64_t(slot)+4, "loc_RightHand") ||
        !Read(base, uint64_t(slot)+0xC, weapon) || !weapon ||
        !Read(base, uint64_t(slot)+0x1C, parent) || parent!=actor) return nullptr;
    const Part* part=nullptr;
    for (const auto& candidate:parts)
        if (candidate.bones==bones && Name(base, uint64_t(weapon)+0x50, candidate.weapon)) part=&candidate;
    if (!part) return nullptr;
    const uint32_t animation=Component(base, weapon, 0x41D258);
    uint32_t pose=0, actual=0, controller=0, controller_pose=0, controller_owner=0, parent_pose=0;
    if (!animation || !Read(base, uint64_t(animation)+0x34, pose) || !pose ||
        !Read(base, pose, parent_pose) || parent_pose ||
        !Read(base, uint64_t(pose)+0x10, actual) || actual!=hierarchy ||
        !Read(base, uint64_t(animation)+0x60, controller) || !controller ||
        !Read(base, uint64_t(controller)+0x88, controller_owner) || controller_owner!=weapon ||
        !Read(base, uint64_t(controller)+0x58, controller_pose) || controller_pose!=pose ||
        !Reloading(base, controller)) return nullptr;
    return part;
}
const Part* Match(const uint8_t* base, uint32_t hierarchy, uint32_t bones) {
    uint32_t game=0, players=0, records=0, seen=0; uint16_t count=0;
    if (!Read(base, 0x4AC9A0, game) || !game ||
        !Read(base, uint64_t(game)+0x44, players) || !players || players>2 ||
        !Read(base, uint64_t(game)+0x50, count) || count<players || count>64 ||
        !Read(base, uint64_t(game)+0x54, records) || !Span(base, records, count*0x130)) return nullptr;
    const Part* result=nullptr;
    for (unsigned i=0; i<count; ++i) {
        uint32_t ordinal=0, actor=0;
        const uint64_t row=uint64_t(records)+i*0x130;
        if (!Read(base, row+0x10C, ordinal)) return nullptr;
        if (ordinal>=players) continue;
        if ((seen&(1u<<ordinal)) || !Read(base, row+0x118, actor) || !actor) return nullptr;
        seen|=1u<<ordinal;
        if (const auto* part=WeaponPart(base, actor, hierarchy, bones)) {
            if (result) return nullptr;
            result=part;
        }
    }
    return seen==(1u<<players)-1 ? result : nullptr;
}
using BodyVector=std::array<float,3>;
float BodyDot(const BodyVector& a,const BodyVector& b){return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
BodyVector BodyCross(const BodyVector& a,const BodyVector& b){return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]};}
bool AlignFirstPersonBody(uint8_t* base,uint32_t matrices,unsigned bones,const DarkwatchFirstPersonFrame& frame){
    BodyVector origin{},old_forward{},target{},old_right{},right{};
    std::memcpy(origin.data(),base+matrices+48,12);
    std::memcpy(old_forward.data(),base+matrices+32,12);
    const float vertical=BodyDot(old_forward,frame.up);
    for(unsigned a=0;a<3;++a)old_forward[a]-=vertical*frame.up[a];
    const float length=std::sqrt(BodyDot(old_forward,old_forward));
    if(!std::isfinite(length)||length<.1f)return false;
    for(auto& v:old_forward)v/=length;
    old_right=BodyCross(frame.up,old_forward);right=BodyCross(frame.up,frame.forward);
    // 30 cm render-only setback keeps the neutral torso outside the native eye;
    // captured 193048/193052 expose shoulder cuts at the anatomical 10 cm seat.
    for(unsigned a=0;a<3;++a)target[a]=frame.eye[a]-.30f*frame.forward[a];
    const float height=BodyDot(origin,frame.up)-BodyDot(target,frame.up);
    float displacement=0;
    for(unsigned a=0;a<3;++a){target[a]+=height*frame.up[a];displacement+=(target[a]-origin[a])*(target[a]-origin[a]);}
    if(!std::isfinite(displacement)||displacement>1.f)return false;
    for(unsigned b=0;b<bones;++b)for(unsigned column=0;column<4;++column){
        BodyVector v{},rotated{};
        const uint32_t at=matrices+b*64+column*16;
        std::memcpy(v.data(),base+at,12);
        for(unsigned a=0;a<3;++a){if(!std::isfinite(v[a]))return false;if(column==3)v[a]-=origin[a];}
        const float x=BodyDot(v,old_right),y=BodyDot(v,frame.up),z=BodyDot(v,old_forward);
        for(unsigned a=0;a<3;++a)rotated[a]=x*right[a]+y*frame.up[a]+z*frame.forward[a]+(column==3?target[a]:0.f);
        std::memcpy(base+at,rotated.data(),12);
    }
    return true;
}
bool SealFirstPersonNeck(uint8_t* base,uint32_t matrices,unsigned bones,uint32_t skin,uint64_t head){
    uint32_t inverse=0;
    if(!head || !Read(base,uint64_t(skin)+0xC,inverse) || !Span(base,inverse,bones*64))return false;
    std::array<float,16> neck{},root_inverse{},root{};
    std::memcpy(neck.data(),base+inverse+9*64,64);
    std::memcpy(root_inverse.data(),base+inverse,64);
    std::memcpy(root.data(),base+matrices,64);
    for(unsigned col=0;col<4;++col)for(unsigned a=0;a<3;++a)
        if(!std::isfinite(neck[col*4+a])||!std::isfinite(root_inverse[col*4+a])||!std::isfinite(root[col*4+a]))return false;
    const BodyVector x{neck[0],neck[1],neck[2]},y{neck[4],neck[5],neck[6]},z{neck[8],neck[9],neck[10]};
    const BodyVector minus_translation{-neck[12],-neck[13],-neck[14]};
    const float determinant=BodyDot(x,BodyCross(y,z));
    if(!std::isfinite(determinant)||std::abs(determinant)<.00001f)return false;
    const BodyVector bind_neck{BodyDot(minus_translation,BodyCross(y,z))/determinant,
        BodyDot(minus_translation,BodyCross(z,x))/determinant,BodyDot(minus_translation,BodyCross(x,y))/determinant};
    BodyVector local{},world{};
    for(unsigned a=0;a<3;++a)local[a]=root_inverse[12+a]+root_inverse[a]*bind_neck[0]+root_inverse[4+a]*bind_neck[1]+root_inverse[8+a]*bind_neck[2];
    for(unsigned a=0;a<3;++a){
        world[a]=root[12+a]+root[a]*local[0]+root[4+a]*local[1]+root[8+a]*local[2];
        if(!std::isfinite(world[a]))return false;
    }
    std::array<float,16> collapsed{};
    std::memcpy(collapsed.data()+12,world.data(),12);
    // Keep the original neck/head transition triangles. Their hidden end meets
    // at the neutral neck instead of leaving an open ring in the chest surface.
    for(unsigned bone=0;bone<bones;++bone)if(head&(uint64_t(1)<<bone))
        std::memcpy(base+matrices+bone*64,collapsed.data(),64);
    return true;
}
}

void DarkwatchWeaponSkinPalette(X86Context& ctx, uint8_t* base) {
    if (DarkwatchEjectedClipSkinPalette(ctx, base)) return;
    uint32_t atomic=0, offset=0, hierarchy=0, flags=0, bones=0, matrices=0, output=0, skin=0, palette_count=0;
    if (base==kernel::g_base && Read(base,uint64_t(ctx.esp)+8,atomic) && atomic &&
        Read(base,0x4BA834,offset) && offset && offset<0x1000 &&
        Read(base,uint64_t(atomic)+offset,hierarchy) && hierarchy) {
        DarkwatchRefreshSecondarySkin(base,hierarchy);
        DarkwatchFirstPersonFrame body_frame{};
        const bool feet=DarkwatchFirstPersonBodyFrame(base,hierarchy,body_frame);
        const uint64_t head=DarkwatchDeathHeadMask(base,hierarchy);
        if ((feet || head) &&
            Read(base,hierarchy,flags) && !(flags&2) &&
            Read(base,uint64_t(hierarchy)+4,bones) && (bones==22 || bones==51) &&
            Read(base,uint64_t(hierarchy)+8,matrices) && Span(base,matrices,bones*64) &&
            Read(base,uint64_t(ctx.esp)+4,output) && Read(base,uint64_t(ctx.esp)+12,skin) && skin &&
            Read(base,uint64_t(skin)+0x81C,palette_count) && palette_count && palette_count<=bones &&
            Span(base,output,palette_count*48) &&
            !(uint64_t(output)<uint64_t(matrices)+bones*64 && uint64_t(matrices)<uint64_t(output)+palette_count*48)) {
            std::array<uint8_t,51*64> saved{};
            std::array<float,16> hidden{};
            std::memcpy(hidden.data()+12,base+matrices+9*64+48,12);
            if (std::isfinite(hidden[12]) && std::isfinite(hidden[13]) && std::isfinite(hidden[14])) {
                const size_t bytes=bones*64;
                std::memcpy(saved.data(),base+matrices,bytes);
                struct Restore {uint8_t* at;const uint8_t* from;size_t size;
                    ~Restore(){std::memcpy(at,from,size);}} restore{base+matrices,saved.data(),bytes};
                if(feet){
                    uint32_t root_slot=palette_count;std::array<uint32_t,51> map{};
                    bool valid=Span(base,uint64_t(skin)+0x1C,palette_count*4),head_only=true;
                    if(valid)std::memcpy(map.data(),base+skin+0x1C,palette_count*4);
                    for(unsigned slot=0;valid && slot<palette_count;++slot){
                        if(map[slot]>=bones)valid=false;
                        if(map[slot]==0)root_slot=slot;
                        if(map[slot]<64 && !(body_frame.head&(uint64_t(1)<<map[slot])))head_only=false;
                    }
                    valid=valid && (root_slot<palette_count || head_only) && AlignFirstPersonBody(base,matrices,bones,body_frame) &&
                        SealFirstPersonNeck(base,matrices,bones,skin,body_frame.head);
                    if(!valid)std::memcpy(base+matrices,saved.data(),bytes);
                    __imp__sub_00260D40(ctx,base);
                    // Root skin transform retains the authored bind geometry:
                    // neutral torso, animated legs, no collapsed shoulder bones.
                    if(valid && root_slot<palette_count)for(unsigned slot=0;slot<palette_count;++slot)
                        if((body_frame.torso&~body_frame.head)&(uint64_t(1)<<map[slot]))
                            std::memcpy(base+output+slot*48,base+output+root_slot*48,48);
                    return;
                }
                // Corpse eyes keep torso/limbs, collapsing only the head and
                // its facial descendants to the neck for this camera's palette.
                for(unsigned bone=0;bone<bones;++bone)
                    if (head&(uint64_t(1)<<bone))
                        std::memcpy(base+matrices+bone*64,hidden.data(),64);
                __imp__sub_00260D40(ctx,base);
                return;
            }
        }
    }
    if (base==kernel::g_base && Read(base, uint64_t(ctx.esp)+8, atomic) && atomic &&
        Read(base, 0x4BA834, offset) && offset && offset<0x1000 &&
        Read(base, uint64_t(atomic)+offset, hierarchy) && hierarchy &&
        Read(base, hierarchy, flags) && !(flags&2) &&
        Read(base, uint64_t(hierarchy)+4, bones) && (bones==4 || bones==5 || bones==8) &&
        Read(base, uint64_t(hierarchy)+8, matrices) && Span(base, matrices, bones*64) &&
        Read(base, uint64_t(ctx.esp)+4, output) &&
        Read(base, uint64_t(ctx.esp)+12, skin) && skin &&
        Read(base, uint64_t(skin)+0x81C, palette_count) && palette_count && palette_count<=bones &&
        Span(base, output, palette_count*48) &&
        !(uint64_t(output)<uint64_t(matrices)+bones*64 && uint64_t(matrices)<uint64_t(output)+palette_count*48)) {
        if (const auto* part=Match(base, hierarchy, bones)) {
            std::array<float,16> root{}, saved{}, adjusted{};
            const uint64_t address=uint64_t(matrices)+part->bone*64;
            std::memcpy(root.data(), base+matrices, sizeof(root));
            std::memcpy(saved.data(), base+address, sizeof(saved));
            adjusted=saved;
            bool valid=true;
            for (unsigned row=0; row<4; ++row) for (unsigned axis=0; axis<3; ++axis)
                valid &= std::isfinite(root[row*4+axis]) && std::isfinite(saved[row*4+axis]);
            for (unsigned axis=0; axis<3; ++axis) {
                const float seat=root[12+axis]+part->seat[0]*root[axis]+
                    part->seat[1]*root[4+axis]+part->seat[2]*root[8+axis];
                adjusted[12+axis]=seat+part->scale*(saved[12+axis]-seat);
                valid &= std::isfinite(adjusted[12+axis]);
            }
            if (valid) {
                // 260D40 copies the current hierarchy into fresh draw constants.
                // Restore the cached pose before the next atomic, camera, or
                // first-person pass; no shared animation/clock is edited.
                struct Restore { uint8_t* at; const std::array<float,16>& saved;
                    ~Restore(){std::memcpy(at,saved.data(),sizeof(saved));} } restore{base+address,saved};
                std::memcpy(base+address, adjusted.data(), sizeof(adjusted));
                __imp__sub_00260D40(ctx, base);
                return;
            }
        }
    }
    __imp__sub_00260D40(ctx, base);
}
