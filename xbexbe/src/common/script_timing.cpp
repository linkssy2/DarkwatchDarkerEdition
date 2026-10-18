#include "cpu/x86_context.h"

void DarkwatchActorScriptTick(X86Context& ctx, uint8_t*) {
    // LuaComponent uses dt only as a 10 ms gate; fast frames must still resume its scripts.
    double& gate = ctx.st[ctx.top];
    if (gate > 0.0 && gate < double(0.01f)) gate = double(0.01f);
}
