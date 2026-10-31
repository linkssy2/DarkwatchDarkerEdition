#include "render_shaders.h"

namespace darkwatch {
namespace {
class Shaders final : public gpu::ShaderHooks {
    void VertexProgram(const std::vector<uint32_t>& program, uint16_t regs, std::string& hlsl) const override {
        struct Variant { uint64_t hash; size_t words; unsigned influences; };
        // Original builder's six unlit skinning programs; lit/reflection/rigid paths are unchanged.
        static constexpr Variant variants[] = {
            {0x736B4A5A6FCCF8C0ull, 72, 2}, {0x75D7FC0F33EE27D1ull, 92, 3},
            {0x0EE76FAEC5F7218Eull, 112, 4}, {0x85B8159F243C881Cull, 76, 2},
            {0xB6F053B95462066Bull, 96, 3}, {0x969D1B836613178Full, 116, 4},
        };
        if ((regs & 7) != 7 || program.size() < 72 || program.size() > 116) return;
        const auto hash = gpu::Hash(program.data(), program.size() * sizeof(uint32_t));
        unsigned influences = 0;
        for (const auto& variant : variants)
            if (hash == variant.hash && program.size() == variant.words) influences = variant.influences;
        if (!influences) return;
        constexpr char projection[] =
            "    {\n        precise float4 mr = dot(float4(((R3).xyzw).xyz, 1), ((c[4]).xyzw)).xxxx;";
        const auto at = hlsl.find(projection);
        if (at == std::string::npos || hlsl.find(projection, at + 1) != std::string::npos) return;

        // Match the lit pass's operation order so LEQUAL cannot reject the same animated surface.
        std::string skin = "    // Darkwatch: identical skinning position for lit and unlit passes.\n    {\n";
        constexpr char lanes[] = "xyzw";
        for (unsigned i = 0; i < influences; ++i) {
            const std::string lane(1, lanes[i]);
            skin += "        a0 = mac_arl(i.v2." + lane + ");\n";
            for (unsigned row = 0; row < 3; ++row) {
                const auto name = "dw_row" + std::to_string(row);
                skin += "        " + (i ? std::string{} : "precise float4 ") + name +
                    " = mac_mul(i.v1." + std::string(4, lanes[i]) + ", c[clamp(a0 + " +
                    std::to_string(6 + row) + ", 0, 191)])" + (i ? " + " + name : "") + ";\n";
            }
        }
        for (unsigned row = 0; row < 3; ++row)
            skin += "        R3." + std::string(1, lanes[row]) + " = dot(i.v0, dw_row" + std::to_string(row) + ");\n";
        skin += "    }\n";
        hlsl.insert(at, skin);
    }
};
}

const gpu::ShaderHooks& RenderShaders() {
    static const Shaders shaders;
    return shaders;
}
}
