"""Default session locations, so the tool runs with no arguments.

Most people keep their agents where the installer put them. Looking there first
means the first command someone runs after `pip install` is `agent-cost
analyze`, not a path they have to go find.
"""

from __future__ import annotations

from pathlib import Path

# (agent, path). Entries that do not exist are skipped: a machine usually runs
# one or two of these, not all of them.
DEFAULT_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("Claude Code", "~/.claude/projects"),
    ("Codex", "~/.codex/sessions"),
    ("OpenCode", "~/.local/share/opencode/opencode.db"),
)


def discover_paths() -> list[Path]:
    """Return the default session locations present on this machine."""
    found = []
    for _, raw in DEFAULT_LOCATIONS:
        path = Path(raw).expanduser()
        if path.exists():
            found.append(path)
    return found


def describe_locations() -> str:
    """The locations searched, for the message shown when none of them exist."""
    return "\n".join(f"  {agent:<12} {raw}" for agent, raw in DEFAULT_LOCATIONS)
