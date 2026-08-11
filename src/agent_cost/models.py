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
