"""CLI-level tests using Typer's CliRunner (in-process, no subprocess spawn
needed) against a real running agent (conftest.agent_server)."""

import re
import sys

import yaml
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


def test_deploy_uses_existing_config_without_overwriting_it(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "configured_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text("print('from config')\n")
    config_path = project_dir / "foxygpu.yaml"
    # Use yaml.safe_dump rather than a hand-written f-string: sys.executable
    # can contain backslashes (Windows paths), which a raw double-quoted YAML
    # scalar would try to interpret as escape sequences.
    config_path.write_text(
        yaml.safe_dump({"runtime": "colab", "gpu": True, "command": f'"{sys.executable}" app.py'})
    )
    original_config_text = config_path.read_text()

    result = runner.invoke(cli_app, ["deploy", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "Detected a project" not in result.output
    assert "from config" in result.output
    assert config_path.read_text() == original_config_text  # untouched


def test_deploy_auto_detects_and_writes_config_when_missing(agent_server, tmp_path, monkeypatch):
    import foxygpu.main as main_module

    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "fastapi_app"
    project_dir.mkdir()
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n")
    (project_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\nprint('detected app ran')\n"
    )

    # detect_command's actual heuristics are unit-tested in test_detect.py.
    # Here we only need to verify `deploy` uses whatever it returns and
    # writes it to disk — stub a short-lived command instead of a real
    # (forever-running) uvicorn server, which would hang this test waiting
    # on a log stream that never ends.
    monkeypatch.setattr(main_module, "detect_command", lambda root: f'"{sys.executable}" main.py')

    result = runner.invoke(cli_app, ["deploy", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "Detected a project" in result.output
    assert "detected app ran" in result.output

    config_path = project_dir / "foxygpu.yaml"
    assert config_path.exists()
    assert sys.executable in config_path.read_text()


def test_deploy_with_no_config_and_nothing_detectable_fails_clearly(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "mystery_project"
    project_dir.mkdir()
    (project_dir / "readme.txt").write_text("no recognizable framework here\n")

    result = runner.invoke(cli_app, ["deploy", str(project_dir)])
    assert result.exit_code != 0
    assert "couldn't auto-detect" in result.output
    assert not (project_dir / "foxygpu.yaml").exists()


def test_deploy_invalid_config_fails_clearly(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "bad_config_app"
    project_dir.mkdir()
    (project_dir / "foxygpu.yaml").write_text("runtime: kaggle\ncommand: echo hi\n")

    result = runner.invoke(cli_app, ["deploy", str(project_dir)])
    assert result.exit_code != 0
    assert "kaggle" in result.output


def test_deploy_stops_previous_deployment_like_redeploy(agent_server, tmp_path):
    import io
    import zipfile

    from foxygpu.client import AgentClient

    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    client = AgentClient(base_url, token)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app.py", "import time\ntime.sleep(30)\n")
    zip_path = tmp_path / "prev.zip"
    zip_path.write_bytes(buf.getvalue())
    old_project_id = client.upload_project(str(zip_path), "deploy_app")
    old_process_id, _ = client.start_process(old_project_id, f'"{sys.executable}" app.py')

    project_dir = tmp_path / "deploy_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text("print('redeployed via deploy')\n")
    (project_dir / "foxygpu.yaml").write_text(
        yaml.safe_dump({"command": f'"{sys.executable}" app.py'})
    )

    result = runner.invoke(cli_app, ["deploy", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "Stopping previous deployment" in result.output
    assert "redeployed via deploy" in result.output

    old_entry = next(p for p in client.list_processes() if p["id"] == old_process_id)
    assert old_entry["status"] == "stopped"


def test_run_with_env_flag_injects_value_without_leaking_it_into_status(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "secret_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text(
        "import os\nprint('GOT_SECRET=' + os.environ['MY_SECRET'])\n"
    )

    result = runner.invoke(
        cli_app,
        [
            "run",
            str(project_dir),
            "--cmd",
            f'"{sys.executable}" app.py',
            "--env",
            "MY_SECRET=super-secret-value",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "GOT_SECRET=super-secret-value" in result.output  # the app actually received it
    assert "Passing env vars: MY_SECRET" in result.output  # key name shown
    assert "super-secret-value" not in result.output.replace(
        "GOT_SECRET=super-secret-value", ""
    )  # value never printed anywhere except the app's own deliberate echo

    status_result = runner.invoke(cli_app, ["status"])
    assert "super-secret-value" not in status_result.output
    assert "MY_SECRET" in status_result.output  # key name shown in the Env vars column


def test_run_with_env_file_flag(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "envfile_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text(
        "import os\nprint('FROM_FILE=' + os.environ['FILE_SECRET'])\n"
    )
    env_file = tmp_path / "secrets.env"
    env_file.write_text("FILE_SECRET=value-from-file\n")

    result = runner.invoke(
        cli_app,
        [
            "run",
            str(project_dir),
            "--cmd",
            f'"{sys.executable}" app.py',
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "FROM_FILE=value-from-file" in result.output


def test_env_flag_overrides_env_file_on_conflict(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "override_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text("import os\nprint('VAL=' + os.environ['KEY'])\n")
    env_file = tmp_path / "secrets.env"
    env_file.write_text("KEY=from_file\n")

    result = runner.invoke(
        cli_app,
        [
            "run",
            str(project_dir),
            "--cmd",
            f'"{sys.executable}" app.py',
            "--env-file",
            str(env_file),
            "--env",
            "KEY=from_cli",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "VAL=from_cli" in result.output


def test_deploy_reads_env_from_config(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    project_dir = tmp_path / "configured_env_app"
    project_dir.mkdir()
    (project_dir / "app.py").write_text(
        "import os\nprint('CFG_SECRET=' + os.environ['CFG_SECRET'])\n"
    )
    (project_dir / "foxygpu.yaml").write_text(
        yaml.safe_dump(
            {
                "command": f'"{sys.executable}" app.py',
                "env": {"CFG_SECRET": "value-from-config"},
            }
        )
    )

    result = runner.invoke(cli_app, ["deploy", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "CFG_SECRET=value-from-config" in result.output


def test_malformed_env_flag_fails_clearly(agent_server, tmp_path):
    base_url, token = agent_server
    runner.invoke(cli_app, ["connect", base_url, "--token", token])

    result = runner.invoke(
        cli_app,
        ["run", str(tmp_path), "--cmd", "echo hi", "--env", "NOEQUALSSIGN"],
    )
    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output
