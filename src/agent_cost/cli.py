from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from agent_cost.analyze import analyze
from agent_cost.compare import compare_sessions
from agent_cost.models import SessionStats
from agent_cost.parsers.detect import load_path
from agent_cost.pricing import estimate_cost
from agent_cost.report import format_analyze, format_compare, format_inspect, format_stats_table


def _pricing_override() -> dict | None:
    env = __import__("os").environ.get("AGENT_COST_PRICING")
    return json.loads(env) if env else None


def _load_all(paths: list[str]) -> list[SessionStats]:
    stats: list[SessionStats] = []
    for path in paths:
        loaded = load_path(path)
        stats.extend(loaded)
    return stats


def _fill_cost(stats: SessionStats, custom_pricing: dict | None = None) -> float | None:
    if stats.cost_status in ("actual", "estimated", "included") and stats.estimated_cost_usd > 0:
        return stats.estimated_cost_usd
    cost, status = estimate_cost(
        stats.input_tokens,
        stats.output_tokens,
        stats.cache_read_tokens,
        stats.cache_write_tokens,
        stats.model,
        custom_pricing,
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
    parser.add_argument(
        "--pricing",
        help="JSON string with custom pricing override.",
        default=None,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Show a single session's usage and cost.")
    p_inspect.add_argument("paths", nargs="+", help="Session files or directories.")

    p_analyze = sub.add_parser("analyze", help="Context growth and action recommendations.")
    p_analyze.add_argument("paths", nargs="+", help="Session files or directories.")

    p_stats = sub.add_parser("stats", help="Aggregate totals across sessions.")
    p_stats.add_argument("paths", nargs="+", help="Session files or directories.")

    p_compare = sub.add_parser("compare", help="Compare usage, cache efficiency, and cost across multiple agents.")
    p_compare.add_argument("paths", nargs="+", help="Session files or directories to compare.")
    p_compare.add_argument("--by-agent", action="store_true", default=False, help="Group comparison strictly by agent.")
    p_compare.add_argument("--json", action="store_true", default=False, help="Output comparison result as JSON.")

    args = parser.parse_args(argv)

    custom_pricing = _pricing_override()
    if args.pricing:
        try:
            custom_pricing = json.loads(args.pricing)
        except json.JSONDecodeError:
            print("Error: Invalid JSON for --pricing", file=sys.stderr)
            return 2

    stats = _load_all(args.paths)
    if not stats:
        print("No sessions found.", file=sys.stderr)
        return 1

    if args.command == "inspect":
        for s in stats:
            _fill_cost(s, custom_pricing)
            print(format_inspect(s))
            print()
    elif args.command == "analyze":
        for s in stats:
            _fill_cost(s, custom_pricing)
            signals = analyze(s)
            print(format_analyze(s, signals))
            print()
    elif args.command == "stats":
        for s in stats:
            _fill_cost(s, custom_pricing)
        print(format_stats_table(stats))
    elif args.command == "compare":
        result = compare_sessions(stats, custom_pricing)
        if args.json:
            out = {
                "total_sessions": result.total_sessions,
                "total_tokens": result.total_tokens,
                "total_cost_usd": result.total_cost_usd,
                "total_cache_savings_usd": result.total_cache_savings_usd,
                "insights": result.insights,
                "agents": {
                    k: dataclasses.asdict(v) for k, v in result.agent_summaries.items()
                },
            }
            # Convert sets to lists for json serialization
            for a in out["agents"].values():
                if isinstance(a.get("models"), set):
                    a["models"] = list(a["models"])
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(format_compare(result, by_agent=args.by_agent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
