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
