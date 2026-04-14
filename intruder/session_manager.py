"""
SessionManager — manages Frida sessions (spawn / attach / detach).
Each session can hook one or more processes (child gating) with the
selected set of JS scripts.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from threading import Lock
from typing import Any

import frida
import psutil

from intruder.config import settings
from intruder.models import HookedProcess, SessionInfo
from intruder.router import router
from intruder.script_loader import AVAILABLE_SCRIPTS, build_agent

log = logging.getLogger("intruder.session")


class _Session:
    def __init__(
        self,
        id: str,
        target: str,
        device: frida.core.Device,
        scripts: list[str],
        managed: bool,
    ) -> None:
        self.id = id
        self.target = target
        self.device = device
        self.scripts = scripts
        self.managed = managed
        self.processes: dict[int, HookedProcess] = {}
        self.agent_source = build_agent(scripts, debug=settings.debug)
        self.created_at = time.time()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"session-{id[:8]}")

    def info(self) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            target=self.target,
            pids=list(self.processes.keys()),
            scripts=self.scripts,
            created_at=self.created_at,
        )


class SessionManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, _Session] = {}

    def spawn(
        self,
        path: str | list[str],
        scripts: list[str] | None = None,
        ignore_children: bool = False,
    ) -> SessionInfo:
        scripts = self._resolve_scripts(scripts)
        sid = uuid.uuid4().hex[:12]
        device = frida.get_local_device()

        argv = path if isinstance(path, list) else [path]
        pid = device.spawn(argv)
        log.info("Spawned %s → pid %d (session %s)", path, pid, sid)

        sess = _Session(id=sid, target=str(path), device=device, scripts=scripts, managed=True)
        proc = HookedProcess(pid=pid, session_id=sid)
        sess.processes[pid] = proc

        if not ignore_children:
            self._enable_child_gating(sess)

        self._attach_and_load(sess, proc)
        device.resume(pid)

        with self._lock:
            self._sessions[sid] = sess
        return sess.info()

    def attach(
        self,
        target: str | int,
        scripts: list[str] | None = None,
        ignore_children: bool = False,
    ) -> SessionInfo:
        scripts = self._resolve_scripts(scripts)
        sid = uuid.uuid4().hex[:12]
        device = frida.get_local_device()

        if isinstance(target, str) and target.isdigit():
            target = int(target)

        if isinstance(target, int):
            pid = target
        else:
            pid = device.get_process(target).pid

        log.info("Attaching to pid %d (session %s)", pid, sid)

        sess = _Session(id=sid, target=str(target), device=device, scripts=scripts, managed=False)
        proc = HookedProcess(pid=pid, session_id=sid)
        sess.processes[pid] = proc

        if not ignore_children:
            self._enable_child_gating(sess)

        self._attach_and_load(sess, proc)

        with self._lock:
            self._sessions[sid] = sess
        return sess.info()

    def detach(self, session_id: str) -> bool:
        with self._lock:
            sess = self._sessions.pop(session_id, None)
        if sess is None:
            return False
        self._teardown(sess)
        return True

    def list_sessions(self) -> list[SessionInfo]:
        with self._lock:
            return [s.info() for s in self._sessions.values()]

    def detach_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for sess in sessions:
            self._teardown(sess)

    # -- internal --------------------------------------------------------------

    def _resolve_scripts(self, scripts: list[str] | None) -> list[str]:
        if scripts is None:
            return sorted(AVAILABLE_SCRIPTS)
        for s in scripts:
            if s not in AVAILABLE_SCRIPTS:
                raise ValueError(f"Unknown script {s!r}. Available: {sorted(AVAILABLE_SCRIPTS)}")
        return scripts

    def _attach_and_load(self, sess: _Session, proc: HookedProcess) -> None:
        try:
            frida_session = sess.device.attach(proc.pid)
            proc.frida_session = frida_session

            frida_session.on(
                "detached",
                lambda reason, **kw: sess._executor.submit(self._on_detached, sess, proc, reason),
            )

            script = frida_session.create_script(sess.agent_source)
            proc.frida_script = script

            script.on(
                "message",
                lambda msg, data: router.on_message(
                    session_id=sess.id,
                    pid=proc.pid,
                    script=script,
                    message=msg,
                    data=data,
                ),
            )
            script.load()
            log.info("Script loaded for pid %d (session %s)", proc.pid, sess.id)
        except Exception:
            log.exception("Failed to attach/load script for pid %d", proc.pid)

    def _enable_child_gating(self, sess: _Session) -> None:
        try:
            sess.device.on("child-added", lambda child: sess._executor.submit(self._on_child_added, sess, child))
            sess.device.on("child-removed", lambda child: log.debug("Child removed: %s", child))
        except Exception:
            log.debug("Child gating not supported on this device/platform")

    def _on_child_added(self, sess: _Session, child: Any) -> None:
        log.info("Child process %d detected in session %s", child.pid, sess.id)
        proc = HookedProcess(pid=child.pid, session_id=sess.id)
        sess.processes[child.pid] = proc
        self._attach_and_load(sess, proc)
        try:
            sess.device.resume(child.pid)
        except Exception:
            log.debug("Could not resume child pid %d", child.pid)

    def _on_detached(self, sess: _Session, proc: HookedProcess, reason: str) -> None:
        log.info("Detached from pid %d: %s", proc.pid, reason)
        sess.processes.pop(proc.pid, None)

    def _teardown(self, sess: _Session) -> None:
        for proc in list(sess.processes.values()):
            try:
                if proc.frida_script:
                    proc.frida_script.unload()
            except Exception:
                pass
            try:
                if proc.frida_session:
                    proc.frida_session.detach()
            except Exception:
                pass
            if sess.managed and psutil.pid_exists(proc.pid):
                try:
                    psutil.Process(proc.pid).kill()
                    log.info("Killed managed process %d", proc.pid)
                except Exception:
                    pass
        sess.processes.clear()
        sess._executor.shutdown(wait=False)
        log.info("Session %s torn down", sess.id)


session_manager = SessionManager()
