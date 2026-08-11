from __future__ import annotations

import json
from pathlib import Path

from agent_cost.models import SessionStats


def parse_hermes_sessions(path: str | Path) -> list[SessionStats]:
    """Parse a Hermes sessions.json file into SessionStats objects."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    records = raw.values() if isinstance(raw, dict) else raw
    stats: list[SessionStats] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        s = SessionStats(
            agent="hermes",
            session_key=str(rec.get("session_key") or rec.get("session_id") or ""),
            model=str(rec.get("model") or ""),
            platform=str(rec.get("platform") or ""),
            created_at=str(rec.get("created_at") or ""),
            updated_at=str(rec.get("updated_at") or ""),
            input_tokens=int(rec.get("input_tokens") or 0),
            output_tokens=int(rec.get("output_tokens") or 0),
            cache_read_tokens=int(rec.get("cache_read_tokens") or 0),
            cache_write_tokens=int(rec.get("cache_write_tokens") or 0),
            estimated_cost_usd=float(rec.get("estimated_cost_usd") or 0.0),
            cost_status=str(rec.get("cost_status") or "unknown"),
            turns=int(rec.get("turn_count") or 0),
        )
        last_prompt = int(rec.get("last_prompt_tokens") or 0)
        if last_prompt:
            s.context_samples.append({"turn": 1, "estimated_prompt_tokens": last_prompt})
        stats.append(s)
    return stats
