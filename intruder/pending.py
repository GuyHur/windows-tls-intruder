"""
PendingStore — holds intercepted messages waiting for UI resolution.

Each message gets a threading.Event so the Frida callback thread can block
until the UI resolves it (forward / replace / drop) or the auto-forward
timeout fires.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from intruder.config import settings
from intruder.models import Direction, InterceptedMessage, ResolveAction

log = logging.getLogger("intruder.pending")


class _PendingEntry:
    __slots__ = ("message", "event", "action", "replacement_data")

    def __init__(self, message: InterceptedMessage) -> None:
        self.message = message
        self.event = threading.Event()
        self.action: ResolveAction = ResolveAction.FORWARD
        self.replacement_data: bytes | None = None


class PendingStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _PendingEntry] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_resolved_callback: Any = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_on_resolved(self, cb: Any) -> None:
        self._on_resolved_callback = cb

    # -- called from Frida thread (blocking) ----------------------------------

    def enqueue(self, msg: InterceptedMessage) -> tuple[ResolveAction, bytes | None]:
        """
        Enqueue a message and **block** until the UI resolves it or the timeout
        fires.  Returns (action, replacement_data | None).
        """
        entry = _PendingEntry(msg)

        with self._lock:
            if len(self._entries) >= settings.max_pending:
                log.warning("Pending store full — auto-forwarding oldest entry")
                _, oldest = self._entries.popitem(last=False)
                oldest.event.set()
            self._entries[msg.id] = entry

        timeout_s = settings.auto_forward_timeout_ms / 1000.0
        entry.event.wait(timeout=timeout_s)

        with self._lock:
            self._entries.pop(msg.id, None)

        if not entry.event.is_set():
            log.debug("Auto-forwarded %s after timeout", msg.id)

        return entry.action, entry.replacement_data

    # -- called from asyncio (FastAPI route) -----------------------------------

    def resolve(
        self,
        message_id: str,
        action: ResolveAction,
        data_b64: str | None = None,
    ) -> bool:
        with self._lock:
            entry = self._entries.get(message_id)
            if entry is None:
                return False
            entry.action = action
            if action == ResolveAction.REPLACE and data_b64:
                entry.replacement_data = base64.b64decode(data_b64)
            entry.event.set()
        return True

    def list_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._serialize(e) for e in self._entries.values()]

    @staticmethod
    def _serialize(entry: _PendingEntry) -> dict[str, Any]:
        m = entry.message
        return {
            "id": m.id,
            "session_id": m.session_id,
            "pid": m.pid,
            "direction": m.direction.value,
            "data_b64": base64.b64encode(m.data).decode() if m.data else "",
            "data_len": len(m.data) if m.data else 0,
            "metadata": m.metadata,
            "created_at": m.created_at,
        }


pending_store = PendingStore()
