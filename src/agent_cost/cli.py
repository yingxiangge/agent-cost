from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_cost.analyze import analyze
from agent_cost.models import SessionStats
from agent_cost.parsers.codex import parse_codex_rollout
from agent_cost.parsers.hermes import parse_hermes_sessions
from agent_cost.pricing import estimate_cost
from agent_cost.report import format_analyze, format_inspect, format_stats_table


def _pricing_override() -> dict | None:
    env = __import__("os").environ.get("AGENT_COST_PRICING")
    return json.loads(env) if env else None


def _load(path: str) -> list[SessionStats]:
    p = Path(path)
    if p.is_dir():
        stats: list[SessionStats] = []
        for f in sorted(p.rglob("*.jsonl")):
            stats.append(parse_codex_rollout(f))
        for f in sorted(p.rglob("sessions.json")):
            stats.extend(parse_hermes_sessions(f))
        return stats
    if p.suffix == ".jsonl":
        return [parse_codex_rollout(p)]
    return parse_hermes_sessions(p)


def _fill_cost(stats: SessionStats) -> float | None:
    if stats.cost_status in ("actual", "estimated", "included"):
        return stats.estimated_cost_usd
    cost, status = estimate_cost(
        stats.input_tokens, stats.output_tokens, stats.cache_read_tokens, stats.cache_write_tokens, stats.model
    )
    if cost is not None:
        stats.estimated_cost_usd = cost
        stats.cost_status = status
    return cost


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-cost",
        description="Token, cache and context observability for AI coding agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Show a single session's usage and cost.")
    p_inspect.add_argument("path", help="Hermes sessions.json, a Codex rollout .jsonl, or a directory.")

    p_analyze = sub.add_parser("analyze", help="Context growth and action recommendations.")
    p_analyze.add_argument("path", help="Hermes sessions.json, a Codex rollout .jsonl, or a directory.")

    p_stats = sub.add_parser("stats", help="Aggregate totals across sessions.")
    p_stats.add_argument("path", help="Hermes sessions.json, a Codex rollout .jsonl, or a directory.")

    args = parser.parse_args(argv)
    stats = _load(args.path)
    if not stats:
        print("No sessions found.", file=sys.stderr)
        return 1

    if args.command == "inspect":
        for s in stats:
            _fill_cost(s)
            print(format_inspect(s))
            print()
    elif args.command == "analyze":
        for s in stats:
            _fill_cost(s)
            signals = analyze(s)
            print(format_analyze(s, signals))
            print()
    else:
        for s in stats:
            _fill_cost(s)
        print(format_stats_table(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
