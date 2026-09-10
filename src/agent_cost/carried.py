"""What a tool result costs after the turn that needed it.

A tool result is paid for more than once. It enters the prompt on the turn that
requested it, and every later turn in the session carries it again -- the cache
discounts that repeat, it does not remove it. So the cost of a call is not its
size but its size multiplied by how much session is left after it:

    carried_tokens = output_chars // CHARS_PER_TOKEN * turns_after

Measured on this project's own transcripts, tool output totals ~11.6M
characters while prompts total ~3.9B tokens; ranking calls by size alone points
at the wrong ones. A 25K-character file read on turn 20 of a 500-turn session
is carried ~480 more times; the same read on turn 495 is carried five. Sorting
by size puts them side by side, and they differ by two orders of magnitude.
"""

from __future__ import annotations

from agent_cost.models import SessionStats

# Rough characters-per-token ratio, matching the estimate the Codex parser
# already uses for sessions that report no usage. Every figure derived from it
# is an estimate and is labelled as one; the ranking it produces is what
# matters here, and that is insensitive to the exact divisor.
CHARS_PER_TOKEN = 4


def carried_cost(stats: SessionStats, limit: int = 5) -> dict | None:
    """Rank tool calls by what their output cost after the turn that used it.

    Returns None when the session carries no per-turn attribution -- parsers
    that cannot see individual calls, or samples recorded before attribution
    existed. `turns_after` deliberately excludes the turn that requested the
    output: that turn is the reason the call was made, and only the repeats
    after it are the part a different habit could have avoided.
    """
    samples = [s for s in stats.context_samples if s.get("tools")]
    if not samples:
        return None

    total_samples = len(stats.context_samples)
    calls = []
    for index, sample in enumerate(stats.context_samples):
        turns_after = total_samples - index - 1
        for tool in sample.get("tools") or []:
            output_chars = tool.get("output_chars") or 0
            if not output_chars:
                continue
            calls.append({
                "tool": tool.get("tool") or "tool",
                "detail": tool.get("detail") or "",
                "turn": sample.get("turn"),
                "output_chars": output_chars,
                "turns_after": turns_after,
                "carried_tokens": output_chars // CHARS_PER_TOKEN * turns_after,
            })

    if not calls:
        return None

    calls.sort(key=lambda call: call["carried_tokens"], reverse=True)
    total = sum(call["carried_tokens"] for call in calls)

    by_tool: dict[str, int] = {}
    for call in calls:
        by_tool[call["tool"]] = by_tool.get(call["tool"], 0) + call["carried_tokens"]

    return {
        "total_carried_tokens": total,
        "calls": calls[:limit],
        "call_count": len(calls),
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: kv[1], reverse=True)),
        # Share of the total held by the calls listed above, so the reader can
        # tell "fix these five" from "this is spread across everything".
        "top_share": (
            sum(call["carried_tokens"] for call in calls[:limit]) / total if total else 0.0
        ),
    }
