#pragma once
#include <cstdint>
struct X86Context;

// E65E8: true cancels the native restart callback before it truncates history.
bool DarkwatchCampaignReplayBegin(X86Context& ctx, uint8_t* base);
// Return to a campaign menu, before its profiles are replaced or reused.
void DarkwatchCampaignReplayEnd(X86Context& ctx, uint8_t* base);
// Campaign-entry callbacks must reject profile reuse if restoration failed.
bool DarkwatchCampaignReplayFinish(X86Context& ctx, uint8_t* base);
bool DarkwatchCampaignReplayBeforeChapter(X86Context& ctx, uint8_t* base);
bool DarkwatchCampaignReplayTakeFailure();

