#include "common/shader_preparation.h"
#include "common/shader_preparation_catalogue.h"
#include "common/shader_preparation_observed.h"
#include "shader_preparation_build.h"
#include "app/app.h"
#include "gpu/backend.h"
#include "gpu/shaders.h"
#include "kernel/kernel.h"
#include <array>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <set>
#include <string_view>
#include <mutex>
#include <thread>
#include <windows.h>
#include <bcrypt.h>

namespace {
using darkwatch::shaderprep::kShaderRecipes;
using darkwatch::shaderprep::kObservedBuilderLayouts;
using darkwatch::shaderprep::kStaticShaderRecipes;
using darkwatch::shaderprep::kFixedShaderRecipes;
using darkwatch::shaderprep::kPixelShaderRecipes;
constexpr const char* kXbeDigest = "72fc8033e01df4f22c703121cfd160969c642b18e841248224fc97a8f32050d7";
constexpr uint32_t kBuilder = 0x2611C0, kFormatter = 0x24D0BE;
constexpr uint32_t kAllocator = 0x113990, kFree = 0x24CB7B;
constexpr uint32_t kScratch = 0x4B9390, kScratchBytes = 0x800;
constexpr uint32_t kCache = 0x4B9B90, kCacheBytes = 0xCE4;
constexpr uint32_t kHeadroom = 0xC000, kMaxInstructions = 124;
struct Layout { uint16_t regs; uint64_t decode; };
constexpr Layout kLayouts[] = {{0x002F, 0}, {0x003F, 0}, {0x003F, 0x4200}, {0x007F, 0}};
constexpr size_t kTotal = std::size(kShaderRecipes) * std::size(kLayouts) +
    std::size(kObservedBuilderLayouts) + std::size(kStaticShaderRecipes) + std::size(kFixedShaderRecipes) + std::size(kPixelShaderRecipes);
static_assert(std::size(kShaderRecipes) == 1110 && kTotal == 4474);
std::atomic<bool> g_attempted{false};
std::string g_compiler;

struct Pin { uint32_t address, size; const char* sha256; };
constexpr Pin kPixelDefinition = {0x00496490, 240, "fa2962811589478be27c6e5133dff5fff7e000a2ca7ca6fa1194eff1cf27e48c"};
// Original bytes are read from the user's XBE; only revision fingerprints are shipped.
constexpr Pin kPins[] = {
    {0x00113C40, 105, "a83cb38ccfdb53868516303d31505bba03cd07ee29662360bcb136eca69db5aa"},
    {0x00129900, 176, "903f5a29848f267b9a304825927d1792ded51925a28cd27d4ac186734bba7bf5"},
    {0x001143C0, 192, "e9337dd24a43fd0a3b8ba159d7347f1bdc651159e8f0b1e40e09cff72c0dd16a"},
    {0x001FC931, 18, "fa73996f14d2653a2dfc8f0a9abb4fa651d724eaf0784f8711a723e92450b878"},
    {0x00113EB0, 195, "cbb79b7c8ac871eec220cdeb8e13c88029d01baa3327ebcaa49d7c29ccff0351"},
    {0x0011A1C0, 83, "acd6ba7f4bdd6d28106b783b14d171760e6ab81b569c7e54c9bc78bfa1243a61"},
    {0x0025A6A0, 284, "0fb638661f10e4a1830597c7c85942e01af8ca2b9573ab5195294567270941c6"},
    {0x0025E2A0, 731, "ba4622330a299e2713439e597810a0de7bb9cf7fcf4adc874168fe927a53dfff"},
    {0x002611C0, 2650, "81cd48f123f919c0fc890400277120b0980e67011126bc143a3db41c2b737c03"},
    {0x00261C90, 288, "d612107e605acbac1d35c1a9f49122281df938ffc56f83d60a0e1f5ba2d468aa"},
    {0x002604D0, 55, "af6646cad80df789995df7b621c8d03925159a76c4b23bf13b6ddca40d5f920d"},
    {0x0044973C, 9, "f5e75926ac250d8f1b4ff73f55aa4d0ba6c07d02e8d4ce867a9d3eafb3461d14"},
    {0x0044972C, 16, "b7d32f8bccb266a798831865a9eec73bd848a766d3b4b6bfb29fe79ecd382b4b"},
    {0x00449710, 28, "30c2918136d101204f9540f0a0fda6c17384e427b6c9e134b7537ecd339ab17c"},
    {0x004496F4, 28, "0edd8243c164a88ef5527f52646b37fc4def691adb722d7e94f2f04f269ef066"},
    {0x004496D8, 28, "168a4eb1651174ab1773425ac76eb1a35a96be61b2c023855e688a15e5266b79"},
    {0x00448E90, 4, "3f6b3b8c4f7288d1bd5b099f836f7409d262ef0978cd7ecfbc9c3fce4d42558f"},
    {0x00448E98, 4, "16abf19fffe3807af1c3efad1e187f6eb032244e52967af75fa01716e392bcdd"},
    {0x0049FD04, 20, "d58dceb2ca895cb8a917ac179b9b4af5e4428f214869a9761741775c592fb03f"},
    {0x0049FD2C, 20, "8345b13772424ca8f27bf444fc1af664347e5bd5886d7880b5df424a721aad52"},
    {0x0049FF38, 116, "abfb9d4b8650490821c568cacb7fcd33d57e6ccef6c364a89cc8d71c2bc0b975"},
};

bool HexDigest(std::string_view s) {
    return s.size() == 64 && s.find_first_not_of("0123456789abcdef") == s.npos;
}
std::string Digest(const void* data, size_t size) {
    if (size > UINT32_MAX) return {};
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) return {};
    std::array<uint8_t, 32> bytes{};
    bool ok = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    if (ok) ok = BCryptHashData(hash, const_cast<PUCHAR>(static_cast<const uint8_t*>(data)), ULONG(size), 0) >= 0;
    if (ok) ok = BCryptFinishHash(hash, bytes.data(), ULONG(bytes.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (!ok) return {};
    std::string result;
    constexpr char digits[] = "0123456789abcdef";
    for (auto b : bytes) { result += digits[b >> 4]; result += digits[b & 15]; }
    return result;
}
std::string ReadFile(const std::filesystem::path& path, size_t maximum) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file || file.tellg() <= 0 || uint64_t(file.tellg()) > maximum) return {};
    std::string bytes(size_t(file.tellg()), '\0');
    file.seekg(0);
    if (!file.read(bytes.data(), std::streamsize(bytes.size())) || file.peek() != EOF) return {};
    return bytes;
}
bool RevisionFile() {
    auto bytes = ReadFile(app::ExeDir() / "assets" / "default.xbe", 64u << 20);
    return !bytes.empty() && Digest(bytes.data(), bytes.size()) == kXbeDigest;
}

void Progress(size_t completed, const char* message, bool ready = false) {
    // Messages are fixed literals, never guest strings or filesystem paths.
    std::printf("{\"state\":\"%s\",\"message\":\"%s\",\"completed\":%zu,\"total\":%zu,\"progress\":%zu}\n",
                ready ? "shader_ready" : "shader_prepare", message, completed, kTotal, completed * 100 / kTotal);
    std::fflush(stdout);
}
int Error(const char* message) {
    std::printf("{\"state\":\"error\",\"message\":\"%s\"}\n", message);
    std::fflush(stdout);
    return -1;
}

std::filesystem::path StampPath() { return app::ExeDir() / "cache" / "shader-preparation-v1.txt"; }
std::string StampPrefix() {
    return std::string("DARKWATCH_SHADERS_1\n") + kShaderPreparationBuild + '\n' + g_compiler + '\n';
}
bool WarmStamp() {
    const std::string text = ReadFile(StampPath(), 1u << 20), prefix = StampPrefix();
    if (!text.starts_with(prefix) || text.size() != prefix.size() + (kTotal + 1) * 65) return false;
    const size_t checksum_at = text.size() - 65;
    if (text.back() != '\n' || Digest(text.data(), checksum_at) != text.substr(checksum_at, 64)) return false;
    std::set<std::string> checked;
    for (size_t at = prefix.size(); at < checksum_at; at += 65) {
        std::string key = text.substr(at, 64);
        if (!HexDigest(key) || text[at + 64] != '\n') return false;
        if (checked.insert(key).second && !gpu::ShaderCacheContains(key)) return false;
    }
    return !checked.empty();
}
bool WriteStamp(const std::vector<std::string>& keys) {
    if (keys.size() != kTotal) return false;
    std::string text = StampPrefix();
    for (const auto& key : keys) { if (!HexDigest(key)) return false; text += key + '\n'; }
    const auto checksum = Digest(text.data(), text.size());
    if (!HexDigest(checksum)) return false;
    text += checksum + '\n';
    const auto path = StampPath();
    std::error_code ec;
    std::filesystem::create_directories(path.parent_path(), ec);
    if (ec) return false;
    auto temporary = path;
    temporary += L".tmp." + std::to_wstring(GetCurrentProcessId()) + L"." + std::to_wstring(GetTickCount64());
    HANDLE file = CreateFileW(temporary.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    bool ok = WriteFile(file, text.data(), DWORD(text.size()), &written, nullptr) && written == text.size();
    if (ok) ok = FlushFileBuffers(file) != 0;
    if (!CloseHandle(file)) ok = false;
    if (ok) ok = MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
    if (!ok) DeleteFileW(temporary.c_str());
    return ok;
}

bool Span(uint32_t p, uint32_t n) {
    if (!p || !n || uint64_t(p) + n > 0x100000000ull) return false;
    const uint64_t end = uint64_t(p) + n - 1;
    for (uint64_t page = p & ~uint64_t(0xFFF); page <= end; page += 0x1000)
        if (!mem::IsCommitted(uint32_t(page))) return false;
    return true;
}
uint32_t Read(uint8_t* base, uint32_t p) { uint32_t v; std::memcpy(&v, base + p, 4); return v; }
bool Mapped(uint32_t p) {
    for (const auto* m = X86FuncMappings; m->guest; ++m) if (m->guest == p) return m->host != nullptr;
    return false;
}
bool StackBounds(uint32_t top, uint32_t size, uint32_t esp) {
    return top && size >= 0x10000 && size <= top && esp <= top && esp >= top - size + kHeadroom;
}
bool Gate(const X86Context& ctx, uint8_t* base) {
    if (base != mem::Base() || base != kernel::g_base || !Span(ctx.esp, 16) ||
        Read(base, ctx.esp) != 0x11A1DD || ctx.eax != 0x4DF1A0 || Read(base, ctx.esp + 4) != ctx.eax) return false;
    if (!Span(0x4DF290, 0x64) || !Span(0x4B91B8, 0x2DC) ||
        !Span(kScratch, kScratchBytes + kCacheBytes) || !Span(0x4A0014, 4)) return false;
    for (const auto& pin : kPins)
        if (!Span(pin.address, pin.size) || Digest(base + pin.address, pin.size) != pin.sha256) return false;
    if (Read(base, 0x4B92BC) != 1 || Read(base, 0x4DF2F0) != 2 ||
        Read(base, 0x4DF290) != kFormatter || Read(base, 0x4DF2D4) != kAllocator || Read(base, 0x4DF2D8) != kFree) return false;
    for (uint32_t f : {kBuilder, kFormatter, kAllocator, kFree, 0x3F529Cu, 0x3F5FEEu, 0x3EEB48u, 0x3EEB13u})
        if (!Mapped(f)) return false;
    for (uint32_t p : {0x4B9384u, 0x4B9388u, 0x4B91B8u})
        if (!Read(base, p) || !Span(Read(base, p), 4)) return false;
    for (uint32_t i = 0; i < 48; ++i) {
        const uint32_t handle = Read(base, 0x4B92C0 + 4 * i);
        if (!(handle & 1) || !Span(handle & ~1u, 16)) return false;
    }
    auto* t = kernel::Current();
    // shortcut: 48 KiB is the qualified admission bound, not a proof of every assembler path's stack use.
    return t && StackBounds(t->stack_top, t->stack_size, ctx.esp) && ctx.fs_base == t->kpcr &&
        Span(t->kpcr, 12) && Span(t->ethread + 0x1C, 8) &&
        Read(base, t->kpcr + 4) == t->stack_top && Read(base, t->kpcr + 8) == t->stack_top - t->stack_size &&
        Read(base, t->ethread + 0x1C) == t->stack_top && Read(base, t->ethread + 0x20) == t->stack_top - t->stack_size &&
        Span(ctx.esp - kHeadroom, kHeadroom);
}
uint32_t Guest(const X86Context& entry, uint32_t target, uint32_t argument) {
    X86Context call = entry;  // CallGuest alone preserves only general-purpose registers.
    return kernel::CallGuest(call, target, {argument});
}
struct Workspace {
    uint8_t* base;
    uint32_t descriptor;
    std::array<uint8_t, kScratchBytes> original;
    explicit Workspace(uint8_t* b) : base(b), descriptor(mem::AllocSystem(16)) {
        std::memcpy(original.data(), base + kScratch, original.size());
    }
    ~Workspace() {
        std::memcpy(base + kScratch, original.data(), original.size());
        if (descriptor) mem::FreeSystem(descriptor);
    }
};
bool ReadProgram(uint8_t* base, uint32_t raw, const char* digest, std::vector<uint32_t>& program) {
    if (!Span(raw, 4)) return false;
    const uint32_t header = Read(base, raw), n = header >> 16;
    if ((header & 0xFFFF) != 0x2078 || !n || n > kMaxInstructions || !Span(raw, 4 + n * 16) ||
        Digest(base + raw, 4 + n * 16) != digest) return false;
    program.resize(n * 4);
    std::memcpy(program.data(), base + raw + 4, n * 16);
    for (uint32_t i = 0; i < n; ++i) {
        const auto* w = program.data() + i * 4;
        const auto mac = w[1] >> 21 & 15, ilu = w[1] >> 25 & 7;
        const bool output = (w[3] & 0xF000) && ((w[3] & 4) ? ilu != 0 : mac != 0 && mac != 13);
        if (bool(w[3] & 1) != (i + 1 == n) || mac > 13 || (output && !(w[3] & 0x800))) return false;
    }
    return true;
}

struct ShaderJob {
    const std::vector<uint32_t>* program = nullptr;
    Layout layout{};
    std::string source;
    const char* profile = "vs_5_0";
};
gpu::PixelKey MakePreparationPixelKey(const darkwatch::shaderprep::PixelShaderRecipe& recipe,
                                      const gpu::PixelShader& program) {
    gpu::TexInfo textures[4]{};
    textures[0].kind = recipe.kind0;
    textures[0].rect = recipe.rect0;
    textures[1].kind = recipe.kind1;
    gpu::PixelKey key{};
    if (recipe.programmable) {
        gpu::State state;
        state.ps = std::make_shared<gpu::PixelShader>(program);
        state.rs[gpu::kRsPsTextureModes] = program.def[54];
        key = gpu::MakePixelKey(state, textures);
    } else {
        std::memcpy(key.ff, recipe.ff, sizeof(recipe.ff));
        std::memcpy(key.tex, textures, sizeof(textures));
    }
    key.alphakill = 1;
    key.proj = recipe.proj;
    key.quad = recipe.quad;
    return key;
}
bool CompileJobs(const std::vector<ShaderJob>& jobs, std::vector<std::string>& keys) {
    if (jobs.size() != kTotal) return false;
    keys.resize(jobs.size());
    std::atomic<size_t> next{0};
    std::atomic<bool> failed{false};
    std::mutex progress;
    size_t completed = 0;
    try {
        // Only host compilation is parallel: the original guest builder stays serial.
        std::vector<std::jthread> workers;
        const unsigned cores = std::thread::hardware_concurrency();
        const unsigned count = cores > 4 ? 4 : cores ? cores : 1;
        for (unsigned worker = 0; worker < count; ++worker) workers.emplace_back([&] {
            try {
                while (!failed) {
                    const auto i = next.fetch_add(1);
                    if (i >= jobs.size()) break;
                    const auto& job = jobs[i];
                    const bool ok = job.program
                        ? gpu::PrepareVertexShaderCache(*job.program, job.layout.regs, job.layout.decode, keys[i])
                        : gpu::PrepareShaderCache(job.source, job.profile, keys[i]);
                    if (!ok || !HexDigest(keys[i])) { failed = true; break; }
                    std::lock_guard lock(progress);
                    ++completed;
                    if (completed % 4 == 0 || completed == jobs.size())
                        Progress(completed, "Preparing shaders. This only needs to finish once.");
                }
            } catch (...) { failed = true; }
        });
    } catch (...) { return false; }
    return !failed && completed == jobs.size();
}

bool PrepareCatalogue(const X86Context& entry, uint8_t* base) {
    Workspace workspace(base);
    if (!workspace.descriptor || !Span(workspace.descriptor, 16)) return false;
    std::array<uint8_t, kCacheBytes> cache;
    std::memcpy(cache.data(), base + kCache, cache.size());
    const uint32_t owner = Read(base, 0x4A0014);
    std::vector<std::string> keys;
    std::vector<std::vector<uint32_t>> programs;
    programs.reserve(std::size(kShaderRecipes) + std::size(kStaticShaderRecipes));
    std::vector<ShaderJob> jobs;
    jobs.reserve(kTotal);
    for (const auto& recipe : kShaderRecipes) {
        std::memcpy(base + workspace.descriptor, &recipe.descriptor, 4);
        uint32_t raw = Guest(entry, kBuilder, workspace.descriptor);
        auto& program = programs.emplace_back();
        // A bad return is not a proven allocation: fail this isolated process without freeing it or resuming.
        if (!raw) return false;
        if (!ReadProgram(base, raw, recipe.sha256, program) ||
            std::memcmp(cache.data(), base + kCache, cache.size()) || Read(base, 0x4A0014) != owner) {
            Error("The original shader builder returned unexpected data. Please repair the installation.");
            app::FinishPreparation(1);
        }
        Guest(entry, kFree, raw);
        for (const auto& layout : kLayouts) {
            jobs.push_back({&program, layout});
        }
        for (const auto& layout : kObservedBuilderLayouts) {
            if (layout.descriptor != recipe.descriptor) continue;
            jobs.push_back({&program, {layout.regs, layout.decode}});
        }
    }
    for (const auto& recipe : kStaticShaderRecipes) {
        auto& program = programs.emplace_back();
        if (!ReadProgram(base, recipe.address, recipe.sha256, program)) return false;
        if (recipe.quad)
            jobs.push_back({nullptr, {}, gpu::QuadHlsl(gpu::VertexProgramHlsl(program, recipe.regs, recipe.decode))});
        else
            jobs.push_back({&program, {recipe.regs, recipe.decode}});
    }
    for (const auto& recipe : kFixedShaderRecipes) {
        const gpu::FixedKey key{recipe.light, recipe.types, {recipe.tex[0], recipe.tex[1], recipe.tex[2], recipe.tex[3]}};
        auto source = gpu::FixedVertexHlsl(recipe.regs, false, recipe.decode, key);
        jobs.push_back({nullptr, {}, recipe.quad ? gpu::QuadHlsl(std::move(source)) : std::move(source)});
    }
    if (!Span(kPixelDefinition.address, kPixelDefinition.size) ||
        Digest(base + kPixelDefinition.address, kPixelDefinition.size) != kPixelDefinition.sha256) return false;
    gpu::PixelShader pixel;
    std::memcpy(pixel.def, base + kPixelDefinition.address, sizeof(pixel.def));
    for (const auto& recipe : kPixelShaderRecipes)
        jobs.push_back({nullptr, {}, gpu::PixelHlsl(MakePreparationPixelKey(recipe, pixel)), "ps_5_0"});
    return CompileJobs(jobs, keys) && WriteStamp(keys);
}
} // namespace

int darkwatch::PrepareShaders() {
    if (!app::PreparingShaders()) return -1;
    if (!RevisionFile()) return Error("Shader preparation needs the supported original game files. Please repair the installation.");
    g_compiler = gpu::ShaderCompilerCacheIdentity();
    if (!HexDigest(g_compiler)) return Error("The Windows shader compiler could not be identified.");
    if (WarmStamp()) { Progress(kTotal, "Shaders are ready.", true); return 0; }
    Progress(0, "Preparing the original game shader library.");
    return 1;
}

void DarkwatchPrepareShaders(X86Context& ctx, uint8_t* base) {
    if (!app::PreparingShaders()) return;
    if (g_attempted.exchange(true) || !HexDigest(g_compiler) || !Gate(ctx, base)) {
        Error("The original shader builder could not be initialized safely.");
        app::FinishPreparation(1);
    }
    const X86Context entry = ctx;
    if (!PrepareCatalogue(entry, base) || std::memcmp(&ctx, &entry, sizeof(ctx))) {
        Error("Shader preparation did not finish. Existing saved data is unchanged; please retry setup.");
        app::FinishPreparation(1);
    }
    Progress(kTotal, "Shaders are ready.", true);
    app::FinishPreparation(0);
}
