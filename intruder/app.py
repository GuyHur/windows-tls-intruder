"""
FastAPI application — REST for session control, WebSocket for live traffic,
static files for the React UI.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from intruder.config import settings
from intruder.intercept_state import intercept_state
from intruder.models import ResolveAction
from intruder.pending import pending_store
from intruder.processes import get_icon_png, list_processes
from intruder.router import router
from intruder.script_loader import AVAILABLE_SCRIPTS
from intruder.session_manager import session_manager
from intruder.ws_hub import hub

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_LOG_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_LEVEL = logging.DEBUG if settings.debug else logging.INFO

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(_LOG_FMT))

_file_handler = logging.handlers.RotatingFileHandler(
    _LOG_DIR / "tls-intruder.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FMT))

logging.root.setLevel(_LOG_LEVEL)
logging.root.addHandler(_console_handler)
logging.root.addHandler(_file_handler)

log = logging.getLogger("intruder.app")

DIST_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    router.set_event_loop(loop)
    log.info("TLS Intruder started on http://%s:%d", settings.host, settings.port)
    yield
    log.info("Shutting down — detaching all sessions")
    session_manager.detach_all()


app = FastAPI(title="Windows TLS Intruder", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class SpawnRequest(BaseModel):
    path: str | list[str]
    scripts: list[str] | None = None
    ignore_children: bool = False


class AttachRequest(BaseModel):
    target: str | int
    scripts: list[str] | None = None
    ignore_children: bool = False


class ResolveRequest(BaseModel):
    action: ResolveAction
    data_b64: str | None = None


class InterceptRequest(BaseModel):
    enabled: bool


# ---------------------------------------------------------------------------
# REST — session management
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/scripts")
async def list_scripts():
    return {"scripts": sorted(AVAILABLE_SCRIPTS)}


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": [_session_dict(s) for s in session_manager.list_sessions()]}


@app.post("/api/sessions/spawn", status_code=201)
async def spawn_session(req: SpawnRequest):
    try:
        info = await asyncio.get_running_loop().run_in_executor(
            None, lambda: session_manager.spawn(req.path, req.scripts, req.ignore_children)
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await hub.broadcast({"type": "session_created", "session": _session_dict(info)})
    return _session_dict(info)


@app.post("/api/sessions/attach", status_code=201)
async def attach_session(req: AttachRequest):
    try:
        info = await asyncio.get_running_loop().run_in_executor(
            None, lambda: session_manager.attach(req.target, req.scripts, req.ignore_children)
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await hub.broadcast({"type": "session_created", "session": _session_dict(info)})
    return _session_dict(info)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = session_manager.detach(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    await hub.broadcast({"type": "session_destroyed", "session_id": session_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# REST — process list
# ---------------------------------------------------------------------------

@app.get("/api/processes")
async def get_processes():
    procs = await asyncio.get_running_loop().run_in_executor(None, list_processes)
    return {"processes": procs}


@app.get("/api/processes/{pid}/icon")
async def get_process_icon(pid: int):
    import psutil as _psutil
    try:
        exe = _psutil.Process(pid).exe()
    except (_psutil.NoSuchProcess, _psutil.AccessDenied):
        raise HTTPException(status_code=404, detail="Process not found")
    png = await asyncio.get_running_loop().run_in_executor(None, get_icon_png, exe)
    if png is None:
        raise HTTPException(status_code=404, detail="No icon available")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# REST — intercept toggle
# ---------------------------------------------------------------------------

@app.get("/api/intercept")
async def get_intercept():
    return {"enabled": intercept_state.enabled}


@app.post("/api/intercept")
async def set_intercept(req: InterceptRequest):
    intercept_state.enabled = req.enabled
    await hub.broadcast({"type": "intercept_changed", "enabled": req.enabled})
    return {"enabled": intercept_state.enabled}


# ---------------------------------------------------------------------------
# REST — pending messages
# ---------------------------------------------------------------------------

@app.get("/api/pending")
async def list_pending():
    return {"pending": pending_store.list_pending()}


@app.post("/api/pending/{message_id}/resolve")
async def resolve_pending(message_id: str, req: ResolveRequest):
    ok = pending_store.resolve(message_id, req.action, req.data_b64)
    if not ok:
        raise HTTPException(status_code=404, detail="Pending message not found or already resolved")
    return {"ok": True}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)


# ---------------------------------------------------------------------------
# Static files (React build)
# ---------------------------------------------------------------------------

if DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file = DIST_DIR / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(DIST_DIR / "index.html")


def _session_dict(s: Any) -> dict:
    return {
        "id": s.id,
        "target": s.target,
        "pids": s.pids,
        "scripts": s.scripts,
        "created_at": s.created_at,
    }


def main():
    uvicorn.run(
        "intruder.app:app",
        host=settings.host,
        port=settings.port,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
