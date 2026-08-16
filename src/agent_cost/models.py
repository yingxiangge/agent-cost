from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionStats:
    """Aggregated usage statistics for one agent session."""

    agent: str
    session_key: str
    model: str = ""
    platform: str = ""
    cli_version: str = ""
    cwd: str = ""
    created_at: str = ""
    updated_at: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_status: str = "unknown"
    turns: int = 0
    tool_calls: int = 0
    compaction_events: int = 0
    context_samples: list[dict] = field(default_factory=list)
    source_chars: dict[str, int] = field(default_factory=dict)
    # Tokens split by billing mode, keyed "<speed>|<inference_geo>". Fast mode and
    # US-pinned inference are priced differently and can change mid-session, so
    # the totals above are not enough to price a session correctly. Parsers that
    # cannot observe these modes leave this empty and are priced off the totals.
    billing_buckets: dict[str, dict[str, int]] = field(default_factory=dict)

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_write: int,
        speed: str = "standard",
        inference_geo: str = "",
    ) -> None:
        """Add one turn's usage to both the flat totals and its billing bucket."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read
        self.cache_write_tokens += cache_write

        bucket = self.billing_buckets.setdefault(
            f"{speed or 'standard'}|{inference_geo or ''}",
            {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
        )
        bucket["input"] += input_tokens
        bucket["output"] += output_tokens
        bucket["cache_read"] += cache_read
        bucket["cache_write"] += cache_write

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        prompt = self.prompt_tokens
        return self.cache_read_tokens / prompt if prompt else 0.0
