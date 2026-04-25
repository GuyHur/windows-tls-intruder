"""
InterceptState — global toggle controlling whether packets are held for
manual review or auto-forwarded immediately.

When enabled=False (default): packets pass through without blocking.
When enabled=True: packets are queued in PendingStore for UI resolution.

The _should_intercept() method in MessageRouter is the single extension
point for future filter logic.
"""

from __future__ import annotations

import threading


class InterceptState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled: bool = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value


intercept_state = InterceptState()
