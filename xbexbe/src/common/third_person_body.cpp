#include "third_person_body.h"
#include "graphics_camera.h"
#include "cpu/x86_ops.h"
#include "kernel/memory.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

X86_EXTERN_FUNC(__imp__sub_002312F1);
X86_EXTERN_FUNC(sub_00231B30);
X86_EXTERN_FUNC(sub_002311AA);
X86_EXTERN_FUNC(sub_00231514);

namespace {
bool Span(const uint8_t* base, uint64_t address, uint32_t size) {
    const uint64_t end = address + size;
    if (!base || !address || !size || end > (uint64_t(1) << 32)) return false;
    for (uint64_t page = address & ~(uint64_t(mem::kPage) - 1); page < end; page += mem::kPage)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t Read(const uint8_t* base, uint32_t address) {
    uint32_t value;
    std::memcpy(&value, base + address, sizeof(value));
    return value;
}
uint32_t Component(const uint8_t* base, uint32_t actor, uint32_t wanted) {
    if (!Span(base, actor, 0x68)) return 0;
    uint16_t count;
    std::memcpy(&count, base + actor + 0x60, sizeof(count));
    const uint32_t list = Read(base, actor + 0x64);
    if (!count || count > 128 || !Span(base, list, count * 8)) return 0;
    uint32_t result = 0;
    for (unsigned i = 0; i < count; ++i) {
        const uint32_t component = Read(base, list + i * 8 + 4);
        if (!Span(base, component, 0x10) || Read(base, component) != wanted ||
            Read(base, component + 0xC) != actor) continue;
        if (result) return 0;
        result = component;
    }
    return result;
}

using Quaternion = std::array<float, 4>;
Quaternion QuaternionProduct(const Quaternion& a, const Quaternion& b) {
    return {a[3]*b[0]+a[0]*b[3]+a[1]*b[2]-a[2]*b[1],
            a[3]*b[1]-a[0]*b[2]+a[1]*b[3]+a[2]*b[0],
            a[3]*b[2]+a[0]*b[1]-a[1]*b[0]+a[2]*b[3],
            a[3]*b[3]-a[0]*b[0]-a[1]*b[1]-a[2]*b[2]};
}
bool Normalize(Quaternion& value) {
    float norm = 0;
    for (float v : value) { if (!std::isfinite(v)) return false; norm += v*v; }
    if (!std::isfinite(norm) || std::abs(norm-1) > .02f) return false;
    const float scale = 1/std::sqrt(norm);
    for (float& v : value) v *= scale;
    return true;
}

bool ReadyRoot(unsigned weapon, unsigned stance, Quaternion& reference) {
    // Original AnimationMod Weapons IDs; FLAG has no aimed weapon calibration.
    if (stance > 1 || weapon > 8 || weapon == 3) return false;
    // Full Alert Poses owns the standing root; Alert Poses UB masks it out.
    // Phase .5 matches the ready upper-body basis in all twenty playable rigs.
    if (!stance) {
        if (weapon == 0 || weapon == 8) reference = {-.0600593926f,.2487826039f,-.0086060714f,.9666571372f};
        else if (weapon == 7) reference = {-.0236816717f,.2168276671f,-.0172424531f,.9757702798f};
        else if (weapon == 2 || weapon == 6) reference = {-.0085754043f,-.2597339984f,-.0386045701f,.9648701465f};
        else reference = {-.0198975028f,-.2494206722f,-.0681153714f,.9657917549f};
    } else {
        if (weapon == 0 || weapon == 7 || weapon == 8) reference = {-.1015329275f,.0132210161f,-.0672071143f,.9924713966f};
        else if (weapon == 6) reference = {-.1012301144f,.0128880671f,-.0674712162f,.9924887892f};
        else reference = {-.1013823119f,.0127354300f,-.0677761312f,.9924544482f};
    }
    return true;
}
Quaternion ReferenceBlend(const Quaternion& a, const Quaternion& b, float fraction) {
    float dot = 0;
    for (unsigned i = 0; i < 4; ++i) dot += a[i]*b[i];
    const float sign = dot < 0 ? -1.f : 1.f;
    dot = std::clamp(dot*sign,0.f,1.f);
    float left = 1-fraction, right = fraction;
    // Native 115CB uses shortest-path SLERP, falling back to a near-equal lerp.
    if (1-dot > .00001f) {
        const float sine = std::sqrt(1-dot*dot), angle = std::atan2(sine,dot);
        left = std::sin(angle*left)/sine; right = std::sin(angle*right)/sine;
    }
    Quaternion result{};
    float norm = 0;
    for (unsigned i = 0; i < 4; ++i) { result[i] = a[i]*left+b[i]*right*sign; norm += result[i]*result[i]; }
    const float scale = 1/std::sqrt(norm);
    for (float& value : result) value *= scale;
    return result;
}
bool Name(const uint8_t* base, uint32_t address, const char* name) {
    const uint32_t token = Read(base, address);
    const auto bytes = uint32_t(std::strlen(name) + 1);
    return Span(base, token, bytes + 2) && !std::memcmp(base + token + 2, name, bytes);
}
bool Action(const uint8_t* base, uint32_t row, const char* name) { return Name(base, row + 0x70, name); }
bool AimedMotionAction(const uint8_t* base, uint32_t row) {
    // Ready and the prepared directional/jump rows share this calibration.
    constexpr const char* actions[]{"IDLE", "LOCO_FORWARD", "LOCO_BACKWARD", "LOCO_STRAFE_LEFT",
        "LOCO_STRAFE_RIGHT", "LOCO_STRAFE_LEFT_BACKWARD", "LOCO_STRAFE_RIGHT_BACKWARD",
        "JUMP_ASCENT", "JUMP_DESCENT", "JUMP_LAND", "JUMP_VAMPIREASCENT", "JUMP_VAMPIREHANG"};
    for (const auto* action : actions) if (Action(base, row, action)) return true;
    return false;
}
bool ReloadAction(const uint8_t* base, uint32_t row) {
    return Action(base, row, "PRERELOAD") || Action(base, row, "RELOAD") || Action(base, row, "POSTRELOAD");
}

struct RifleFingerPose {
    uint32_t controller{}, source{}, output{}, local{}, absolute{}, additive{}, secondary{};
    unsigned capacity{}, additive_capacity{};
    bool coop{};
    std::array<bool,6> replace{};
};
bool RifleFingerLayers(const uint8_t* base, RifleFingerPose& pose) {
    constexpr unsigned absolute_capacity[]{1,4,6}, additive_capacity[]{1,3,6};
    const auto mode=Read(base,pose.controller+0x104);
    if (mode>2) return false;
    pose.capacity=absolute_capacity[mode]; pose.additive_capacity=additive_capacity[mode];
    const auto absolute=Read(base,pose.controller+0xF4), additive=Read(base,pose.controller+0xF8);
    const uint64_t abs=uint64_t(absolute)+16*pose.capacity*0x40,
                   add=uint64_t(additive)+16*pose.additive_capacity*0x40;
    if (!absolute || !additive || !Span(base,abs,pose.capacity*0x40) ||
        !Span(base,add,pose.additive_capacity*0x40)) return false;
    pose.absolute=uint32_t(abs); pose.additive=uint32_t(add);
    std::array<uint32_t,6> keys{};
    bool additive_active=false;
    for (unsigned table=0; table<2; ++table) {
        const auto entries=table ? pose.additive : pose.absolute;
        const auto capacity=table ? pose.additive_capacity : pose.capacity;
        for (unsigned i=0; i<capacity; ++i) {
            const auto entry=entries+i*0x40, node=Read(base,entry+0x3C);
            if (!node) break;
            if (!Span(base,node,0x20)) return false;
            float weight; std::memcpy(&weight,base+node,4);
            if (!std::isfinite(weight) || weight<0 || weight>1.001f) return false;
            for (unsigned offset : {0u,0x10u}) {
                Quaternion q; std::memcpy(q.data(),base+entry+offset,sizeof(q));
                if (!Normalize(q)) return false;
            }
            for (unsigned offset : {0x20u,0x30u}) for (unsigned axis=0; axis<3; ++axis) {
                float value; std::memcpy(&value,base+entry+offset+axis*4,4);
                if (!std::isfinite(value) || std::abs(value)>4) return false;
            }
            uint16_t fractions[2]; std::memcpy(fractions,base+entry+0x2C,sizeof(fractions));
            if (fractions[0]>32768 || fractions[1]>32768) return false;
            if (!table) keys[i]=Read(base,node+0x10);
            else additive_active=true;
        }
    }
    // Native 65F85 initializes this identity before the original additive mix.
    if (additive_active && (!Span(base,0x4ACE40,0x14) || !(Read(base,0x4ACE50)&1))) return false;
    uint16_t groups_count; std::memcpy(&groups_count,base+pose.controller+0x28,2);
    const auto groups=Read(base,pose.controller+0x2C);
    if (!groups_count || groups_count>64 || !Span(base,groups,groups_count*0x3C)) return false;
    for (unsigned i=0; i<groups_count; ++i) {
        const auto resource=Read(base,groups+i*0x3C+0x14);
        if (!Span(base,resource,8)) return false;
        uint16_t count; std::memcpy(&count,base+resource,2);
        const auto rows=Read(base,resource+4);
        if (count>256 || (count && !Span(base,rows,count*0x8C))) return false;
        for (unsigned j=0; j<count; ++j) {
            const auto row=rows+j*0x8C, key=Read(base,row+0x6C);
            if (!key || std::find(keys.begin(),keys.end(),key)==keys.end() || !ReloadAction(base,row)) continue;
            uint16_t predicates; std::memcpy(&predicates,base+row+0x80,2);
            const auto flags=Read(base,row+0x84);
            if (predicates<2 || predicates>3 || !Span(base,flags,predicates*8)) continue;
            unsigned signature=0;
            for (unsigned n=0; n<predicates; ++n) {
                const auto category=Read(base,flags+n*8), value=Read(base,flags+n*8+4);
                const unsigned bit=category==0 && value==1 ? 1 :
                    category==8 && value==0 ? 2 : category==2 && value<=1 ? 4 : 0;
                if (!bit || (signature&bit)) { signature=0; break; }
                signature|=bit;
            }
            if (signature!=3 && signature!=7) continue;
            for (unsigned k=0; k<pose.capacity; ++k) if (keys[k]==key) pose.replace[k]=true;
        }
    }
    return std::any_of(pose.replace.begin(),pose.replace.end(),[](bool replace){return replace;});
}
bool RifleFingerSource(const X86Context& ctx, uint8_t* base, uint32_t actor, RifleFingerPose& pose) {
    if (!Span(base,actor,0x68)) return false;
    pose.coop=Name(base,actor+0x50,"CassidySpectralPlayerTwo");
    if (!pose.coop && !Name(base,actor+0x50,"CassidySpectralSolo")) return false;
    const auto animation=Component(base,actor,0x41D258), control=Component(base,actor,0x41F878);
    if (!animation || !control || !Span(base,animation,0xA0) || !Span(base,control,0x2C4) ||
        !(Read(base,animation+0x84)&8) || Read(base,control+0x2C0)!=animation ||
        (Read(base,control+0x254)!=1 && Read(base,control+0x254)!=2) ||
        !DarkwatchThirdPersonPlayer(ctx,base,actor,control)) return false;
    pose.controller=Read(base,animation+0x60);
    if (!Span(base,pose.controller,0x128) || Read(base,pose.controller+0x88)!=actor) return false;
    const auto bones=Read(base,pose.controller+0xFC);
    pose.source=Read(base,pose.controller+0x54); pose.output=Read(base,pose.controller+0x58);
    if (bones!=22 || pose.source!=Read(base,pose.controller+0xF0) ||
        Read(base,animation+0x34)!=pose.output || !Span(base,pose.source,0x18) ||
        !Span(base,pose.output,0x18) || Read(base,pose.source)!=pose.output || Read(base,pose.output)) return false;
    const auto parents=Read(base,pose.output+8), hierarchy=Read(base,pose.output+0x10), masks=Read(base,pose.source+0xC);
    const auto transforms=Read(base,pose.source+0x14);
    if (!Span(base,parents,bones*4) || Read(base,parents+16*4)!=15 ||
        !Span(base,hierarchy,0xC) || Read(base,hierarchy+4)!=bones ||
        !Span(base,masks,bones*4) || (Read(base,masks+16*4)&1) ||
        !Span(base,transforms,bones*0x1C)) return false;
    for (unsigned i=0; i<bones; ++i) if (Read(base,parents+i*4)==16) return false;
    pose.secondary=Read(base,pose.controller+0x5C);
    if (!Span(base,pose.secondary,0x20) || Read(base,pose.secondary)!=pose.output) return false;
    const auto secondary_masks=Read(base,pose.secondary+0xC), secondary_local=Read(base,pose.secondary+0x14);
    if (!Span(base,secondary_masks,bones*4) || !Span(base,secondary_local,bones*0x1C)) return false;
    float time, duration;
    std::memcpy(&time,base+pose.secondary+0x18,4); std::memcpy(&duration,base+pose.secondary+0x1C,4);
    if (!std::isfinite(time) || (time>0 && (!std::isfinite(duration) || duration==0 ||
        !std::isfinite(time/duration)))) return false;
    if (!(Read(base,secondary_masks+16*4)&1)) {
        Quaternion q; std::memcpy(q.data(),base+secondary_local+16*0x1C,sizeof(q));
        if (!Normalize(q)) return false;
        for (unsigned i=4; i<7; ++i) {
            float value; std::memcpy(&value,base+secondary_local+16*0x1C+i*4,4);
            if (!std::isfinite(value) || std::abs(value)>4) return false;
        }
    }
    pose.local=transforms+16*0x1C;
    return RifleFingerLayers(base,pose);
}
bool PublicationFinger(const X86Context& ctx, uint8_t* base, uint32_t& address,
                       std::array<float,7>& saved, std::array<float,7>& corrected) {
    if (!Span(base,ctx.esp,8) || (Read(base,ctx.esp)!=0x21CE42 && Read(base,ctx.esp)!=0x21CEC1) ||
        !Span(base,ctx.edi,0x128) || ctx.esp<2048 || !Span(base,ctx.esp-2048,2048)) return false;
    RifleFingerPose pose;
    if (!RifleFingerSource(ctx,base,Read(base,ctx.edi+0x88),pose) || pose.controller!=ctx.edi ||
        Read(base,ctx.esp+4)!=pose.source || ctx.ecx!=pose.output) return false;
    // Reuse the native one-bone mix, preserving fades, other weapons and all
    // additive layers. Only the rifle reload's finger samples become neutral.
    std::array<uint8_t,2048> scratch_before;
    const auto scratch=ctx.esp-2048, packet=scratch+1280, source=scratch+1312,
               result=scratch+1344, entries=scratch+1408;
    std::memcpy(scratch_before.data(),base+scratch,scratch_before.size());
    struct Restore {
        uint8_t* where; const std::array<uint8_t,2048>& bytes;
        ~Restore(){std::memcpy(where,bytes.data(),bytes.size());}
    } restore{base+scratch,scratch_before};
    const uint32_t header[]{source,entries,pose.additive,1,Read(base,pose.controller+0x100),Read(base,pose.controller+0x104)};
    std::memcpy(base+packet,header,sizeof(header));
    std::memcpy(base+source,base+pose.source,0x18); std::memcpy(base+source+0x14,&result,4);
    std::memcpy(saved.data(),base+pose.local,sizeof(saved));
    std::memcpy(base+result,saved.data(),sizeof(saved));
    std::memcpy(base+entries,base+pose.absolute,pose.capacity*0x40);
    constexpr Quaternion neutral{.6987348698f,.0068054628f,-.0191346420f,.7150923947f};
    const std::array<float,3> position=pose.coop ? std::array<float,3>{.1248203889f,.0051895115f,-.0234911013f} :
        std::array<float,3>{.1248202920f,.0051895152f,-.0234910399f};
    for (unsigned i=0; i<pose.capacity; ++i) if (pose.replace[i]) {
        for (unsigned offset : {0u,0x10u}) std::memcpy(base+entries+i*0x40+offset,neutral.data(),sizeof(neutral));
        for (unsigned offset : {0x20u,0x30u}) std::memcpy(base+entries+i*0x40+offset,position.data(),sizeof(position));
    }
    X86Context call=ctx; call.esp=scratch+1024; call.ecx=packet;
    const uint32_t caller=0x21CDF7; std::memcpy(base+call.esp,&caller,4);
    sub_00231B30(call,base);
    // 21CDC3 applies this secondary pose after the layer mix. Replay its native
    // masks and interpolation too, so crouch/action fades remain authoritative.
    const auto secondary=scratch+1792, secondary_local=scratch+1824,
               parent=scratch+1856, hierarchy=scratch+1880, masks=scratch+1892;
    std::memset(base+parent,0,40);
    std::memcpy(base+parent+0x10,&hierarchy,4);
    const uint32_t one=1;
    std::memcpy(base+hierarchy+4,&one,4);
    std::memcpy(base+source,&parent,4); std::memcpy(base+source+0xC,&masks,4);
    const uint32_t primary_mask=Read(base,Read(base,pose.source+0xC)+16*4), secondary_mask=masks+4;
    std::memcpy(base+masks,&primary_mask,4);
    std::memcpy(base+secondary,base+pose.secondary,0x20);
    std::memcpy(base+secondary,&parent,4); std::memcpy(base+secondary+0xC,&secondary_mask,4);
    std::memcpy(base+secondary+0x14,&secondary_local,4);
    std::memcpy(base+secondary_mask,base+Read(base,pose.secondary+0xC)+16*4,4);
    std::memcpy(base+secondary_local,base+Read(base,pose.secondary+0x14)+16*0x1C,0x1C);
    call=ctx; call.esp=scratch+1024; call.ecx=secondary;
    std::memcpy(base+call.esp,&caller,4); sub_002311AA(call,base);
    const double ratio=call.st[call.top];
    const float fraction=float(ratio);
    call=ctx; call.esp=scratch+1024;
    if (ratio>0) {
        const uint32_t args[]{caller,source,secondary,source};
        std::memcpy(base+call.esp,args,sizeof(args)); std::memcpy(base+call.esp+16,&fraction,4);
        sub_00231514(call,base);
    } else {
        const uint32_t args[]{caller,secondary}; std::memcpy(base+call.esp,args,sizeof(args));
        call.ecx=source; __imp__sub_002312F1(call,base);
    }
    std::memcpy(corrected.data(),base+result,sizeof(corrected));
    Quaternion q{corrected[0],corrected[1],corrected[2],corrected[3]};
    if (!Normalize(q)) return false;
    for (unsigned i=4; i<7; ++i) if (!std::isfinite(corrected[i]) || std::abs(corrected[i])>4) return false;
    address=pose.local;
    return true;
}

unsigned HitAction(const uint8_t* base, uint32_t row) {
    constexpr const char* actions[]{"HIT_FRONT", "HIT_BACK", "HIT_LEFT", "HIT_RIGHT"};
    for (unsigned i = 0; i < 4; ++i) if (Action(base, row, actions[i])) return 1u << i;
    return 0;
}
bool HitRoute(const uint8_t* base, uint32_t row, unsigned direction, unsigned& weapons, bool& owns_root) {
    constexpr unsigned stand=1u<<9, crouch=1u<<10, stopped=1u<<11, moving=1u<<12,
                       ground=1u<<13, foot=1u<<14;
    // Exact solo/co-op armed-hit selectors. Flag, turret, death and other
    // authored reactions retain the original publication path.
    struct Route { unsigned signature, directions; bool root; };
    constexpr Route routes[]{
        {0x101|foot,15,false}, {0x12|foot,15,false}, {0x80|foot,15,false},
        {0x24,15,false}, {0x40,15,false},
        {0x24|crouch|stopped|ground|foot,1,false},
        {0x40|crouch|stopped|ground|foot,3,true},
        {0x181|stand|stopped|foot,15,true}, {0x181|crouch|stopped|ground|foot,3,true},
        {0x181|stand|moving,15,false}, {0x36|stand|stopped|foot,15,true},
        {0x34|crouch|stopped|ground|foot,1,false}, {0x36|moving,15,false},
        {0x40|stand|stopped|foot,15,true}, {0x40|stand|moving,15,false},
    };
    uint16_t count;
    std::memcpy(&count, base + row + 0x80, sizeof(count));
    const uint32_t predicates = Read(base, row + 0x84);
    if (!count || count > 7 || !Span(base, predicates, count*8)) return false;
    unsigned signature = 0;
    for (unsigned i = 0; i < count; ++i) {
        const auto category=Read(base,predicates+i*8), value=Read(base,predicates+i*8+4);
        unsigned bit = 0;
        if (category==0 && value<=8 && value!=3) bit=1u<<value;
        else if (category==2 && value<=1) bit=stand<<value;
        else if (category==3 && value<=1) bit=stopped<<value;
        else if (category==4 && value==0) bit=ground;
        else if (category==8 && value==0) bit=foot;
        if (!bit || (signature&bit)) return false;
        signature |= bit;
    }
    for (const auto& route : routes) if (route.signature==signature && (route.directions&direction)) {
        weapons=signature&0x1FF; owns_root=route.root; return true;
    }
    return false;
}

bool SampleHitRoot(const uint8_t* base, uint32_t controller, uint32_t node, Quaternion& reference) {
    constexpr unsigned capacities[]{1,4,6};
    const auto mode=Read(base,controller+0x104), entries=Read(base,controller+0xF4);
    if (mode>2 || !Span(base,entries,capacities[mode]*0x40)) return false;
    bool found = false;
    for (unsigned i=0; i<capacities[mode]; ++i) {
        const auto entry=entries+i*0x40, candidate=Read(base,entry+0x3C);
        if (!candidate) break;
        if (candidate!=node) continue;
        if (found) return false;
        Quaternion first{}, second{}; uint16_t fraction;
        std::memcpy(first.data(),base+entry,sizeof(first));
        std::memcpy(second.data(),base+entry+0x10,sizeof(second));
        std::memcpy(&fraction,base+entry+0x2C,sizeof(fraction));
        if (fraction>32768 || !Normalize(first) || !Normalize(second)) return false;
        // 231BF4/BD580 interpolate this same root sample before priority fades.
        reference=ReferenceBlend(first,second,float(fraction)/32768.f);
        found=true;
    }
    return found;
}

struct RootLayer { uint32_t key{}, flags{}; float weight{}; Quaternion reference{}; bool active = false, resolved = false; };
bool RootReference(const uint8_t* base, uint32_t controller, Quaternion& reference, unsigned stance_weapon = 9) {
    // 231B64-6D indexes F4 by bone*absolute_capacity*0x40. Bone 7 owns the
    // ready upper-body calibration, including independent weapon/stance fades.
    // Root/leg movement entries can lack weapon selectors; additive AIM_POSE
    // entries at F8 must not become part of this neutral reference.
    const uint32_t mode = Read(base, controller + 0x104);
    constexpr unsigned capacities[]{1,4,6};
    const uint32_t bones = Read(base, controller + 0xFC);
    if (mode > 2 || bones < 8 || bones > 64) return false;
    const unsigned capacity = capacities[mode];
    // Shared reload/melee clips mask their root and have no stance selector. For
    // those clips only, reuse the native lower-body stance blend for this gun.
    const bool lower_body = stance_weapon < 9;
    const uint64_t start = uint64_t(Read(base, controller + 0xF4)) + (lower_body ? 0 : 7) * capacity * 0x40;
    if (!Read(base, controller + 0xF4) || !Span(base, start, capacity * 0x40)) return false;
    const uint32_t entries = uint32_t(start);
    std::array<RootLayer, 6> layers{};
    unsigned count = 0;
    for (unsigned i = 0; i < capacity; ++i) {
        const uint32_t node = Read(base, entries + i * 0x40 + 0x3C);
        if (!node) break;
        if (!Span(base, node, 0x20)) return false;
        RootLayer& layer = layers[count++];
        layer.key = Read(base, node + 0x10); layer.flags = Read(base, node + 0x1C);
        std::memcpy(&layer.weight, base + node, sizeof(float));
        if (!std::isfinite(layer.weight) || layer.weight < 0 || layer.weight > 1.001f) return false;
    }
    if (!count || layers[0].weight < .001f) return false;
    // 231AB8 priority normalization includes the suffix even when an override
    // hides it; only effective layers need a neutral-pose reference.
    std::array<float, 6> weights{};
    float suffix = .001f;
    for (unsigned i = count; i-- > 0;) {
        const auto& layer = layers[i];
        weights[i] = (layer.flags & 0x10) ? layer.weight / std::max(.001f, 1-layer.weight) * suffix : layer.weight;
        suffix += weights[i];
    }
    unsigned remaining = 0;
    for (unsigned i = 0; i < count; ++i) {
        if (i && (layers[i-1].flags & 0x10) && layers[i-1].weight >= .999f) break;
        if (weights[i] > 0) {
            if (!layers[i].key) return false;
            layers[i].active = true; ++remaining;
        }
    }
    uint16_t groups_count;
    std::memcpy(&groups_count, base + controller + 0x28, sizeof(groups_count));
    const uint32_t groups = Read(base, controller + 0x2C);
    if (!groups_count || groups_count > 64 || !Span(base, groups, groups_count * 0x3C)) return false;
    for (unsigned i = 0; i < groups_count && remaining; ++i) {
        const uint32_t resource = Read(base, groups + i * 0x3C + 0x14);
        if (!Span(base, resource, 8)) return false;
        uint16_t row_count;
        std::memcpy(&row_count, base + resource, sizeof(row_count));
        const uint32_t rows = Read(base, resource + 4);
        if (row_count > 256 || (row_count && !Span(base, rows, row_count * 0x8C))) return false;
        for (unsigned j = 0; j < row_count && remaining; ++j) {
            const uint32_t row = rows + j * 0x8C, key = Read(base, row + 0x6C);
            for (unsigned k = 0; k < count; ++k) {
                auto& layer = layers[k];
                if (!layer.active || layer.resolved || layer.key != key) continue;
                const bool reload = !lower_body && ReloadAction(base, row);
                const bool fan = !lower_body && Action(base, row, "ALT_SHOOT");
                const bool melee = !lower_body && Action(base, row, "MELEE_ATTACK");
                const unsigned hit = HitAction(base, row);
                if (hit) {
                    unsigned weapons=0; bool owns_root=false;
                    if (!(layer.flags&0x10) || !HitRoute(base,row,hit,weapons,owns_root) ||
                        (lower_body && !owns_root)) return false;
                    if (owns_root) {
                        if (!SampleHitRoot(base,controller,Read(base,entries+k*0x40+0x3C),layer.reference)) return false;
                    } else {
                        // Shared shotgun/crossbow and co-op hit rows span
                        // different ready bases; use the native equipped gun.
                        if (!Span(base,uint64_t(controller)+0x144,4)) return false;
                        const auto selectors=Read(base,controller+0x144);
                        if (!Span(base,selectors,4)) return false;
                        const auto weapon=Read(base,selectors);
                        if (weapon>8 || !(weapons&(1u<<weapon)) ||
                            !RootReference(base,controller,layer.reference,weapon)) return false;
                    }
                    layer.resolved=true; --remaining;
                    continue;
                }
                if (!AimedMotionAction(base, row) && !reload && !fan && !melee &&
                    !(lower_body && (Action(base, row, "LOCO_TURNLEFT") || Action(base, row, "LOCO_TURNRIGHT")))) return false;
                uint16_t predicates;
                std::memcpy(&predicates, base + row + 0x80, sizeof(predicates));
                const uint32_t flags = Read(base, row + 0x84);
                if (!predicates || predicates > 32 || !Span(base, flags, predicates * 8)) return false;
                unsigned weapons = 0, stance = 2;
                bool airborne = false, on_foot = false;
                for (unsigned n = 0; n < predicates; ++n) {
                    const uint32_t category = Read(base, flags + n * 8), value = Read(base, flags + n * 8 + 4);
                    if (category == 0) {
                        if (value > 8 || value == 3) return false;
                        weapons |= 1u << value;
                    } else if (category == 2) {
                        if (value > 1 || stance != 2) return false;
                        stance = value;
                    } else if (category == 4 && value == 1) airborne = true;
                    else if (category == 8 && value == 0) on_foot = true;
                }
                if (fan) {
                    // The two native hammer-fan rows override bone 7, mask the
                    // root and select only their pistol. Their shared standing
                    // basis must not inherit running/jumping root rotation.
                    if (predicates != 1 || (weapons != 1 && weapons != (1u << 8)) ||
                        !(layer.flags & 0x10) || !ReadyRoot(0, 0, layer.reference)) return false;
                    layer.resolved = true; --remaining;
                    continue;
                }
                if (melee) {
                    // Native weapon-melee overrides own the complete swing,
                    // but mask the locomotion root. Preserve that swing in
                    // the same neutral stance as an idle player, not the
                    // currently turning/airborne legs. Shared pistol/rifle
                    // selectors have identical ready roots for both guns.
                    const bool paired = weapons == ((1u << 0) | (1u << 8)) ||
                                        weapons == ((1u << 1) | (1u << 4));
                    const bool shared = paired || weapons == (1u << 2) ||
                                        weapons == (1u << 5) || weapons == (1u << 7);
                    if (!on_foot || !(layer.flags & 0x10) ||
                        (shared ? stance != 2 || predicates != (paired ? 3 : 2) :
                                  weapons != (1u << 6) || stance == 2 || predicates != 3)) return false;
                    if (shared) {
                        unsigned weapon = 0;
                        while (!(weapons & (1u << weapon))) ++weapon;
                        if (!RootReference(base, controller, layer.reference, weapon)) return false;
                        layer.resolved = true; --remaining;
                        continue;
                    }
                }
                // This native rocket-descent row omits stance; its prepared
                // upper-body pose explicitly uses standing ready on all rigs.
                if (stance == 2 && weapons == (1u << 6) && predicates == 3 && airborne && on_foot &&
                    Action(base, row, "JUMP_DESCENT")) stance = 0;
                if ((reload || lower_body) && !on_foot) return false;
                if (reload && stance == 2) {
                    // Only these native phase-only UB routes omit stance;
                    // never interpret an unknown action's missing predicate.
                    const bool shared = weapons == (1u << 1) || weapons == (1u << 2) ||
                        ((weapons == (1u << 7) || weapons == (1u << 8)) && Action(base, row, "RELOAD"));
                    if (!shared || predicates != 2) return false;
                    unsigned weapon = 0;
                    while (!(weapons & (1u << weapon))) ++weapon;
                    if (!RootReference(base, controller, layer.reference, weapon)) return false;
                    layer.resolved = true; --remaining;
                    continue;
                }
                if (lower_body) weapons = 1u << stance_weapon;
                if (!weapons || stance == 2) return false;
                for (unsigned weapon = 0; weapon <= 8; ++weapon) if (weapons & (1u << weapon)) {
                    Quaternion ready{};
                    if (!ReadyRoot(weapon,stance,ready) || (layer.resolved && ready != layer.reference)) return false;
                    layer.reference = ready; layer.resolved = true;
                }
                --remaining;
            }
        }
    }
    if (remaining) return false;
    // Original 231B30 ordered quaternion SLERPs, after priority normalization.
    float total = weights[0];
    Quaternion ready = layers[0].reference;
    for (unsigned i = 1; i < count; ++i) {
        if ((layers[i-1].flags & 0x10) && layers[i-1].weight >= .999f) break;
        total += weights[i];
        if (total > 0 && layers[i].active) ready = ReferenceBlend(ready,layers[i].reference,weights[i]/total);
    }
    reference = ready;
    return true;
}

bool PublicationSpine(const X86Context& ctx, uint8_t* base, uint32_t& address,
                      Quaternion& saved, Quaternion& corrected) {
    if (!Span(base, ctx.esp, 8)) return false;
    // Native 21CDC3 retains its owning controller in EDI at both publications.
    // Render-time animation updates also reach these calls after the camera
    // refresh; every publication must use the same pose for body and attachments.
    const uint32_t caller = Read(base, ctx.esp), controller = ctx.edi;
    if ((caller != 0x21CE42 && caller != 0x21CEC1) || !Span(base, controller, 0x128)) return false;
    const uint32_t actor = Read(base, controller + 0x88);
    const uint32_t animation = Component(base, actor, 0x41D258), control = Component(base, actor, 0x41F878);
    if (!animation || !control || !Span(base, animation, 0xA0) || !Span(base, control, 0x2C4) ||
        Read(base, animation + 0x60) != controller || !(Read(base, animation + 0x84) & 8) ||
        Read(base, control + 0x2C0) != animation ||
        (Read(base, control + 0x254) != 1 && Read(base, control + 0x254) != 2) ||
        !DarkwatchThirdPersonPlayer(ctx, base, actor, control)) return false;
    const uint32_t source = Read(base, ctx.esp + 4), output = ctx.ecx;
    const uint32_t bones = Read(base, controller + 0xFC);
    if ((bones != 22 && bones != 51) || source != Read(base, controller + 0x54) ||
        source != Read(base, controller + 0xF0) || output != Read(base, controller + 0x58) ||
        !Span(base, source, 0x18) || !Span(base, output, 0x18) || Read(base, output) ||
        Read(base, source) != output) return false;
    // 231055/23109A and 21A4B0 define the root hierarchy and parent table.
    const uint32_t parents = Read(base, output + 8), hierarchy = Read(base, output + 0x10);
    const uint32_t masks = Read(base, source + 0xC), transforms = Read(base, source + 0x14);
    if (!Span(base, parents, bones*4) || int32_t(Read(base, parents)) >= 0 || Read(base, parents + 7*4) ||
        !Span(base, hierarchy, 0xC) || Read(base, hierarchy + 4) != bones ||
        !Span(base, masks, bones*4) || ((Read(base, masks) | Read(base, masks + 7*4)) & 1) ||
        !Span(base, transforms, bones*0x1C)) return false;
    Quaternion root;
    address = transforms + 7*0x1C;
    std::memcpy(root.data(), base + transforms, sizeof(root));
    std::memcpy(saved.data(), base + address, sizeof(saved));
    corrected = saved;
    if (!Normalize(root) || !Normalize(corrected)) return false;
    for (unsigned i = 0; i < 3; ++i) root[i] = -root[i];
    Quaternion reference{};
    if (!RootReference(base, controller, reference)) return false;
    // Row matrices: spine' = spine * ready_root * inverse(animated_root).
    // Preserve the native legs/root and the fully blended additive aim pose.
    corrected = QuaternionProduct(QuaternionProduct(root, reference), corrected);
    return Normalize(corrected);
}

float SmoothStep(float low, float high, float value) {
    value = std::clamp((value-low)/(high-low), 0.f, 1.f);
    return value*value*(3-2*value);
}
bool SpreadSpineHeading(Quaternion root, Quaternion spine, Quaternion chest,
                        const std::array<float,3>& segment, const Quaternion& corrected,
                        Quaternion& lower, Quaternion& upper) {
    if (!Normalize(root) || !Normalize(spine) || !Normalize(chest)) return false;
    const Quaternion world = QuaternionProduct(root, corrected);
    Quaternion inverse_world = world;
    for (unsigned i=0; i<3; ++i) inverse_world[i] = -inverse_world[i];
    const auto lever = QuaternionProduct(QuaternionProduct(world,
        {segment[0],segment[1],segment[2],0}), inverse_world);
    const float length = lever[0]*lever[0]+lever[1]*lever[1]+lever[2]*lever[2];
    if (!std::isfinite(length) || length < .000001f) return false;
    // Authored standing chest slopes are .045-.279; all crouched weapon
    // references are .589-.919. Keep bent poses intact through stance fades.
    const float upright = 1-SmoothStep(.35f,.55f,
        std::sqrt((lever[0]*lever[0]+lever[2]*lever[2])/length));
    Quaternion before = QuaternionProduct(root, spine);
    for (unsigned i=0; i<3; ++i) before[i] = -before[i];
    const auto difference = QuaternionProduct(world, before);
    const float yaw_length = difference[1]*difference[1]+difference[3]*difference[3];
    if (!std::isfinite(yaw_length) || yaw_length < .000001f) return false;
    const float scale = 1/std::sqrt(yaw_length);
    const Quaternion yaw{0,difference[1]*scale,0,difference[3]*scale};
    const float degrees = 114.591559f*std::acos(std::clamp(std::abs(yaw[3]),0.f,1.f));
    const float weight = upright*SmoothStep(55,90,degrees)*(1-SmoothStep(150,180,degrees));
    if (weight <= 0) return false;
    // Only heading is shared. Near a half-turn its share fades to zero so the
    // shortest-path quaternion hemisphere cannot flip the waist in a blend.
    const auto turn = ReferenceBlend({0,0,0,1},yaw,-2.f/3*weight);
    for (unsigned i=0; i<3; ++i) root[i] = -root[i];
    lower = QuaternionProduct(root,QuaternionProduct(turn,world));
    auto inverse_lower = lower;
    for (unsigned i=0; i<3; ++i) inverse_lower[i] = -inverse_lower[i];
    // Both clavicles descend from chest 8, not neck 9. Preserve their complete
    // final orientation and relative grips; native translations/legs are kept.
    upper = QuaternionProduct(inverse_lower,QuaternionProduct(corrected,chest));
    return Normalize(lower) && Normalize(upper);
}
bool PublicationChest(const X86Context& ctx, uint8_t* base, uint32_t address,
                      const Quaternion& spine, Quaternion& corrected,
                      Quaternion& saved_chest, Quaternion& corrected_chest) {
    // PublicationSpine already validated this controller's full local arrays.
    const auto parents = Read(base,ctx.ecx+8), source = Read(base,ctx.esp+4);
    const auto masks = Read(base,source+0xC);
    if (Read(base,parents+8*4)!=7 || Read(base,parents+9*4)!=8 ||
        Read(base,parents+12*4)!=8 || Read(base,parents+17*4)!=8 ||
        (Read(base,masks+8*4)&1)) return false;
    Quaternion root{}, lower{};
    std::array<float,3> segment{};
    std::memcpy(root.data(),base+address-7*0x1C,sizeof(root));
    std::memcpy(saved_chest.data(),base+address+0x1C,sizeof(saved_chest));
    std::memcpy(segment.data(),base+address+0x1C+0x10,sizeof(segment));
    if (!SpreadSpineHeading(root,spine,saved_chest,segment,corrected,lower,corrected_chest)) return false;
    corrected = lower;
    return true;
}

void RefreshHeldAttachments(const X86Context& ctx, uint8_t* base, uint32_t controller) {
    const uint32_t actor = Read(base, controller + 0x88);
    const uint32_t animation = Component(base, actor, 0x41D258);
    const uint32_t inventory = Component(base, actor, 0x41F29C);
    const uint32_t locator = Component(base, actor, 0x422590);
    if (!animation || !inventory || !locator || !Span(base, animation, 0x64) ||
        Read(base, animation + 0x60) != controller ||
        Read(base, animation + 0x34) != Read(base, controller + 0x58) ||
        !Span(base, inventory, 0x90) || Read(base, inventory + 0x64) ||
        !Span(base, locator, 0x28) || ctx.esp < 2048 || !Span(base, ctx.esp - 2048, 2048)) return;
    uint16_t slots_count, categories_count, rows_count;
    std::memcpy(&slots_count, base + inventory + 0x88, 2);
    std::memcpy(&categories_count, base + inventory + 0x78, 2);
    std::memcpy(&rows_count, base + locator + 0x20, 2);
    const uint32_t slots = Read(base, inventory + 0x8C), categories = Read(base, inventory + 0x7C);
    const uint32_t rows = Read(base, locator + 0x24), bones = Read(base, controller + 0xFC);
    if (!slots_count || slots_count > 64 || !Span(base, slots, slots_count*4) ||
        !categories_count || categories_count > 4 || !Span(base, categories, categories_count*4) ||
        !rows_count || rows_count > 128 || !Span(base, rows, rows_count*0x40)) return;
    const uint32_t selected = Read(base, categories);
    if (selected >= slots_count) return;
    auto held = [&](uint32_t slot, const char* name) -> uint32_t {
        if (!Span(base, slot, 0x20) || Read(base, slot) != 0x41F570 ||
            Read(base, slot + 8) != inventory || Read(base, slot + 0x1C) != actor ||
            !Name(base, slot + 4, name)) return 0;
        const uint32_t child = Read(base, slot + 0xC);
        return child != actor && Span(base, child, 0x90) ? child : 0;
    };
    const uint32_t primary = held(Read(base, slots + selected*4), "loc_RightHand");
    if (!primary) return;
    uint32_t secondary = 0;
    if (Name(base, primary + 0x50, "DoublePistol")) {
        for (unsigned i = 0; i < slots_count; ++i) {
            const uint32_t child = held(Read(base, slots + i*4), "loc_LeftHandDualWield");
            if (child) { if (secondary || child == primary) return; secondary = child; }
        }
    }
    std::array<uint32_t,2> attachments{};
    for (unsigned i = 0; i < rows_count; ++i) {
        const uint32_t row = rows + i*0x40;
        const unsigned hand = Name(base, row + 0x10, "loc_RightHand") ? 0 :
            Name(base, row + 0x10, "loc_LeftHandDualWield") ? 1 : 2;
        const uint32_t child = hand == 0 ? primary : secondary;
        if (hand > 1 || !child) continue;
        if (attachments[hand] || !base[row + 0xC] || Read(base, row + 8) >= bones) return;
        uint16_t count;
        std::memcpy(&count, base + row, 2);
        const uint32_t refs = Read(base, row + 4);
        if (!count || count > 64 || !Span(base, refs, count*16)) return;
        unsigned matches = 0;
        for (unsigned j = 0; j < count; ++j) {
            const uint32_t attached = Read(base, refs + j*16);
            if (attached && (attached != child || ++matches > 1)) return;
        }
        if (matches != 1) return;
        attachments[hand] = row;
    }
    // The native pre-render path publishes again after its locator update.
    // Refresh only the held children, through AA19F/216244 and the existing grip
    // adjustment; no actor messages, animation clocks or weapon events replay.
    std::array<uint8_t,2048> saved;
    const uint32_t scratch = ctx.esp - uint32_t(saved.size());
    std::memcpy(saved.data(), base + scratch, saved.size());
    struct Restore {
        uint8_t* where; const std::array<uint8_t,2048>& saved;
        ~Restore() { std::memcpy(where, saved.data(), saved.size()); }
    } restore{base + scratch, saved};
    for (const auto row : attachments) if (row) {
        X86Context call = ctx;
        call.esp -= 64;
        call.ecx = row;
        const uint32_t args[]{0xAA5E6, actor, animation + 0x30};
        std::memcpy(base + call.esp, args, sizeof(args));
        x86_icall(call, base, 0xAA19F);
    }
}
}

X86_FUNC(sub_002312F1) {
    uint32_t finger_address=0;
    std::array<float,7> finger_saved{}, finger_corrected{};
    const bool finger=PublicationFinger(ctx,base,finger_address,finger_saved,finger_corrected);
    auto publish = [&] {
        struct Restore {
            uint8_t* where; const std::array<float,7>& pose; bool changed;
            ~Restore(){if(changed)std::memcpy(where,pose.data(),sizeof(pose));}
        } restore{base+finger_address,finger_saved,finger};
        if(finger)std::memcpy(base+finger_address,finger_corrected.data(),sizeof(finger_corrected));
        __imp__sub_002312F1(ctx,base);
    };
    uint32_t address = 0;
    Quaternion saved{}, corrected{};
    if (!PublicationSpine(ctx, base, address, saved, corrected)) {
        const uint32_t controller=ctx.edi;
        publish();
        if(finger)RefreshHeldAttachments(ctx,base,controller);
        return;
    }
    const uint32_t controller = ctx.edi;
    Quaternion saved_chest{}, corrected_chest{};
    const bool spread = PublicationChest(ctx,base,address,saved,corrected,saved_chest,corrected_chest);
    {
        struct Restore {
            uint8_t* where; const Quaternion& saved; const Quaternion& chest; bool spread;
            ~Restore() {
                std::memcpy(where, saved.data(), sizeof(saved));
                if (spread) std::memcpy(where+0x1C,chest.data(),sizeof(chest));
            }
        } restore{base + address, saved, saved_chest, spread};
        std::memcpy(base + address, corrected.data(), sizeof(corrected));
        if (spread) std::memcpy(base+address+0x1C,corrected_chest.data(),sizeof(corrected_chest));
        publish();
    }
    RefreshHeldAttachments(ctx, base, controller);
}

bool DarkwatchRifleReloadSocket(const X86Context& ctx, uint8_t* base, uint32_t actor,
                               std::array<float,16>& world) {
    RifleFingerPose pose;
    if(!RifleFingerSource(ctx,base,actor,pose))return false;
    const auto hierarchy=Read(base,pose.output+0x10), matrices=Read(base,hierarchy+8);
    const uint64_t wrist=uint64_t(matrices)+15*64;
    if(!matrices || !Span(base,wrist,64))return false;
    Quaternion q;
    std::array<float,3> position;
    std::array<float,16> hand;
    std::memcpy(q.data(),base+pose.local,sizeof(q));
    std::memcpy(position.data(),base+pose.local+16,sizeof(position));
    std::memcpy(hand.data(),base+wrist,sizeof(hand));
    if(!Normalize(q))return false;
    for(float value:position)if(!std::isfinite(value)||std::abs(value)>4)return false;
    for(unsigned r=0;r<4;++r)for(unsigned a=0;a<3;++a)if(!std::isfinite(hand[r*4+a]))return false;
    const auto [x,y,z,w]=q;
    const float local[3][3]{{1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w)},
        {2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w)},
        {2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y)}};
    std::array<float,16> result{};
    for(unsigned r=0;r<3;++r)for(unsigned a=0;a<3;++a)
        for(unsigned k=0;k<3;++k)result[r*4+a]+=local[r][k]*hand[k*4+a];
    for(unsigned a=0;a<3;++a){
        result[12+a]=hand[12+a];
        for(unsigned k=0;k<3;++k)result[12+a]+=position[k]*hand[k*4+a];
    }
    world=result;
    return true;
}

void DarkwatchThirdPersonBodyAim(const X86Context& ctx, uint8_t* base, uint32_t actor) {
    const uint32_t control = Component(base, actor, 0x41F878);
    const uint32_t animation = Component(base, actor, 0x41D258);
    if (!control || !animation || !Span(base, control, 0x2C4) ||
        !Span(base, animation, 0xA0) || ctx.esp < 2048 ||
        !Span(base, ctx.esp - 2048, 2048)) return;
    const uint32_t driver = control + 0x1E8;
    const uint32_t mode = Read(base, driver + 0x6C);
    const uint32_t controller = Read(base, animation + 0x60);
    if ((mode != 1 && mode != 2) || Read(base, driver + 0xD8) != animation ||
        !(Read(base, animation + 0x84) & 8) || !Span(base, controller, 0x128) ||
        Read(base, controller + 0x88) != actor) return;
    std::array<float, 3> origin{}, original{}, facing{}, target{}, direction{};
    std::memcpy(origin.data(), base + control + 0x1A8, sizeof(origin));
    std::memcpy(original.data(), base + control + 0x170, sizeof(original));
    // The actor has already applied this frame's turn. The movement driver's
    // reference can still be the preceding orientation at this late refresh.
    std::memcpy(facing.data(), base + actor + 0x30, sizeof(facing));
    float original_length = 0, facing_length = 0;
    for (unsigned i = 0; i < 3; ++i) {
        if (!std::isfinite(origin[i]) || !std::isfinite(original[i]) || !std::isfinite(facing[i])) return;
        original_length += original[i] * original[i];
        facing_length += facing[i] * facing[i];
    }
    if (!std::isfinite(original_length) || std::abs(original_length - 1.f) > .02f ||
        !std::isfinite(facing_length) || std::abs(facing_length - 1.f) > .02f ||
        !DarkwatchThirdPersonBodyAimTarget(ctx, base, actor, target)) return;
    float length = 0, along = 0;
    for (unsigned i = 0; i < 3; ++i) {
        direction[i] = target[i] - origin[i];
        if (!std::isfinite(direction[i])) return;
        length += direction[i] * direction[i];
        along += direction[i] * original[i];
    }
    if (!std::isfinite(length) || !std::isfinite(along) || length < .0001f || along <= .01f) return;
    const float scale = 1.f / std::sqrt(length);
    for (float& value : direction) value *= scale;

    // Run after the current camera update. Native AIMING poses move the arms;
    // neither the control ray nor the body's facing/locomotion is changed.
    std::array<uint8_t, 2048> saved;
    const uint32_t scratch = ctx.esp - uint32_t(saved.size());
    std::memcpy(saved.data(), base + scratch, saved.size());
    struct Restore {
        uint8_t* where; const std::array<uint8_t, 2048>& saved;
        ~Restore() { std::memcpy(where, saved.data(), saved.size()); }
    } restore{base + scratch, saved};
    X86Context call = ctx;
    call.esp -= 64;
    call.ecx = driver;
    const uint32_t vector = call.esp + 16, reference = call.esp + 32;
    const uint32_t args[]{0x21606D, reference, vector, 1};
    std::memcpy(base + call.esp, args, sizeof(args));
    std::memcpy(base + vector, direction.data(), sizeof(direction));
    std::memcpy(base + reference, facing.data(), sizeof(facing));
    x86_icall(call, base, 0x6AF7B);
    // Evaluate those weights now. Final pose publication refreshes the held
    // children without advancing clocks or replaying reload/melee events.
    call = ctx;
    call.esp -= 64;
    call.ecx = controller;
    std::memcpy(base + call.esp, args, sizeof(uint32_t));
    x86_icall(call, base, 0x21CDC3);
}
