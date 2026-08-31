"""Exercises the FoxyGPU control-plane agent directly over HTTP/WebSocket
against a real running instance (see conftest.agent_server)."""

import asyncio
import json
import socket
import sys
import time

import pytest
import requests
import websockets

from foxygpu import agent_source as agent_module


def test_unauthenticated_request_is_rejected(agent_server):
    base_url, _ = agent_server
    resp = requests.get(f"{base_url}/processes")
    assert resp.status_code == 401


def test_root_health_check_needs_no_auth(agent_server):
    base_url, _ = agent_server
    resp = requests.get(f"{base_url}/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_run_and_port_injection(agent_server, auth_headers, upload_project):
    base_url, _ = agent_server
    resp = upload_project()
    assert resp.status_code == 200
    project_id = resp.json()["project_id"]

    cmd = (
        f'{sys.executable} -c "import os,time; '
        "print('PORT_ENV=' + os.environ['PORT'], flush=True); "
        "[print(i, flush=True) or time.sleep(0.1) for i in range(3)]\""
    )
    resp = requests.post(
        f"{base_url}/projects/{project_id}/start", headers=auth_headers, data={"cmd": cmd}
    )
    assert resp.status_code == 200
    data = resp.json()
    process_id, port = data["process_id"], data["port"]
    assert port == agent_module.PREFERRED_APP_PORT

    time.sleep(1.5)
    resp = requests.get(f"{base_url}/processes/{process_id}", headers=auth_headers)
    info = resp.json()
    assert info["status"] == "exited(0)"
    assert info["port"] == port

    log_lines = list(agent_module.PROCESSES[process_id].log_buffer)
    assert f"PORT_ENV={port}" in log_lines


def test_env_vars_are_injected_and_never_logged(agent_server, auth_headers, upload_project):
    base_url, _ = agent_server
    project_id = upload_project().json()["project_id"]

    cmd = f'{sys.executable} -c "import os; print(\'SECRET_VALUE=\' + os.environ[\'MY_SECRET\'])"'
    resp = requests.post(
        f"{base_url}/projects/{project_id}/start",
        headers=auth_headers,
        data={"cmd": cmd, "env": json.dumps({"MY_SECRET": "sk-super-secret-value"})},
    )
    assert resp.status_code == 200
    process_id = resp.json()["process_id"]
    time.sleep(1.0)

    resp = requests.get(f"{base_url}/processes/{process_id}", headers=auth_headers)
    info = resp.json()
    assert info["env_keys"] == ["MY_SECRET"]  # key name shown

    log_lines = list(agent_module.PROCESSES[process_id].log_buffer)
    full_log = "\n".join(log_lines)
    # The child process itself received the real value (proves injection worked)...
    assert "SECRET_VALUE=sk-super-secret-value" in full_log
    # ...but the agent's own bookkeeping/echo of the command never repeats the
    # secret value anywhere else in the log stream.
    secret_mentions = full_log.count("sk-super-secret-value")
    assert secret_mentions == 1  # only the child process's own deliberate print


def test_invalid_env_json_rejected(agent_server, auth_headers, upload_project):
    base_url, _ = agent_server
    project_id = upload_project().json()["project_id"]
    resp = requests.post(
        f"{base_url}/projects/{project_id}/start",
        headers=auth_headers,
        data={"cmd": "echo hi", "env": "not valid json"},
    )
    assert resp.status_code == 400


def test_non_string_env_values_rejected(agent_server, auth_headers, upload_project):
    base_url, _ = agent_server
    project_id = upload_project().json()["project_id"]
    resp = requests.post(
        f"{base_url}/projects/{project_id}/start",
        headers=auth_headers,
        data={"cmd": "echo hi", "env": json.dumps({"PORT_OVERRIDE": 1234})},
    )
    assert resp.status_code == 400


def test_no_env_defaults_to_empty(agent_server, auth_headers, upload_project):
    base_url, _ = agent_server
    project_id = upload_project().json()["project_id"]
    resp = requests.post(
        f"{base_url}/projects/{project_id}/start", headers=auth_headers, data={"cmd": "echo hi"}
    )
    assert resp.status_code == 200
    process_id = resp.json()["process_id"]
    time.sleep(0.5)
    info = requests.get(f"{base_url}/processes/{process_id}", headers=auth_headers).json()
    assert info["env_keys"] == []


def test_port_falls_back_when_preferred_port_is_occupied(agent_server, auth_headers, upload_project):
    base_url, _ = agent_server
    project_id = upload_project().json()["project_id"]

    occupier = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupier.bind(("", agent_module.PREFERRED_APP_PORT))
    occupier.listen(1)
    try:
        resp = requests.post(
            f"{base_url}/projects/{project_id}/start",
            headers=auth_headers,
            data={"cmd": f'{sys.executable} -c "import time; time.sleep(0.5)"'},
        )
        assert resp.json()["port"] != agent_module.PREFERRED_APP_PORT
    finally:
        occupier.close()


def test_stop_running_process(agent_server, auth_headers, upload_project):
    base_url, _ = agent_server
    project_id = upload_project().json()["project_id"]
    resp = requests.post(
        f"{base_url}/projects/{project_id}/start",
        headers=auth_headers,
        data={"cmd": f'{sys.executable} -c "import time; time.sleep(30)"'},
    )
    process_id = resp.json()["process_id"]
    time.sleep(0.5)

    resp = requests.post(f"{base_url}/processes/{process_id}/stop", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_stop_on_process_already_dead_at_os_level_does_not_500(agent_server):
    """Regression test: the agent's bookkeeping can say "running" for a
    process whose OS-level process already exited. stop() must handle
    ProcessLookupError gracefully instead of raising a raw 500."""

    async def run():
        handle = agent_module.ProcessHandle("regress-test", "proj", "true", 9999, [])
        proc = await asyncio.create_subprocess_shell(f'{sys.executable} -c "pass"')
        await proc.wait()  # genuinely dead at the OS level now
        handle.proc = proc
        handle.status = "running"  # but bookkeeping still says running
        agent_module.PROCESSES["regress-test"] = handle
        return await agent_module.stop_process("regress-test")

    result = asyncio.run(run())
    assert result["status"] == "stopped"


def test_gpu_status_does_not_crash_without_nvidia_smi(agent_server, auth_headers):
    base_url, _ = agent_server
    resp = requests.get(f"{base_url}/gpu", headers=auth_headers)
    assert resp.status_code == 200
    assert "available" in resp.json()


def test_websocket_log_replay_and_live_streaming(agent_server, auth_headers, upload_project):
    base_url, token = agent_server
    project_id = upload_project().json()["project_id"]
    cmd = f'{sys.executable} -c "import time; [print(i, flush=True) or time.sleep(0.3) for i in range(4)]"'
    resp = requests.post(
        f"{base_url}/projects/{project_id}/start", headers=auth_headers, data={"cmd": cmd}
    )
    process_id = resp.json()["process_id"]
    time.sleep(0.15)  # connect while it's still emitting, to exercise live streaming too

    async def collect():
        ws_url = base_url.replace("http://", "ws://") + f"/ws/logs/{process_id}?token={token}"
        lines = []
        async with websockets.connect(ws_url) as ws:
            try:
                while True:
                    lines.append(await asyncio.wait_for(ws.recv(), timeout=3))
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                pass
        return lines

    lines = asyncio.run(collect())
    assert any("0" in l for l in lines)
    assert any("exited" in l for l in lines)


@pytest.mark.parametrize(
    "malicious_name",
    [
        "../evil.txt",
        "../../evil.txt",
        "subdir/../../evil.txt",
    ],
)
def test_zip_slip_relative_traversal_is_rejected(upload_project, malicious_name):
    resp = upload_project(files={malicious_name: "pwned"})
    assert resp.status_code == 400


def test_zip_slip_absolute_path_is_rejected(upload_project, tmp_path):
    # zipfile stores this as-is; an absolute member path must also be rejected
    absolute_target = str(tmp_path / "evil.txt")
    resp = upload_project(files={absolute_target: "pwned"})
    assert resp.status_code == 400
    assert not (tmp_path / "evil.txt").exists()


def test_legitimate_nested_paths_still_extract_fine(upload_project):
    resp = upload_project(files={"main.py": "print(1)", "static/index.html": "<html></html>"})
    assert resp.status_code == 200
    project_id = resp.json()["project_id"]
    project_path = agent_module.PROJECTS[project_id].path
    assert (project_path / "main.py").exists()
    assert (project_path / "static" / "index.html").exists()
