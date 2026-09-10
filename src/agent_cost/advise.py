"""Turn carried cost into advice a future session can act on.

`carried_cost` ranks individual calls, which answers "what was expensive".
Advice needs a different question: "what do I keep doing". A call that happened
once cannot be prevented next time -- there is nothing to change. A call that
happened seventeen times is a habit, and a habit is actionable.

So this aggregates carried cost across sessions by the call itself (tool plus
its argument) and reports only what recurs. On this project's own transcripts
the recurring calls hold 23.3% of all carried cost, led by the same three files
read in full over and over.

The result is meant to be read at the *start* of a session, not the end. Ranking
by carried cost needs to know how many turns followed a call, which is only
knowable afterwards -- so the measurement is historical and the delivery is
up front, as notes in a project file or a SessionStart hook.
"""

from __future__ import annotations

from agent_cost.analyze import classify_tool
from agent_cost.carried import carried_cost
from agent_cost.models import SessionStats

# One line of advice per tool category, keyed by the same classifier the
# analysis uses. Derived from the category rather than written per tool, so a
# newly seen tool name inherits advice instead of falling through to nothing.
_ADVICE_BY_CATEGORY = {
    "file_read": "Locate with a search first, then read only the line range you need.",
    "shell": "Filter the output at the source (head/tail/grep) or write it to a file.",
    "search": "Narrow the path and add file-type filters so the match set stays small.",
    "web": "Extract the passage you need rather than ingesting the whole page.",
    "file_edit": "Prefer targeted patches over whole-file writes.",
    "subagent": "Ask the subagent for findings, not a transcript.",
    "other": "Reduce how much this call returns, or make it less often.",
}

# A call seen once is an event, not a habit: there is no next time to change.
MIN_OCCURRENCES = 2


def advise(
    sessions: list[SessionStats], limit: int = 8, min_occurrences: int = MIN_OCCURRENCES
) -> dict:
    """Aggregate carried cost across sessions into recurring, fixable habits."""
    habits: dict[tuple[str, str], dict] = {}
    total_carried = 0
    analyzed = 0

    for stats in sessions:
        # No cap: a habit's cost is the sum over every occurrence, so taking
        # only each session's top calls would undercount the frequent ones.
        result = carried_cost(stats, limit=len(stats.context_samples) or 1)
        if not result:
            continue
        analyzed += 1
        total_carried += result["total_carried_tokens"]
        for call in result["calls"]:
            key = (call["tool"], call["detail"])
            habit = habits.setdefault(
                key,
                {
                    "tool": call["tool"],
                    "detail": call["detail"],
                    "occurrences": 0,
                    "carried_tokens": 0,
                    "output_chars": 0,
                },
            )
            habit["occurrences"] += 1
            habit["carried_tokens"] += call["carried_tokens"]
            habit["output_chars"] += call["output_chars"]

    recurring = [h for h in habits.values() if h["occurrences"] >= min_occurrences]
    recurring.sort(key=lambda habit: habit["carried_tokens"], reverse=True)

    for habit in recurring:
        category, label = classify_tool(habit["tool"])
        habit["category"] = category
        habit["category_label"] = label
        habit["advice"] = _ADVICE_BY_CATEGORY[category]
        habit["avg_output_chars"] = habit["output_chars"] // habit["occurrences"]

    return {
        "sessions_analyzed": analyzed,
        "sessions_seen": len(sessions),
        "total_carried_tokens": total_carried,
        "recurring_carried_tokens": sum(h["carried_tokens"] for h in recurring),
        "habits": recurring[:limit],
        "habit_count": len(recurring),
        "min_occurrences": min_occurrences,
    }
