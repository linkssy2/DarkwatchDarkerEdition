#include "cpu/x86_ops.h"

X86_EXTERN_FUNC(__imp__sub_00222DBC);

X86_FUNC(sub_00222DBC) {
    // This protected call saves its resume ESP 0x58 bytes below the entry stack.
    const uint32_t resume_esp = ctx.esp - 0x58u;
    try {
        __imp__sub_00222DBC(ctx, base);
    } catch (const X86Resume& resume) {
        if (resume.target != 0x222DE4u || resume.esp != resume_esp) throw;
        x86_resume(ctx, base, resume);
    }
}

void DarkwatchScriptResume(X86Context& ctx, uint8_t* base) {
    // The original longjmp must discard nested host calls, not return to abort.
    const uint32_t target = x86_read32(ctx, base, ctx.edx + 0x14u);
    if (target == 0x222DE4u) throw X86Resume{target, ctx.esp};
}
