"""
MessageRouter — receives raw Frida messages, converts them to InterceptedMessage,
pushes them through PendingStore for UI resolution, then posts the (possibly
modified) response back to the Frida script so the hooked thread can resume.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any, Optional

from intruder.intercept_state import intercept_state
from intruder.models import Direction, InterceptedMessage, ResolveAction
from intruder.pending import pending_store
from intruder.ws_hub import hub

log = logging.getLogger("intruder.router")

_SCRIPT_LEVEL_RE = re.compile(r'\[(WARN|INFO|ERROR|DEBUG)\]')
_SCRIPT_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
}


def _log_frida_console(pid: int, payload: str) -> None:
    """Route Frida console.log/warn/error messages into Python logging."""
    m = _SCRIPT_LEVEL_RE.search(payload)
    level = _SCRIPT_LEVEL_MAP.get(m.group(1) if m else "", logging.INFO)
    log.log(level, "Script [pid=%d]: %s", pid, payload)

_MSG_TYPE_MAP = {"s": Direction.SEND, "r": Direction.RECV, "c": Direction.CLOSE}


class MessageRouter:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        pending_store.set_event_loop(loop)

    def on_message(
        self,
        session_id: str,
        pid: int,
        script: Any,
        message: dict,
        data: Optional[bytes],
    ) -> None:
        """
        Called on the **Frida thread**.  Must not call asyncio directly.
        For data messages: blocks until UI resolves, then posts response.
        """
        msg_type = message.get("type")
        if msg_type != "send":
            if msg_type == "error":
                desc = message.get("description", "Unknown error")
                stack = message.get("stack", "")
                fname = message.get("fileName", "")
                line = message.get("lineNumber", "")
                col = message.get("columnNumber", "")
                location = f" [{fname}:{line}:{col}]" if fname else ""
                log.error(
                    "Frida script error [pid=%d]%s: %s\n%s",
                    pid, location, desc, stack,
                )
                self._broadcast_event({
                    "type": "error",
                    "session_id": session_id,
                    "pid": pid,
                    "error": desc,
                    "location": location.strip(" []"),
                    "stack": stack,
                })
            elif msg_type == "log":
                _log_frida_console(pid, message.get("payload", ""))
            else:
                log.debug("Non-send message from pid=%d: %s", pid, message)
            return

        payload = message.get("payload", {})
        msg_id = payload.get("id", InterceptedMessage.new_id())
        msg_type_code = payload.get("type")
        direction = _MSG_TYPE_MAP.get(msg_type_code)

        if direction is None:
            log.warning("Unknown message type code %r from pid=%d", msg_type_code, pid)
            return

        metadata = {k: v for k, v in payload.items() if k not in ("id", "type")}

        if direction == Direction.CLOSE:
            self._broadcast_event({
                "type": "close",
                "session_id": session_id,
                "pid": pid,
                "metadata": metadata,
            })
            return

        intercepted = InterceptedMessage(
            id=msg_id,
            session_id=session_id,
            pid=pid,
            direction=direction,
            data=data or b"",
            metadata=metadata,
        )

        msg_dict = {
            "id": intercepted.id,
            "session_id": session_id,
            "pid": pid,
            "direction": direction.value,
            "data_b64": base64.b64encode(intercepted.data).decode(),
            "data_len": len(intercepted.data),
            "metadata": metadata,
            "created_at": intercepted.created_at,
        }

        if not self._should_intercept(intercepted):
            self._broadcast_event({"type": "auto_forwarded", "message": msg_dict})
            try:
                script.post({
                    "type": msg_id,
                    "id": msg_id,
                    "data": list(intercepted.data),
                    "metadata": metadata,
                })
            except Exception:
                log.exception("Failed to post auto-forward response for %s", msg_id)
            return

        self._broadcast_event({"type": "pending", "message": msg_dict})

        action, replacement = pending_store.enqueue(intercepted)

        resolved_data = intercepted.data
        if action == ResolveAction.REPLACE and replacement is not None:
            resolved_data = replacement
        elif action == ResolveAction.DROP:
            resolved_data = b""

        self._broadcast_event({
            "type": "resolved",
            "id": intercepted.id,
            "action": action.value,
            "data_len": len(resolved_data),
        })

        try:
            script.post({
                "type": msg_id,
                "id": msg_id,
                "data": list(resolved_data),
                "metadata": metadata,
            })
        except Exception:
            log.exception("Failed to post response for %s back to Frida script", msg_id)

    def _should_intercept(self, msg: InterceptedMessage) -> bool:
        """Returns True if this message should be held for manual review.

        This is the single extension point for future filter logic:
        add per-message filter checks here without changing any other code.
        """
        if not intercept_state.enabled:
            return False
        # Future: check message filters here
        return True

    def _broadcast_event(self, event: dict) -> None:
        if self._loop is not None:
            hub.broadcast_sync(self._loop, event)


router = MessageRouter()
