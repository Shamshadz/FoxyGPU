"""CLI-level tests using Typer's CliRunner (in-process, no subprocess spawn
needed) against a real running agent (conftest.agent_server)."""

import re
import sys

from typer.testing import CliRunner

from foxygpu.main import app as cli_app

runner = CliRunner()


def test_connect_run_status_expose_full_flow(agent_server, tmp_path):
    base_url, token = agent_server

    result = runner.invoke(cli_app, ["connect", base_url, "--token", token])
    assert result.exit_code == 0, result.output

    project_dir = tmp_path / "sample_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text(
        "import os,time\n"
        "print('MY_PORT=' + os.environ['PORT'], flush=True)\n"
        "for i in range(2):\n"
        "    print(f'line {i}', flush=True)\n"
        "    time.sleep(0.1)\n"
    )

    result = runner.invoke(
        cli_app, ["run", str(project_dir), "--cmd", f'"{sys.executable}" app.py']
    )
    assert result.exit_code == 0, result.output
    assert "line 0" in result.output
    assert "line 1" in result.output
    port_match = re.search(r"MY_PORT=(\d+)", result.output)
    assert port_match, result.output
    assigned_port = port_match.group(1)
    assert f"assigned port {assigned_port}" in result.output

    result = runner.invoke(cli_app, ["status"])
    assert result.exit_code == 0, result.output
    assert "exited" in result.output
    assert assigned_port in result.output

    # No cloudflared binary in the test environment, so expose ultimately
    # fails — but it must fail *after* correctly inferring the port.
    result = runner.invoke(cli_app, ["expose"])
    assert f"most recently started process's port: {assigned_port}" in result.output


def test_run_without_connect_fails_clearly(tmp_path):
    result = runner.invoke(cli_app, ["run", str(tmp_path), "--cmd", "echo hi"])
    assert result.exit_code != 0
    assert "Not connected" in result.output


def test_stop_all_stops_every_running_process(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text("import time\ntime.sleep(0.05)\n")

    result = runner.invoke(
        cli_app, ["run", str(project_dir), "--cmd", f'"{sys.executable}" app.py']
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli_app, ["stop", "--all"])
    assert result.exit_code == 0, result.output
    assert "Stopped" in result.output or "No running processes" in result.output


def test_redeploy_stops_previous_deployment_of_same_project(agent_server, tmp_path):
    import io
    import zipfile

    from foxygpu.client import AgentClient

    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    # Start a long-running "previous deployment" directly via the client
    # (bypassing `run`'s blocking log stream) so it's still running when
    # `redeploy` goes looking for it under the same project name.
    client = AgentClient(base_url, token)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app.py", "import time\ntime.sleep(30)\n")
    zip_path = tmp_path / "prev.zip"
    zip_path.write_bytes(buf.getvalue())
    old_project_id = client.upload_project(str(zip_path), "myapp")
    old_process_id, _ = client.start_process(old_project_id, f'"{sys.executable}" app.py')

    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "app.py").write_text("print('redeployed')\n")

    result = runner.invoke(
        cli_app, ["redeploy", str(project_dir), "--cmd", f'"{sys.executable}" app.py']
    )
    assert result.exit_code == 0, result.output
    assert "Stopping previous deployment" in result.output
    assert old_process_id in result.output
    assert "redeployed" in result.output

    old_entry = next(p for p in client.list_processes() if p["id"] == old_process_id)
    assert old_entry["status"] == "stopped"


def test_redeploy_with_no_previous_deployment_just_deploys(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "brand_new_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text("print('first deploy')\n")

    result = runner.invoke(
        cli_app, ["redeploy", str(project_dir), "--cmd", f'"{sys.executable}" app.py']
    )
    assert result.exit_code == 0, result.output
    assert "Stopping previous deployment" not in result.output
    assert "first deploy" in result.output
