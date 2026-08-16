from __future__ import annotations

from dataclasses import dataclass, field
from agent_cost.models import SessionStats
from agent_cost.pricing import estimate_cost


@dataclass
class AgentSummary:
    agent: str
    session_count: int = 0
    models: set[str] = field(default_factory=set)
    total_tokens: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    turns: int = 0
    tool_calls: int = 0
    compaction_events: int = 0
    unpriced_sessions: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def cache_hit_rate(self) -> float:
        prompt = self.prompt_tokens
        return self.cache_read_tokens / prompt if prompt else 0.0

    @property
    def avg_cost_per_session(self) -> float:
        return self.estimated_cost_usd / self.session_count if self.session_count else 0.0

    @property
    def avg_tokens_per_turn(self) -> float:
        return self.total_tokens / self.turns if self.turns else 0.0


@dataclass
class CompareResult:
    sessions: list[SessionStats]
    agent_summaries: dict[str, AgentSummary]
    total_sessions: int
    total_tokens: int
    total_cost_usd: float
    total_cache_savings_usd: float
    unpriced_sessions: int = 0
    insights: list[str] = field(default_factory=list)


def compare_sessions(sessions: list[SessionStats], custom_pricing: dict | None = None) -> CompareResult:
    """Perform side-by-side comparative analysis of multiple agent sessions."""
    summaries: dict[str, AgentSummary] = {}
    total_tokens = 0
    total_cost = 0.0
    total_savings = 0.0

    for s in sessions:
        # Ensure cost is filled
        if s.cost_status == "unknown" or s.estimated_cost_usd == 0.0:
            c, st = estimate_cost(
                s.input_tokens, s.output_tokens, s.cache_read_tokens, s.cache_write_tokens, s.model, custom_pricing
            )
            if c is not None:
                s.estimated_cost_usd = c
                s.cost_status = st

        agent = s.agent or "unknown"
        if agent not in summaries:
            summaries[agent] = AgentSummary(agent=agent)

        summary = summaries[agent]
        summary.session_count += 1
        if s.model:
            summary.models.add(s.model)
        summary.total_tokens += s.total_tokens
        summary.input_tokens += s.input_tokens
        summary.cache_read_tokens += s.cache_read_tokens
        summary.cache_write_tokens += s.cache_write_tokens
        summary.output_tokens += s.output_tokens
        summary.estimated_cost_usd += s.estimated_cost_usd
        summary.turns += s.turns
        summary.tool_calls += s.tool_calls
        summary.compaction_events += s.compaction_events
        if s.cost_status == "unknown":
            summary.unpriced_sessions += 1

        total_tokens += s.total_tokens
        total_cost += s.estimated_cost_usd

        # Calculate approximate cache savings (cost if cache_read was full price input)
        if s.cache_read_tokens > 0:
            # Assume base input price difference
            full_cost, _ = estimate_cost(
                s.input_tokens + s.cache_read_tokens,
                s.output_tokens,
                0,
                s.cache_write_tokens,
                s.model,
                custom_pricing,
            )
            if full_cost is not None and full_cost > s.estimated_cost_usd:
                total_savings += (full_cost - s.estimated_cost_usd)

    # Generate insights
    insights = []
    if summaries:
        # Highest cache efficiency
        best_cache = max(summaries.values(), key=lambda a: a.cache_hit_rate)
        if best_cache.cache_hit_rate > 0.1:
            insights.append(
                f"Highest cache efficiency: {best_cache.agent} ({best_cache.cache_hit_rate*100:.1f}% hit rate)."
            )

        # Most tool active
        most_tools = max(summaries.values(), key=lambda a: a.tool_calls)
        if most_tools.tool_calls > 0:
            insights.append(
                f"Most tool intensive: {most_tools.agent} ({most_tools.tool_calls} total tool calls)."
            )

        # Cost saving impact
        if total_savings > 0:
            insights.append(f"Prompt caching saved approx. ${total_savings:.2f} across analyzed sessions.")

    unpriced = sum(1 for s in sessions if s.cost_status == "unknown")
    if unpriced:
        insights.append(
            f"{unpriced} of {len(sessions)} sessions have no rate card and are excluded from "
            f"every dollar figure above. Supply rates with --pricing to include them."
        )

    return CompareResult(
        sessions=sessions,
        agent_summaries=summaries,
        total_sessions=len(sessions),
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        total_cache_savings_usd=total_savings,
        unpriced_sessions=unpriced,
        insights=insights,
    )
