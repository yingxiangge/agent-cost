from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from agent_cost.analyze import DEFAULT_BUDGET, analyze, parse_budget
from agent_cost.baseline import (
    diff_summaries,
    list_baselines,
    load_baseline,
    save_baseline,
    split_by_cutoff,
)
from agent_cost.advise import advise
from agent_cost.compare import compare_sessions
from agent_cost.discover import describe_locations, discover_paths
from agent_cost.models import SessionStats
from agent_cost.parsers.detect import load_path
from agent_cost.pricing import estimate_session_cost, validate_custom_pricing
from agent_cost.report import (
    HOOK_SNIPPET,
    format_advice,
    format_analyze,
    format_compare,
    format_inspect,
    format_diff,
    format_stats_table,
    format_summary,
)
from agent_cost.summary import summarize


_PATHS_HELP = "Session files or directories (default: auto-detect installed agents)."


def _pricing_override() -> dict | None:
    env = __import__("os").environ.get("AGENT_COST_PRICING")
    return _parse_pricing_json(env, "AGENT_COST_PRICING") if env else None


def _budget_override(flag: str | None) -> dict | None:
    """Resolve the prompt budget: flag first, then environment, else default.

    Returns None when neither is set so `analyze()` applies its own default,
    rather than freezing today's default into every call site.
    """
    if flag:
        return parse_budget(flag)
    env = __import__("os").environ.get("AGENT_COST_BUDGET")
    if env:
        try:
            return parse_budget(env)
        except ValueError as exc:
            raise ValueError(f"invalid AGENT_COST_BUDGET: {exc}") from None
    return None


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
    p_analyze.add_argument(
        "--budget",
        default=None,
        metavar="SPEC",
        help="Prompt-size budget, e.g. 'warning:100k,critical:150k'. "
             f"Defaults to warning:{DEFAULT_BUDGET['warning'] // 1000}k,"
             f"critical:{DEFAULT_BUDGET['critical'] // 1000}k, "
             "or the AGENT_COST_BUDGET environment variable.",
    )

    p_advise = sub.add_parser(
        "advise",
        help="Recurring calls that cost the most, as notes to start a session with.",
    )
    p_advise.add_argument("paths", nargs="*", help=_PATHS_HELP)
    p_advise.add_argument(
        "--limit", type=int, default=8, help="How many habits to report (default: 8)."
    )
    p_advise.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="How often a call must recur to count as a habit (default: 2).",
    )
    p_advise.add_argument(
        "--hook",
        action="store_true",
        default=False,
        help="Print a Claude Code settings snippet that runs this at session start, "
             "and exit. Nothing is written for you.",
    )
    p_advise.add_argument(
        "--json", action="store_true", default=False, help="Output the habits as JSON."
    )

    p_stats = sub.add_parser("stats", help="Aggregate totals across sessions.")
    p_stats.add_argument("paths", nargs="*", help=_PATHS_HELP)

    p_baseline = sub.add_parser(
        "baseline", help="Save a snapshot of how the agents behave right now."
    )
    p_baseline.add_argument("paths", nargs="*", help=_PATHS_HELP)
    p_baseline.add_argument(
        "--label", default="default", help="Name for this baseline (default: default)."
    )
    p_baseline.add_argument(
        "--list", action="store_true", default=False, help="List saved baselines and exit."
    )

    p_diff = sub.add_parser(
        "diff", help="Compare sessions since a baseline against that baseline."
    )
    p_diff.add_argument("paths", nargs="*", help=_PATHS_HELP)
    p_diff.add_argument(
        "--against", default="default", help="Baseline to compare against (default: default)."
    )
    p_diff.add_argument(
        "--json", action="store_true", default=False, help="Output the comparison as JSON."
    )

    p_compare = sub.add_parser("compare", help="Compare usage, cache efficiency, and cost across multiple agents.")
    p_compare.add_argument("paths", nargs="*", help=_PATHS_HELP)
    p_compare.add_argument("--by-agent", action="store_true", default=False, help="Group comparison strictly by agent.")
    p_compare.add_argument("--json", action="store_true", default=False, help="Output comparison result as JSON.")

    args = parser.parse_args(argv)

    try:
        custom_pricing = _pricing_override()
        if args.pricing:
            custom_pricing = _parse_pricing_json(args.pricing, "--pricing")
        budget = _budget_override(getattr(args, "budget", None))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.command == "advise" and args.hook:
        print(HOOK_SNIPPET)
        return 0

    if args.command == "baseline" and args.list:
        saved = list_baselines()
        if not saved:
            print("No baselines saved yet. Run: agent-cost baseline --label <name>")
            return 0
        for item in saved:
            print(
                f"{item['label']:<24} saved {item['cutoff'][:10]}  "
                f"{item['sessions']} sessions"
            )
        return 0

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
            pairs.append((s, analyze(s, budget)))
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
    elif args.command == "advise":
        result = advise(
            stats, limit=args.limit, min_occurrences=args.min_occurrences
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(format_advice(result))
    elif args.command == "baseline":
        pairs = [(s, analyze(s)) for s in stats]
        path = save_baseline(args.label, summarize(pairs))
        print(
            f"Baseline '{args.label}' saved to {path}\n"
            f"{len(stats)} sessions recorded. Make your change, then run: "
            f"agent-cost diff --against {args.label}"
        )
    elif args.command == "diff":
        try:
            snapshot = load_baseline(args.against)
        except FileNotFoundError:
            print(
                f"No baseline named '{args.against}'. "
                f"Save one first: agent-cost baseline --label {args.against}",
                file=sys.stderr,
            )
            return 1
        recent, undateable = split_by_cutoff(stats, snapshot["cutoff"])
        if not recent:
            print(
                f"No sessions started since the baseline was saved "
                f"({snapshot['cutoff'][:10]}); nothing to compare yet.",
                file=sys.stderr,
            )
            return 1
        for s in recent:
            _fill_cost(s, custom_pricing, args.subscription)
        after = summarize([(s, analyze(s)) for s in recent])
        diff = diff_summaries(snapshot["summary"], after)
        if args.json:
            print(
                json.dumps(
                    {
                        "baseline": args.against,
                        "cutoff": snapshot["cutoff"],
                        "undateable_sessions": undateable,
                        "diff": diff,
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(
                format_diff(
                    args.against, snapshot["cutoff"], diff, undateable
                )
            )
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
