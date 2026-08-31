"""FoxyGPU control-plane agent.

This module is never imported by the `foxygpu` CLI itself — `foxygpu.notebook_builder`
reads its *source text* and embeds it into a generated Colab notebook via `%%writefile`.
It runs standalone inside the Colab VM once that notebook cell executes.

Exposes a small HTTP/WebSocket API, reached from the local `foxygpu` CLI over a
public tunnel, that can:
  - accept a zipped project and run an arbitrary shell command for it
  - stream that process's stdout/stderr back live
  - stop the process
  - open an additional tunnel to expose a port the process is listening on
  - report GPU status (nvidia-smi)

Every route (except the root health check) requires `Authorization: Bearer <TOKEN>`,
where TOKEN is generated at startup and printed once. Anyone who obtains a live
control URL without the token cannot execute anything through it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import uuid
import zipfile
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

TOKEN = secrets.token_urlsafe(32)
WORKSPACE = Path.home() / "foxygpu_workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FoxyGPU Agent")


def check_auth(authorization: Optional[str] = Header(None)) -> None:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="invalid or missing token")


class Project:
    def __init__(self, project_id: str, name: str, path: Path):
        self.id = project_id
        self.name = name
        self.path = path


# Not a registered/well-known port and not one commonly defaulted to by dev
# frameworks (unlike 3000, 5000, 8000, 8080, 8888, ...) - tried first so a run's
# port stays predictable across deploys; falls back to any free port if taken
# (e.g. a second concurrent project).
PREFERRED_APP_PORT = 9876


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("", port))
            return True
        except OSError:
            return False


def _find_free_port() -> int:
    if _is_port_free(PREFERRED_APP_PORT):
        return PREFERRED_APP_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class ProcessHandle:
    def __init__(self, process_id: str, project_id: str, cmd: str, port: int, env_keys: List[str]):
        self.id = process_id
        self.project_id = project_id
        self.cmd = cmd
        self.port = port
        self.env_keys = env_keys  # names only - values are never retained here
        self.status = "starting"
        self.pid: Optional[int] = None
        self.log_buffer: deque = deque(maxlen=2000)
        self.subscribers: List[asyncio.Queue] = []
        self.proc: Optional[asyncio.subprocess.Process] = None

    def append_log(self, line: str) -> None:
        self.log_buffer.append(line)
        for q in self.subscribers:
            q.put_nowait(line)


PROJECTS: Dict[str, Project] = {}
PROCESSES: Dict[str, ProcessHandle] = {}
TUNNELS: Dict[int, dict] = {}


@app.get("/")
def root():
    return {"service": "foxygpu-agent", "status": "ok"}


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Reject zip members that would extract outside dest (zip-slip)."""
    dest_resolved = dest.resolve()
    for member in zf.namelist():
        target = (dest_resolved / member).resolve()
        try:
            target.relative_to(dest_resolved)
        except ValueError:
            raise HTTPException(400, f"Zip contains an unsafe path: {member!r}")
    zf.extractall(dest_resolved)


@app.post("/projects", dependencies=[Depends(check_auth)])
async def create_project(file: UploadFile = File(...), name: str = Form("project")):
    project_id = uuid.uuid4().hex[:12]
    project_dir = WORKSPACE / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    zip_path = project_dir / "upload.zip"
    with open(zip_path, "wb") as f:
        f.write(await file.read())
    with zipfile.ZipFile(zip_path) as zf:
        _safe_extract(zf, project_dir)
    zip_path.unlink()
    PROJECTS[project_id] = Project(project_id, name, project_dir)
    return {"project_id": project_id, "path": str(project_dir)}


@app.post("/projects/{project_id}/start", dependencies=[Depends(check_auth)])
async def start_project(project_id: str, cmd: str = Form(...), env: str = Form("{}")):
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(404, "project not found")

    try:
        extra_env = json.loads(env)
    except json.JSONDecodeError:
        raise HTTPException(400, "env must be a JSON object")
    if not isinstance(extra_env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in extra_env.items()
    ):
        raise HTTPException(400, "env must be a JSON object of string keys to string values")

    process_id = uuid.uuid4().hex[:12]
    port = _find_free_port()
    handle = ProcessHandle(process_id, project_id, cmd, port, list(extra_env.keys()))
    PROCESSES[process_id] = handle
    asyncio.create_task(_run_process(handle, project.path, cmd, port, extra_env))
    return {"process_id": process_id, "port": port}


async def _run_process(
    handle: ProcessHandle, cwd: Path, cmd: str, port: int, extra_env: Dict[str, str]
) -> None:
    handle.append_log(f"$ {cmd}")
    handle.append_log(f"[assigned port {port} - reference $PORT in your start command]")
    if handle.env_keys:
        handle.append_log(f"[env vars set: {', '.join(handle.env_keys)} (values not logged)]")
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["FOXYGPU_PORT"] = str(port)
    env.update(extra_env)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    handle.proc = proc
    handle.pid = proc.pid
    handle.status = "running"
    assert proc.stdout is not None
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            handle.append_log(line.decode(errors="replace").rstrip())
    finally:
        returncode = await proc.wait()
        if handle.status != "stopped":
            handle.status = f"exited({returncode})"
        handle.append_log(f"[process exited with code {returncode}]")
        for q in handle.subscribers:
            q.put_nowait(None)


@app.post("/processes/{process_id}/stop", dependencies=[Depends(check_auth)])
async def stop_process(process_id: str):
    handle = PROCESSES.get(process_id)
    if not handle:
        raise HTTPException(404, "process not found")
    if handle.proc and handle.status == "running":
        handle.status = "stopped"
        try:
            handle.proc.terminate()
            await asyncio.wait_for(handle.proc.wait(), timeout=5)
        except ProcessLookupError:
            pass  # already exited on its own
        except asyncio.TimeoutError:
            try:
                handle.proc.kill()
            except ProcessLookupError:
                pass
    return {"status": handle.status}


def _project_name(project_id: str) -> Optional[str]:
    project = PROJECTS.get(project_id)
    return project.name if project else None


@app.get("/processes", dependencies=[Depends(check_auth)])
async def list_processes():
    return [
        {
            "id": h.id,
            "project_id": h.project_id,
            "project_name": _project_name(h.project_id),
            "cmd": h.cmd,
            "status": h.status,
            "pid": h.pid,
            "port": h.port,
            "env_keys": h.env_keys,
        }
        for h in PROCESSES.values()
    ]


@app.get("/processes/{process_id}", dependencies=[Depends(check_auth)])
async def get_process(process_id: str):
    handle = PROCESSES.get(process_id)
    if not handle:
        raise HTTPException(404, "process not found")
    return {
        "id": handle.id,
        "project_name": _project_name(handle.project_id),
        "status": handle.status,
        "pid": handle.pid,
        "cmd": handle.cmd,
        "port": handle.port,
        "env_keys": handle.env_keys,
    }


@app.websocket("/ws/logs/{process_id}")
async def ws_logs(websocket: WebSocket, process_id: str, token: str = ""):
    if token != TOKEN:
        await websocket.close(code=4401)
        return
    handle = PROCESSES.get(process_id)
    if not handle:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    for line in list(handle.log_buffer):
        await websocket.send_text(line)
    queue: asyncio.Queue = asyncio.Queue()
    handle.subscribers.append(queue)
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            await websocket.send_text(item)
    except WebSocketDisconnect:
        pass
    finally:
        handle.subscribers.remove(queue)


def _find_cloudflared() -> str:
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    local = Path.cwd() / "cloudflared"
    if local.exists():
        return str(local)
    raise HTTPException(500, "cloudflared binary not found on the Colab VM")


async def _wait_for_tunnel_url(proc: asyncio.subprocess.Process, timeout: float) -> Optional[str]:
    pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    deadline = time.time() + timeout
    assert proc.stdout is not None
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return None
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            return None
        if not line:
            return None
        match = pattern.search(line.decode(errors="replace"))
        if match:
            return match.group(0)


@app.post("/tunnels", dependencies=[Depends(check_auth)])
async def create_tunnel(port: int = Form(...)):
    existing = TUNNELS.get(port)
    if existing and existing.get("url"):
        return {"port": port, "url": existing["url"]}
    exe = _find_cloudflared()
    proc = await asyncio.create_subprocess_exec(
        exe,
        "tunnel",
        "--url",
        f"http://localhost:{port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    TUNNELS[port] = {"proc": proc, "url": None}
    url = await _wait_for_tunnel_url(proc, timeout=20)
    if not url:
        raise HTTPException(504, "timed out waiting for tunnel URL")
    TUNNELS[port]["url"] = url
    return {"port": port, "url": url}


@app.get("/gpu", dependencies=[Depends(check_auth)])
async def gpu_status():
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=10)
        return {"available": result.returncode == 0, "output": result.stdout or result.stderr}
    except FileNotFoundError:
        return {"available": False, "output": "nvidia-smi not found (no GPU runtime attached?)"}


def start_in_background(port: int = 8765):
    """Start the agent on a background thread so the notebook cell returns immediately."""
    import threading

    import uvicorn

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    import uvicorn

    print(f"FoxyGPU agent starting. TOKEN={TOKEN}")
    uvicorn.run(app, host="0.0.0.0", port=8765)
