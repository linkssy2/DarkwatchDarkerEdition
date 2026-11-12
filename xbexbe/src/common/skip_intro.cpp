#include "skip_intro.h"
#include "cpu/x86_ops.h"

X86_EXTERN_FUNC(__imp__sub_000C7A95);
X86_EXTERN_FUNC(__imp__sub_000C7B36);

// C7A95 only advances timed startup artwork; the caller still initializes every subsystem.
X86_FUNC(sub_000C7A95) {
    if (!DarkwatchSkipIntro()) { __imp__sub_000C7A95(ctx, base); return; }
    ctx.eax = (ctx.eax & 0xFFFFFF00u) | 1u;
    ctx.esp += 4;
}
// C7B36 plays only the boot intro. Campaign and Extras movies use their original paths.
X86_FUNC(sub_000C7B36) {
    if (!DarkwatchSkipIntro()) { __imp__sub_000C7B36(ctx, base); return; }
    ctx.esp += 4;
}
