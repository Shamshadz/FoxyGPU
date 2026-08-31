"""Shared fixtures.

Two isolation guarantees every test in this suite gets automatically:
1. `~/.foxygpu/config.json` is never touched — `isolated_config` (autouse)
   redirects it to a per-test tmp_path. A version of this suite's own history
   didn't have this and clobbered a real developer's live connection; don't
   repeat that mistake.
2. Each test gets a clean agent process/project registry via `clean_agent_state`.
"""

import io
import socket
import time
import zipfile

import pytest
import requests

from foxygpu import agent_source as agent_module
from foxygpu import config


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".foxygpu")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / ".foxygpu" / "config.json")


@pytest.fixture(autouse=True)
def clean_agent_state(tmp_path, monkeypatch):
    agent_module.PROJECTS.clear()
    agent_module.PROCESSES.clear()
    agent_module.TUNNELS.clear()
    workspace = tmp_path / "agent_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(agent_module, "WORKSPACE", workspace)


@pytest.fixture(scope="session")
def agent_server():
    """One real agent instance, serving for the whole test session."""
    port = _free_port()
    server, thread = agent_module.start_in_background(port=port)
    time.sleep(1.0)
    base_url = f"http://127.0.0.1:{port}"
    yield base_url, agent_module.TOKEN
    server.should_exit = True


@pytest.fixture
def auth_headers(agent_server):
    _, token = agent_server
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def upload_project(agent_server, auth_headers):
    """Callable: upload_project(files={...}, name="proj") -> requests.Response"""
    base_url, _ = agent_server

    def _do(files=None, name="proj"):
        if files is None:
            files = {"hello.txt": "hi"}
        return requests.post(
            f"{base_url}/projects",
            headers=auth_headers,
            files={"file": ("p.zip", _make_zip(files), "application/zip")},
            data={"name": name},
        )

    return _do
