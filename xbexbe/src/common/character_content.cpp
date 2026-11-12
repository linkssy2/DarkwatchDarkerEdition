#include "kernel/kernel.h"
#include <algorithm>
#include <array>
#include <filesystem>
#include <string_view>
#include <cstdlib>
#include <windows.h>
#include <bcrypt.h>

namespace {
struct ArchivePin { const char* guest_path; uint64_t size; std::string_view sha256; };
#ifndef XBE_RELEASE
constexpr std::array<ArchivePin, 3> kDevTestRoomArchives{{
    {"D:\\packfile.pck", 210056365, "c817f7419d0ef62d5c977277d507cc3562ec4c42f999c8eb386ad55d249b31cd"},
    {"D:\\LvlSingl.pck", 2487593903, "a0fdace2361471ef436813011beea610dc97b0861d50bbb9bbc2f1959adcafc9"},
    {"D:\\audio.pck", 152632677, "4c16eb53a53b7b502ec77db68d68b940f1d75be46842d8761e80cccb79fa6540"},
}};
constexpr std::string_view kDevTestRoomFixture = "5561188cd6f3f6ca1af3d01b900f1d99e8f381ecd9ff229462a3ff1063018dde";
#endif
constexpr std::array<ArchivePin, 3> kCharacterArchives{{
    {"D:\\packfile.pck", 199441106, "e19c6eeb1494bb7ede1f9976f0d402c970be44ae7da1a2754fd063a2b2e48257"},
    {"D:\\LvlSingl.pck", 3018752579, "55e931aa28853a38ad8c8072140b4cfcb4c30e6c9e4c27eb851d4d142b727180"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};

constexpr std::array<ArchivePin, 3> kCampaignFeedbackArchives{{
    {"D:\\packfile.pck", 199254290, "7f520632e0f2ceac93b3d0cccdf91af8011907d399ae85dec01e2c3c6fe68a83"},
    {"D:\\LvlSingl.pck", 3012989507, "0afa41525e9983e6df7580b27caba1824f4a0c8a23a5030abc0422fa14e58f94"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};
constexpr std::array<ArchivePin, 3> kCampaignCameraGaitArchives{{
    {"D:\\packfile.pck", 200704954, "656c752a29c0dfa52bfb557f911a40233ef53c13bdaa67b56c6b38ffbf3b38df"},
    {"D:\\LvlSingl.pck", 3045288515, "6553332771df115b726b9e2b7d3dba2f7a24ae59134f3cfdb41ca0f886eb1692"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};
constexpr std::array<ArchivePin, 3> kCampaignMaleStrideArchives{{
    {"D:\\packfile.pck", 200704954, "a414e23dae485790f1aba7e36e63746c0f7cb6eb66a69ca0861db705d8146719"},
    {"D:\\LvlSingl.pck", 3045288515, "a2724db84e595461b5ed4c2e35613fb925f2cdf6233692c9e1859e6f96cf6f9f"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};
constexpr std::array<ArchivePin, 3> kCampaignOutwardStrideArchives{{
    {"D:\\packfile.pck", 200704954, "5204b0dce560336ba80cb65d6dfc4e73a0504f73d5742dc2c6e837c03f215fac"},
    {"D:\\LvlSingl.pck", 3045288515, "797f73cab89874e431ea94996b158b19afa77eb940e03c3266ab9079e2b07bfb"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};
constexpr std::array<ArchivePin, 3> kCampaignReferenceStrideArchives{{
    {"D:\\packfile.pck", 200704954, "02774c265a1f838adf99db7ee946b59695ac6d6638e86c4b3b6db3179e848907"},
    {"D:\\LvlSingl.pck", 3045288515, "7d81366ee928f4db9e328a47ce42b9057378656a71059f586e15d85591ea7631"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};
constexpr std::array<ArchivePin, 3> kCampaignCrouchStrideArchives{{
    {"D:\\packfile.pck", 200442226, "3736a8837f9d36e83216aae940118a7944d19e81b9a30794f7799779fe6b9206"},
    {"D:\\LvlSingl.pck", 3031343683, "19bf1ec7de1dd65eaee13c98fef01aebb6c48fe496c7ec1214309fa3c6514ed6"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};
constexpr std::array<ArchivePin, 3> kCampaignWideStrideArchives{{
    {"D:\\packfile.pck", 200442226, "02bef06ae69fb66e6358d16fef1eeb494060ad1da7f23b2e951c8c2392092067"},
    {"D:\\LvlSingl.pck", 3031343683, "6d93ed66a681d77987736a69cc53ac2df2dc9372104022243a492eb57a04d0e4"},
    {"D:\\audio.pck", 152395109, "33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285"},
}};

#if defined(DARKWATCH_GRENADE_PAIR_FIXTURE)
static_assert(DARKWATCH_GRENADE_PAIR_FIXTURE == 20261029);
// Only the private pickup arrangement may replace the production archive pin.
constexpr auto kAdmittedCharacterArchives = [] {
    auto pins = kCharacterArchives;
    pins[0].size = 142404897;
    pins[0].sha256 = "8b8f1b9e3d0334a03ccbf8fb38d3d3a471374e3822aec37d597a0b1b7cd9a073";
    pins[1].size = 1792254903;
    pins[1].sha256 = "04878dcaf630a679a327460c72939d98f84140d2d42cf3a79492ccb1f9eea7a9";
    return pins;
}();
#else
constexpr auto& kAdmittedCharacterArchives = kCharacterArchives;
#endif

#ifndef XBE_RELEASE
constexpr auto kOnlineNpcArchives = [] {
    auto pins = kCharacterArchives;
    pins[0].size = 143781153;
    pins[0].sha256 = "176d9bf2e1b373bde65f82853b445a67e22541ad2468734c3cd7c21cf508836a";
    pins[1].size = 1794683831;
    pins[1].sha256 = "79ae5e1924204dd036e03aaea150b5cf6a52eafa55b971203d8b0f1e66dd84f7";
    return pins;
}();
constexpr auto kOnlineNearNpcArchives = [] {
    auto pins = kOnlineNpcArchives;
    pins[1].size = 1794702263;
    pins[1].sha256 = "4d2dd53a8501df28eddbbce5b0c72661059a0dc3704623bfc0223b082e779af4";
    return pins;
}();
constexpr auto kOnlineRegroupArchives = [] {
    auto pins = kOnlineNearNpcArchives;
    pins[1].size = 1794716599;
    pins[1].sha256 = "34c65ae6d3c9e4c9f4fd2c1241f5e22c92f694bd8484bedea3859f1f11249728";
    return pins;
}();
constexpr auto kOnlineRegroupSpawnArchives = [] {
    auto pins = kOnlineRegroupArchives;
    pins[1].sha256 = "2ff52bf44f208ae05c9da45333bfbfb1c7d3396f33b2e72ea663a2f0a8a7c083";
    return pins;
}();
constexpr auto kOnlineRegroupFacingArchives = [] {
    auto pins = kOnlineRegroupSpawnArchives;
    pins[1].sha256 = "174838f22f9753592c4b250ecad4cac77f1d9fa71c5e112a3c1422d3d046d5db";
    return pins;
}();
constexpr auto kOnlineCinematicArchives = [] {
    auto pins = kOnlineNpcArchives;
    pins[1].size = 1794698167;
    pins[1].sha256 = "d3535e665feca8be6a9eabbae9a4fdec78e4d50d0bf58660f7f009c2c08f534e";
    return pins;
}();
constexpr auto kOnlineAreaArchives = [] {
    auto pins = kOnlineCinematicArchives;
    pins[1].sha256 = "714d3b470c385f4b069e541f02924dab7c97fb1e4ecb0b2074c16a58f16cd62d";
    return pins;
}();
constexpr auto kOnlineChapterArchives = [] {
    auto pins = kOnlineAreaArchives;
    pins[1].sha256 = "28bbc62f73879b2f5afa63db15fa593a6fbaef1d8456df147411ef83dcc39ff9";
    return pins;
}();
// Recompose the same reviewed private edits over the current v15 character set.
// Retain historical pins for comparisons; never pair their receipts with new bytes.
constexpr auto kOnlineCurrentNpcArchives = [] {
    auto pins = kOnlineNpcArchives;
    pins[0].size = 144956705;
    pins[0].sha256 = "d43485d7c528d6dd9970a3dc3503c77920f367b88bf86467ac44057e1e0bdd3c";
    return pins;
}();
constexpr auto kOnlineCurrentChapterArchives = [] {
    auto pins = kOnlineCurrentNpcArchives;
    pins[1].size = 1794698167;
    pins[1].sha256 = "28bbc62f73879b2f5afa63db15fa593a6fbaef1d8456df147411ef83dcc39ff9";
    return pins;
}();
constexpr auto kOnlineBattleArchives = [] {
    auto pins = kCharacterArchives;
    pins[0].size = 144958753;
    pins[0].sha256 = "50e745cb852c11bea16a90854ec9b4e102ae82767fb147b6a3e90d3d7622c2af";
    pins[1].size = 1794683831;
    pins[1].sha256 = "a9067a043b71370a1601b00b568f998d74b97185f6e202232d20d97232a0a1e0";
    return pins;
}();
#endif
const std::array<ArchivePin, 3>& AdmittedArchives() {
#ifndef XBE_RELEASE
    const char* room = std::getenv("DARKWATCH_DEV_TEST_ROOM_FIXTURE");
    if (room && std::string_view(room) == kDevTestRoomFixture) return kDevTestRoomArchives;
#endif
#ifndef XBE_RELEASE
    // The bounded runner admits this exact private fixture; normal builds never accept it.
    const char* fixture = std::getenv("DARKWATCH_ONLINE_NPC_FIXTURE");
    if (fixture && std::string_view(fixture) == "7a0e09bbecf60bf4b0a15160fe955792e2b328a766d5496633304d17e1f50c9c")
        return kOnlineCurrentNpcArchives;
    if (fixture && std::string_view(fixture) == "f817c0785645ea37ac1a1b0887004ec49d1bee953cede07ce6f6960d6e735751")
        return kOnlineCurrentChapterArchives;
    if (fixture && std::string_view(fixture) == "9c9453134c5665d5eaaeca697ca839da1f347035aa26937963e4be0437d52b92")
        return kOnlineBattleArchives;
    if (fixture && std::string_view(fixture) == "48d1975c434cf61906f71ee96d90a33e99f7a3b326082b66b2c5a234242e6262")
        return kOnlineNpcArchives;
    if (fixture && std::string_view(fixture) == "fff6b346a46b318244190a159f8830e03add2349fcd7cc92f009ac6c31474042")
        return kOnlineNearNpcArchives;
    if (fixture && std::string_view(fixture) == "d7d06fe9c8fd317b4cf7a83d412454eb4689a5715f2435403bb7b1f281d5b4d7")
        return kOnlineRegroupArchives;
    if (fixture && std::string_view(fixture) == "767d7f0866ed81e37a229163315ba60c4303bfde6d789086f4001c8922c3cf19")
        return kOnlineRegroupSpawnArchives;
    if (fixture && std::string_view(fixture) == "87648bd0c34c9e2573bd8def876d2895768bf3efe3326d2030099b8894038dc3")
        return kOnlineRegroupFacingArchives;
    if (fixture && std::string_view(fixture) == "08402d7791f3682531400304c1f321de14d47f7579ec4bba621f64454ae64baf")
        return kOnlineCinematicArchives;
    if (fixture && std::string_view(fixture) == "a3c0e22b68edd4f7d11ff172c01f4411b520f088f1f5bd25c1d7f6ba12d37df0")
        return kOnlineAreaArchives;
    if (fixture && std::string_view(fixture) == "9326b61e31ed5da0319b0e5eba9555f07246675f52965341e93e263ace8bc658")
        return kOnlineChapterArchives;
#endif
    return kAdmittedCharacterArchives;
}

HANDLE OpenCharacterArchive(const ArchivePin& pin) {
    const auto host = kernel::ResolvePath(pin.guest_path, 0);
    if (host.empty() || pin.sha256.size() != 64) return INVALID_HANDLE_VALUE;
    const auto path = std::filesystem::u8path(host);
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file == INVALID_HANDLE_VALUE) return file;
    LARGE_INTEGER size{};
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    bool ok = GetFileSizeEx(file, &size) && size.QuadPart >= 0 && uint64_t(size.QuadPart) == pin.size;
    if (ok) ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
    if (ok) ok = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    std::array<unsigned char, 64 * 1024> buffer{};
    uint64_t total = 0;
    while (ok && total < pin.size) {
        DWORD read = 0;
        const DWORD requested = DWORD((std::min)(uint64_t(buffer.size()), pin.size - total));
        ok = ReadFile(file, buffer.data(), requested, &read, nullptr) && read != 0;
        if (ok) ok = BCryptHashData(hash, buffer.data(), read, 0) >= 0;
        total += read;
    }
    DWORD extra = 0;
    if (ok) ok = ReadFile(file, buffer.data(), 1, &extra, nullptr) && extra == 0;
    std::array<unsigned char, 32> digest{};
    if (ok) ok = BCryptFinishHash(hash, digest.data(), ULONG(digest.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    constexpr char hex[] = "0123456789abcdef";
    for (size_t i = 0; ok && i < digest.size(); ++i)
        ok = pin.sha256[i * 2] == hex[digest[i] >> 4] && pin.sha256[i * 2 + 1] == hex[digest[i] & 15];
    if (ok) return file;
    CloseHandle(file);
    return INVALID_HANDLE_VALUE;
}

struct CharacterArchiveSet {
    std::array<HANDLE, 3> handles{INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE};
    bool ready = false;
    explicit CharacterArchiveSet(const std::array<ArchivePin, 3>& pins) {
        try {
            for (size_t i = 0; i < pins.size(); ++i) {
                handles[i] = OpenCharacterArchive(pins[i]);
                if (handles[i] == INVALID_HANDLE_VALUE) { Close(); return; }
            }
            ready = true;
        } catch (...) { Close(); }
    }
    void Close() {
        for (auto& handle : handles) {
            if (handle != INVALID_HANDLE_VALUE) CloseHandle(handle);
            handle = INVALID_HANDLE_VALUE;
        }
        ready = false;
    }
    ~CharacterArchiveSet() { Close(); }
};
bool CampaignFeedbackReady() {
    if (&AdmittedArchives() == &kCharacterArchives) {
        static const CharacterArchiveSet release(kCharacterArchives);
        if (release.ready) return true;
    }
    // Validate the current build once before trying retained comparison archives.
    static const CharacterArchiveSet wide_stride(kCampaignWideStrideArchives);
    if (wide_stride.ready) return true;
    static const CharacterArchiveSet crouch_stride(kCampaignCrouchStrideArchives);
    if (crouch_stride.ready) return true;
    static const CharacterArchiveSet reference_stride(kCampaignReferenceStrideArchives);
    if (reference_stride.ready) return true;
    static const CharacterArchiveSet outward_stride(kCampaignOutwardStrideArchives);
    if (outward_stride.ready) return true;
    static const CharacterArchiveSet male_stride(kCampaignMaleStrideArchives);
    if (male_stride.ready) return true;
    static const CharacterArchiveSet camera_gait(kCampaignCameraGaitArchives);
    if (camera_gait.ready) return true;
    static const CharacterArchiveSet content(kCampaignFeedbackArchives);
    return content.ready;
}
}

bool DarkwatchCharacterContentReady() {
    if (CampaignFeedbackReady()) return true;
    // Call after mounting D: and before guest archive opens; retained locks force their read-only fallback.
    static const CharacterArchiveSet content(AdmittedArchives());
    return content.ready;
}

bool DarkwatchPrivateClipFixtureReady() {
    if (CampaignFeedbackReady()) return true;
#ifndef XBE_RELEASE
    const char* room = std::getenv("DARKWATCH_DEV_TEST_ROOM_FIXTURE");
    return room && std::string_view(room) == kDevTestRoomFixture && DarkwatchCharacterContentReady();
#else
    return false;
#endif
}

void DarkwatchCharacterInitialize(X86Context&, uint8_t*) {
    (void)DarkwatchCharacterContentReady();
}
