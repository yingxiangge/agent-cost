"""Baselines: snapshot how the agents behave now, compare after a change.

`analyze` says where the context went. It cannot say whether the change you
just made helped. A baseline records the current rollup and a cutoff time;
`diff` re-reads the sessions started after that cutoff and compares the two.

Windows of different lengths are not comparable in absolute terms — a baseline
over 200 sessions against a week of 20 says nothing about totals. Everything
compared here is therefore a rate: per turn, per session, or a share.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agent_cost.models import SessionStats

BASELINE_DIR = Path("~/.agent-cost/baselines").expanduser()
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9._-]+$")


def baseline_path(label: str) -> Path:
    """Path for a label, rejecting anything that is not a plain file name."""
    if not _SAFE_LABEL.match(label):
        raise ValueError(
            f"invalid baseline label {label!r}: use letters, digits, dot, dash or underscore"
        )
    return BASELINE_DIR / f"{label}.json"


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(raw: str) -> datetime | None:
    """Parse a session timestamp, or None when it has none we can read."""
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def save_baseline(label: str, summary: dict) -> Path:
    """Write a snapshot and the cutoff that later diffs measure from."""
    path = baseline_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": label,
        "cutoff": now_iso(),
        "summary": summary,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def load_baseline(label: str) -> dict:
    path = baseline_path(label)
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def list_baselines() -> list[dict]:
    if not BASELINE_DIR.exists():
        return []
    found = []
    for path in sorted(BASELINE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        found.append(
            {
                "label": data.get("label", path.stem),
                "cutoff": data.get("cutoff", ""),
                "sessions": data.get("summary", {}).get("totals", {}).get("sessions", 0),
            }
        )
    return found


def split_by_cutoff(
    sessions: list[SessionStats], cutoff: str
) -> tuple[list[SessionStats], int]:
    """Sessions started after `cutoff`, plus a count of undateable ones.

    Sessions with no readable timestamp cannot be placed on either side of the
    cutoff. They are excluded and counted, never silently folded into the new
    window: a session from before the change would flatter or spoil the result
    with no way to tell which.
    """
    mark = parse_time(cutoff)
    if mark is None:
        return list(sessions), 0
    after, undateable = [], 0
    for stats in sessions:
        started = parse_time(stats.created_at)
        if started is None:
            undateable += 1
        elif started > mark:
            after.append(stats)
    return after, undateable


def _pct_change(before: float, after: float) -> float | None:
    return (after - before) / before if before else None


def diff_summaries(before: dict, after: dict) -> dict:
    """Compare two rollups on rates only. See the module docstring."""
    b, a = before["totals"], after["totals"]

    metrics = [
        _metric("Per-turn prompt", b["prompt_per_turn"], a["prompt_per_turn"], "tokens"),
        _metric("Per-turn output", b["output_per_turn"], a["output_per_turn"], "tokens"),
        _metric(
            "Context:output ratio",
            b["context_to_output_ratio"],
            a["context_to_output_ratio"],
            "ratio",
        ),
        _metric("Cache hit", b["cache_hit_rate"], a["cache_hit_rate"], "share"),
    ]

    growth_b = (before.get("context_growth") or {}).get("growth_ratio")
    growth_a = (after.get("context_growth") or {}).get("growth_ratio")
    if growth_b is not None and growth_a is not None:
        metrics.append(_metric("Context growth", growth_b, growth_a, "ratio"))

    return {
        "windows": {
            "before_sessions": b["sessions"],
            "after_sessions": a["sessions"],
            "before_turns": b["turns"],
            "after_turns": a["turns"],
        },
        "metrics": [m for m in metrics if m is not None],
        "sources": _share_diff(before["sources"], after["sources"], "source"),
        "tools": _share_diff(before["tools"], after["tools"], "tool"),
        "waste": _waste_diff(before, after),
    }


def _metric(name: str, before, after, unit: str) -> dict | None:
    if before is None or after is None:
        return None
    row = {
        "name": name,
        "before": before,
        "after": after,
        "unit": unit,
        "pct_change": _pct_change(before, after),
    }
    if unit == "share":
        # A cache hit moving 97.1% -> 98.4% rose by 1.3 points, not 1.4 percent
        # of itself; reporting the latter invites the wrong conclusion.
        row["delta_pt"] = after - before
    return row


def _share_diff(before: list[dict], after: list[dict], key: str) -> list[dict]:
    """Compare shares in percentage points, keeping entries only one side has."""
    before_map = {item[key]: item["pct"] for item in before}
    after_map = {item[key]: item["pct"] for item in after}
    rows = []
    for name in sorted(set(before_map) | set(after_map)):
        b = before_map.get(name, 0.0)
        a = after_map.get(name, 0.0)
        rows.append({key: name, "before_pct": b, "after_pct": a, "delta_pt": a - b})
    # Largest movement first: what changed is the point, not what is biggest.
    rows.sort(key=lambda r: abs(r["delta_pt"]), reverse=True)
    return rows


def _waste_diff(before: dict, after: dict) -> list[dict]:
    """Waste counts normalised per session, since the windows differ in size."""
    b_sessions = before["totals"]["sessions"] or 1
    a_sessions = after["totals"]["sessions"] or 1
    rows = []
    for key, label in (
        ("repeated_file_reads", "repeated file reads"),
        ("repeated_tool_outputs", "duplicate tool output"),
        ("compaction_events", "compactions"),
    ):
        b = before["waste"][key] / b_sessions
        a = after["waste"][key] / a_sessions
        # Both sides rounding to zero is not a change worth a -100% headline.
        if round(b, 2) or round(a, 2):
            rows.append(
                {
                    "name": label,
                    "before": b,
                    "after": a,
                    "pct_change": _pct_change(b, a),
                }
            )
    return rows
