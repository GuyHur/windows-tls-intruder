"""WebSocket connection hub — broadcasts events to all connected UI clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("intruder.ws")


class WebSocketHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        log.info("WS client connected (%d total)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        log.info("WS client disconnected (%d total)", len(self._clients))

    async def broadcast(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, default=str)
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def broadcast_sync(self, loop: asyncio.AbstractEventLoop, event: dict[str, Any]) -> None:
        """Fire-and-forget broadcast from a non-async (Frida callback) thread."""
        asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)


hub = WebSocketHub()
