"""Small progress reporter used by long-running CLI tools."""

from __future__ import annotations

import sys
import time


class ProgressReporter:
    """Print timestamped progress lines to stderr."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.started_at = time.monotonic()

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return

        elapsed = time.monotonic() - self.started_at
        print(f"[{elapsed:7.1f}s] {message}", file=sys.stderr, flush=True)
