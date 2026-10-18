#include <mutex>
#include "cpu/x86_ops.h"

X86_EXTERN_FUNC(__imp__sub_0030AC00);
X86_EXTERN_FUNC(__imp__sub_0030AC40);
X86_EXTERN_FUNC(__imp__sub_0030AD10);

namespace {
// The original global drain gate cannot exclude a worker on another host core.
// Keep its wait outside this lock; destruction recursively invokes stop/reset.
std::recursive_mutex g_cri_lifetime;
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
