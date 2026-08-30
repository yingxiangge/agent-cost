from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from agent_cost.analyze import analyze
from agent_cost.compare import compare_sessions
from agent_cost.discover import describe_locations, discover_paths
from agent_cost.models import SessionStats
from agent_cost.parsers.detect import load_path
from agent_cost.pricing import estimate_session_cost, validate_custom_pricing
from agent_cost.report import (
    format_analyze,
    format_compare,
    format_inspect,
    format_stats_table,
    format_summary,
)
from agent_cost.summary import summarize


_PATHS_HELP = "Session files or directories (default: auto-detect installed agents)."


def _pricing_override() -> dict | None:
    env = __import__("os").environ.get("AGENT_COST_PRICING")
    return _parse_pricing_json(env, "AGENT_COST_PRICING") if env else None


def _parse_pricing_json(raw: str, source: str) -> dict:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON for {source}: {exc.msg}") from exc
    if parsed is None:
        raise ValueError("custom pricing must be a JSON object mapping model names to rate cards")
    return validate_custom_pricing(parsed)


def _resolve_paths(paths: list[str]) -> tuple[list[str | Path], bool]:
    """Use the paths given, or fall back to wherever the agents install.

    Returns the paths and whether they were auto-detected, so the caller can
    say which directories it read rather than reporting numbers from
    locations the user never named.
    """
    if paths:
        return list(paths), False
    return list(discover_paths()), True


def _load_all(paths: list[str | Path]) -> list[SessionStats]:
    stats: list[SessionStats] = []
    for path in paths:
        loaded = load_path(path)
        stats.extend(loaded)
    return stats


def _fill_cost(
    stats: SessionStats,
    custom_pricing: dict | None = None,
    subscription: bool = False,
) -> float | None:
    if stats.cost_status in ("actual", "estimated", "included") and stats.estimated_cost_usd > 0:
        cost = stats.estimated_cost_usd
    else:
        cost, status = estimate_session_cost(stats, custom_pricing)
        if cost is None:
            return None
        stats.estimated_cost_usd = cost
        stats.cost_status = status

    if subscription and stats.cost_status == "estimated":
        # The tokens were real, the dollars were not spent: a subscription
        # already covers them. Keep the figure, change what it claims to be.
        stats.cost_status = "included"
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
    parser.add_argument(
        "--subscription",
        action="store_true",
        default=False,
        help="Bill through a Claude Pro/Max (or similar) subscription: report costs "
             "as API-equivalent value rather than money spent.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Show a single session's usage and cost.")
    p_inspect.add_argument("paths", nargs="*", help=_PATHS_HELP)

    p_analyze = sub.add_parser("analyze", help="Context growth and action recommendations.")
    p_analyze.add_argument("paths", nargs="*", help=_PATHS_HELP)
    p_analyze.add_argument(
        "--per-session",
        action="store_true",
        default=False,
        help="Print one analysis per session instead of the rollup.",
    )
    p_analyze.add_argument(
        "--json", action="store_true", default=False, help="Output analysis as JSON."
    )

    p_stats = sub.add_parser("stats", help="Aggregate totals across sessions.")
    p_stats.add_argument("paths", nargs="*", help=_PATHS_HELP)

    p_compare = sub.add_parser("compare", help="Compare usage, cache efficiency, and cost across multiple agents.")
    p_compare.add_argument("paths", nargs="*", help=_PATHS_HELP)
    p_compare.add_argument("--by-agent", action="store_true", default=False, help="Group comparison strictly by agent.")
    p_compare.add_argument("--json", action="store_true", default=False, help="Output comparison result as JSON.")

    args = parser.parse_args(argv)

    try:
        custom_pricing = _pricing_override()
        if args.pricing:
            custom_pricing = _parse_pricing_json(args.pricing, "--pricing")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    paths, auto_detected = _resolve_paths(args.paths)
    if not paths:
        print(
            "No session paths given, and none of the default locations exist:\n"
            + describe_locations(),
            file=sys.stderr,
        )
        return 1
    if auto_detected:
        print(f"Reading {', '.join(str(p) for p in paths)}\n", file=sys.stderr)

    stats = _load_all(paths)
    if not stats:
        print("No sessions found.", file=sys.stderr)
        return 1

    if args.command == "inspect":
        for s in stats:
            _fill_cost(s, custom_pricing, args.subscription)
            print(format_inspect(s))
            print()
    elif args.command == "analyze":
        pairs = []
        for s in stats:
            _fill_cost(s, custom_pricing, args.subscription)
            pairs.append((s, analyze(s)))
        if args.per_session:
            for s, signals in pairs:
                if args.json:
                    print(
                        json.dumps(
                            {"session": dataclasses.asdict(s), "analysis": signals},
                            ensure_ascii=False,
                        )
                    )
                else:
                    print(format_analyze(s, signals))
                print()
        else:
            summary = summarize(pairs)
            if args.json:
                print(json.dumps(summary, ensure_ascii=False))
            else:
                print(format_summary(summary))
    elif args.command == "stats":
        for s in stats:
            _fill_cost(s, custom_pricing, args.subscription)
        print(format_stats_table(stats))
    elif args.command == "compare":
        result = compare_sessions(stats, custom_pricing, args.subscription)
        if args.json:
            out = {
                "total_sessions": result.total_sessions,
                "total_tokens": result.total_tokens,
                "total_cost_usd": result.total_cost_usd,
                "total_cache_savings_usd": result.total_cache_savings_usd,
                # Dollar totals cover only the priced sessions; this says how many
                # were left out so a consumer never reads them as complete.
                "unpriced_sessions": result.unpriced_sessions,
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
