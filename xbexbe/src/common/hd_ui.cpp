#include "hd_ui.h"
#include "hd_ui_assets.h"
#include "gameplay_textures.h"
#include "spectral_hand_textures.h"
#include "graphics_view.h"
#include "prompts.h"
#include "app/app.h"
#include "core/log.h"
#include "gpu/ext.h"
#include <array>
#include <atomic>
#include <filesystem>
#include "cpu/x86_context.h"

namespace darkwatch {
namespace {
std::atomic<bool> g_startup{false};
std::atomic<bool> g_gameplay_available{false};
constexpr uint64_t kHandSeamOffset = 115466240;
constexpr uint32_t kHandSeamBytes = 19000;
constexpr uint64_t kHandSeamHash = 0x7e7b0b359ebdcd84ull;
bool Font(const hd::Asset& a) { return a.offset >= 93423668 && a.offset <= 94154164; }
class HdUi final : public gpu::Extension {
    GameplayTextures gameplay_;
    SpectralHandTextures spectral_hands_;
    HANDLE file_ = INVALID_HANDLE_VALUE, mapping_ = nullptr;
    const uint8_t* data_ = nullptr;
    uint64_t bytes_ = 0;
    std::array<hd::PackEntry, std::size(hd::kAssets)> entries_{};
    std::array<uint8_t, std::size(hd::kAssets)> verified_{};
#ifndef XBE_RELEASE
    std::array<bool, std::size(hd::kAssets)> used_{};
#endif
public:
    bool GameplayAvailable() const { return gameplay_.Available(); }
    ~HdUi() override {
        if (data_) UnmapViewOfFile(data_);
        if (mapping_) CloseHandle(mapping_);
        if (file_ != INVALID_HANDLE_VALUE) CloseHandle(file_);
    }
    bool Open(const std::filesystem::path& path) {
        gameplay_.Open(path.parent_path() / "gameplay-hd");
        spectral_hands_.Open(path.parent_path() / "assets" / "packfile.pck",
                             kHandSeamOffset, kHandSeamBytes, kHandSeamHash);
        // Prepare the optional hand atlases before gameplay to avoid a first-draw hitch.
        spectral_hands_.Prepare(gameplay_);
        file_ = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        LARGE_INTEGER size{};
        if (file_ == INVALID_HANDLE_VALUE || !GetFileSizeEx(file_, &size) || size.QuadPart <= 0 ||
            uint64_t(size.QuadPart) > (1ull << 30)) return false;
        bytes_ = uint64_t(size.QuadPart);
        mapping_ = CreateFileMappingW(file_, nullptr, PAGE_READONLY, 0, 0, nullptr);
        if (!mapping_) return false;
        data_ = static_cast<const uint8_t*>(MapViewOfFile(mapping_, FILE_MAP_READ, 0, 0, 0));
        if (!data_ || !hd::ValidatePack({data_, size_t(bytes_)}, hd::kAssets)) return false;
        std::memcpy(entries_.data(), data_ + sizeof(hd::PackHeader), sizeof(entries_));
        // Verify/preload fonts, HUD and intro art before the original game starts.
        for (size_t i = 0; i < entries_.size(); ++i) {
            const auto& a = hd::kAssets[i];
            if (a.always || Font(a) ||
                (a.offset >= 103041076 && a.offset <= 103414324)) Verify(i);
        }
        return true;
    }
    bool Verify(size_t i) {
        if (!entries_[i].pixels_offset) return false;
        if (!verified_[i]) {
            const auto& entry = entries_[i];
            verified_[i] = hd::Hash({data_ + entry.pixels_offset, size_t(hd::PixelBytes(hd::kAssets[i]))}) == entry.pixels_hash ? 1 : 2;
            if (verified_[i] == 2) LOGE("HD UI: invalid replacement for %s; using original", hd::kAssets[i].name);
        }
        return verified_[i] == 1;
    }
    uint64_t TextureRevision() const override { const auto s = view::Snapshot(); return 1 + uint64_t(s.hd_ui) * 2 + uint64_t(g_startup.load()) + uint64_t(s.hd_textures)*4 + PromptTextureRevision()*8; }
    bool ReplaceTexture(const gpu::TextureDesc& d, const gpu::FormatInfo& fi, const uint8_t* original,
                        uint32_t bytes, const uint32_t* palette, gpu::TextureReplacement& out) override {
        if (!original || fi.depth || d.cube || d.linear || d.depth != 1) return false;
        if (view::Snapshot().hd_textures &&
            (spectral_hands_.Replace(d, original, bytes, palette, gameplay_, out) ||
             gameplay_.Replace(d, original, bytes, palette, out))) return true;
        if (d.levels != 1) return false;
        const bool enabled = view::Snapshot().hd_ui;
        if (enabled && ReplacePromptTexture(d, fi, original, bytes, out)) return true;
        uint64_t source_hash = 0, palette_hash = 0;
        bool hashed = false;
        for (size_t i = 0; i < entries_.size(); ++i) {
            const auto& a = hd::kAssets[i];
            if ((!enabled && !a.always && !(Font(a) && g_startup.load())) || d.format != a.format || d.width != a.width ||
                d.height != a.height || bytes != a.payload_bytes || (a.palette_bytes && !palette)) continue;
            if (!hashed) {
                source_hash = hd::Hash({original, bytes});
                palette_hash = palette ? hd::Hash({reinterpret_cast<const uint8_t*>(palette), 1024}) : 0;
                hashed = true;
            }
            if (source_hash != a.payload_hash || palette_hash != a.palette_hash) continue;
            const uint8_t* native = data_ + entries_[i].native_offset;
            if ((a.palette_bytes && std::memcmp(palette, native + 92, a.palette_bytes)) ||
                std::memcmp(original, native + 92 + a.palette_bytes, bytes) || !Verify(i)) continue;
            out.id = entries_[i].pixels_hash;
            out.width = a.width * 4; out.height = a.height * 4;
            out.bgra.assign(data_ + entries_[i].pixels_offset,
                            data_ + entries_[i].pixels_offset + hd::PixelBytes(a));
#ifndef XBE_RELEASE
            if (!used_[i]) {
                used_[i] = true;
                LOGR("HD UI: selected %s %ux%u -> %ux%u (%s)", a.name, a.width, a.height,
                     out.width, out.height, a.always ? "intro still" : "UI/font/HUD");
            }
#endif
            return true;
        }
        return false;
    }
};
} // namespace
void InitializeHdUi() {
    if (gpu::g_extension) return; // A quick reboot must not invalidate the renderer's existing extension pointer.
    g_gameplay_available = false;
    auto extension = std::make_unique<HdUi>();
    if (!extension->Open(app::ExeDir() / "hd-ui.pack")) {
        LOGE("HD UI: prepared asset pack missing or invalid; retaining original textures");
        return;
    }
    LOGR("HD UI: %zu pinned identities loaded; available intro replacements enabled independently; missing art retains originals; videos unchanged", std::size(hd::kAssets));
    g_gameplay_available = extension->GameplayAvailable();
    gpu::SetExtension(std::move(extension));
}
bool GameplayTexturesAvailable() { return g_gameplay_available.load(); }
} // namespace darkwatch

// The original splash sequence and following movie entry delimit its legal text.
void DarkwatchHdStartupBegin(X86Context&, uint8_t*) { darkwatch::g_startup = true; }
void DarkwatchHdStartupEnd(X86Context&, uint8_t*) { darkwatch::g_startup = false; }
