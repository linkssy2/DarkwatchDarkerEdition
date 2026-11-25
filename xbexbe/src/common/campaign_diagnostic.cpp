// Private campaign navigation only; absent from release binaries.
#ifndef XBE_RELEASE
#include "cpu/x86_context.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <cstdlib>
#include <cstring>

extern "C" void __imp__sub_000E6BBB(X86Context&, uint8_t*);
extern "C" void sub_000E6BBB(X86Context& ctx, uint8_t* base) {
    const uint32_t menu = ctx.ecx;
    __imp__sub_000E6BBB(ctx, base);
    const char* enabled = std::getenv("DARKWATCH_DIAGNOSTIC_CHAPTERS");
    if (!enabled || std::strcmp(enabled,"1") || base != kernel::g_base ||
        !menu || uint64_t(menu)+0x74 > (uint64_t(1)<<32)) return;
    for (uint64_t p=menu & ~uint64_t(mem::kPage-1); p<uint64_t(menu)+0x74; p+=mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return;
    uint32_t type=0,mode=0;
    std::memcpy(&type,base+menu,4);std::memcpy(&mode,base+menu+0x70,4);
    if (type!=0x429B80 || mode!=0) return;
    // Native mode 1 enumerates the full TOC and starts chapters through the
    // difficulty page. Mode 0 enumerates saved checkpoints instead. No profile
    // records are fabricated or marked complete; coop/movie menus are untouched.
    mode=1;std::memcpy(base+menu+0x70,&mode,4);
}
#endif
