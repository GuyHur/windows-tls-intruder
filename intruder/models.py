from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class Direction(str, enum.Enum):
    SEND = "send"
    RECV = "recv"
    CLOSE = "close"


class ResolveAction(str, enum.Enum):
    FORWARD = "forward"
    REPLACE = "replace"
    DROP = "drop"


@dataclass
class HookedProcess:
    pid: int
    session_id: str
    frida_session: Any = None
    frida_script: Any = None

    def __hash__(self) -> int:
        return hash(self.pid)


@dataclass
class InterceptedMessage:
    id: str
    session_id: str
    pid: int
    direction: Direction
    data: bytes
    metadata: dict[str, Any]
    created_at: float = field(default_factory=time.time)

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:16]


@dataclass
class SessionInfo:
    id: str
    target: str
    pids: list[int]
    scripts: list[str]
    created_at: float
