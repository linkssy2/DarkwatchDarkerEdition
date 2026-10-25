#include <mutex>
#include <algorithm>
#include <vector>
#include "cpu/x86_ops.h"

X86_EXTERN_FUNC(__imp__sub_001EEAAA);
X86_EXTERN_FUNC(__imp__sub_00307DB0);
X86_EXTERN_FUNC(__imp__sub_0030AC00);
X86_EXTERN_FUNC(__imp__sub_0030AC40);
X86_EXTERN_FUNC(__imp__sub_0030AD10);

namespace {
// The original global drain gate cannot exclude a worker on another host core.
// Keep its wait outside this lock; destruction recursively invokes stop/reset.
std::recursive_mutex g_cri_lifetime;
std::vector<uint32_t> g_retiring_movies;

// The title releases its movie audio before destroying the decoder. Retire the
// worker first, but leave guest state intact for the original audio unregister.
struct MovieRetirement {
    uint32_t wrapper;
    explicit MovieRetirement(uint32_t value) : wrapper(value) {
        if (wrapper) {
            std::lock_guard<std::recursive_mutex> lock(g_cri_lifetime);
            g_retiring_movies.push_back(wrapper);
        }
    }
    ~MovieRetirement() {
        if (wrapper) {
            std::lock_guard<std::recursive_mutex> lock(g_cri_lifetime);
            g_retiring_movies.erase(std::find(g_retiring_movies.begin(), g_retiring_movies.end(), wrapper));
        }
    }
};
}

X86_FUNC(sub_001EEAAA) {
    MovieRetirement retiring(X86_MEM32(ctx.ecx + 0x1C));
    // Scheduler drain must run outside the lock so a waiting worker can leave.
    __imp__sub_001EEAAA(ctx, base);
}

X86_FUNC(sub_00307DB0) {
    std::lock_guard<std::recursive_mutex> lock(g_cri_lifetime);
    const uint32_t wrapper = X86_MEM32(ctx.esp + 4);
    if (std::find(g_retiring_movies.begin(), g_retiring_movies.end(), wrapper) != g_retiring_movies.end()) {
        ctx.eax = 0;
        ctx.esp += 4;
        return;
    }
    __imp__sub_00307DB0(ctx, base);
}

X86_FUNC(sub_0030AC00) {
    std::lock_guard<std::recursive_mutex> lock(g_cri_lifetime);
    __imp__sub_0030AC00(ctx, base);
}

X86_FUNC(sub_0030AC40) {
    std::lock_guard<std::recursive_mutex> lock(g_cri_lifetime);
    __imp__sub_0030AC40(ctx, base);
}

X86_FUNC(sub_0030AD10) {
    std::lock_guard<std::recursive_mutex> lock(g_cri_lifetime);
    __imp__sub_0030AD10(ctx, base);
}
