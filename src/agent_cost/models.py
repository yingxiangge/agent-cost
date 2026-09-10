from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


def _new_tool_entry() -> dict[str, int]:
    return {"calls": 0, "output_chars": 0, "images": 0, "image_tokens": 0}


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
    # Detailed tool usage split by tool name:
    # {tool_name: {"calls": int, "output_chars": int, "images": int, "image_tokens": int}}
    # Images are tracked apart from output_chars: a screenshot is billed on its
    # pixel dimensions, so folding its base64 payload into a character count
    # would swamp every text tool with a number that means nothing.
    tool_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    # Sanitized call arguments and output fingerprints used by analyze().
    # Only arguments and hashes are retained; session contents are never stored.
    tool_call_inputs: dict[str, list[str]] = field(default_factory=dict)
    tool_output_fingerprints: dict[str, dict[str, dict[str, int]]] = field(
        default_factory=dict
    )
    # Tokens split by billing mode, keyed "<speed>|<inference_geo>". Fast mode and
    # US-pinned inference are priced differently and can change mid-session, so
    # the totals above are not enough to price a session correctly. Parsers that
    # cannot observe these modes leave this empty and are priced off the totals.
    billing_buckets: dict[str, dict[str, int]] = field(default_factory=dict)
    # Tool output seen since the last context sample, waiting to be attributed
    # to the turn whose prompt it inflates. A tool result lands in the
    # transcript *before* the usage figure that carries it, so the buffer is
    # drained by `sample_context()` rather than filled by it.
    pending_tool_output: list[dict] = field(default_factory=list)

    def record_tool_call(
        self, tool_name: str, char_count: int = 0, input_value: object = None
    ) -> None:
        """Record a tool invocation and optional request character footprint."""
        name = str(tool_name or "unknown")
        entry = self.tool_stats.setdefault(name, _new_tool_entry())
        entry["calls"] += 1
        self.tool_calls += 1
        if char_count > 0:
            self.source_chars["tool_calls"] = self.source_chars.get("tool_calls", 0) + char_count
        if input_value is not None:
            try:
                encoded = json.dumps(
                    input_value, sort_keys=True, ensure_ascii=False, default=str
                )
            except (TypeError, ValueError):
                encoded = str(input_value)
            self.tool_call_inputs.setdefault(name, []).append(encoded)

    def record_tool_output(
        self,
        tool_name: str,
        output_chars: int,
        images: int = 0,
        image_tokens: int = 0,
        content: object = None,
        detail: str = "",
    ) -> None:
        """Record tool output attributed to a specific tool.

        `output_chars` counts textual payload only. Images are recorded as a
        count plus their estimated token footprint and deliberately kept out of
        both `output_chars` and `source_chars`, which are character pools.

        `detail` is a short, already-sanitized label for the call that produced
        this output (a command line, a file path) used to name the culprit
        behind a context jump. Parsers that cannot supply one leave it empty
        and the turn is reported without attribution.
        """
        name = str(tool_name or "unknown")
        entry = self.tool_stats.setdefault(name, _new_tool_entry())
        entry["output_chars"] = entry.get("output_chars", 0) + output_chars
        entry["images"] = entry.get("images", 0) + images
        entry["image_tokens"] = entry.get("image_tokens", 0) + image_tokens
        if output_chars or image_tokens:
            self.pending_tool_output.append({
                "tool": name,
                "detail": str(detail or ""),
                "output_chars": output_chars,
                "image_tokens": image_tokens,
            })
        if output_chars:
            self.source_chars["tool_output"] = self.source_chars.get("tool_output", 0) + output_chars
        if content is not None and output_chars > 0:
            try:
                serialized = json.dumps(
                    content, sort_keys=True, ensure_ascii=False, default=str
                )
            except (TypeError, ValueError):
                serialized = str(content)
            digest = hashlib.sha256(
                serialized.encode("utf-8", errors="replace")
            ).hexdigest()
            by_hash = self.tool_output_fingerprints.setdefault(name, {})
            item = by_hash.setdefault(digest, {"calls": 0, "output_chars": 0})
            item["calls"] += 1
            item["output_chars"] += output_chars

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

    def sample_context(self, prompt_tokens: int, turn: int | None = None) -> dict:
        """Record this turn's prompt size and attribute its growth to tools.

        `delta` is this turn's prompt minus the previous sample's, so the first
        sample reports the whole prompt (session preamble, not tool growth) and
        a compaction shows up as a negative delta. Callers looking for the
        worst tool-driven jump skip the first sample for that reason.

        The pending buffer holds every tool result recorded since the previous
        sample -- exactly the payload this turn's prompt had to carry -- and is
        drained here so each result is attributed to one turn only. Entries are
        ordered largest-first so the culprit is `tools[0]`.
        """
        previous = (
            self.context_samples[-1]["estimated_prompt_tokens"]
            if self.context_samples
            else 0
        )
        tools = sorted(
            self.pending_tool_output,
            key=lambda item: (item["output_chars"], item["image_tokens"]),
            reverse=True,
        )
        self.pending_tool_output = []
        sample = {
            "turn": self.turns if turn is None else turn,
            "estimated_prompt_tokens": prompt_tokens,
            "delta": prompt_tokens - previous,
            "tools": tools,
        }
        self.context_samples.append(sample)
        return sample

    @property
    def image_count(self) -> int:
        return sum(info.get("images", 0) for info in self.tool_stats.values())

    @property
    def image_tokens(self) -> int:
        return sum(info.get("image_tokens", 0) for info in self.tool_stats.values())

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
