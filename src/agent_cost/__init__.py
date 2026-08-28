"""Token, cache and context observability for AI coding agents."""

from importlib.metadata import PackageNotFoundError, version as _dist_version

from .models import SessionStats
from .pricing import estimate_cost

__all__ = ["SessionStats", "estimate_cost"]

try:
    # Read the version off the installed distribution so it cannot drift from
    # pyproject.toml the way a hand-maintained literal did (it sat at 0.1.0
    # through the 0.2 and 0.3 releases).
    __version__ = _dist_version("agent-cost-tracker")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+source"
