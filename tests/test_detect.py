import json

from foxygpu.detect import detect_command


def test_empty_directory_detects_nothing(tmp_path):
    assert detect_command(tmp_path) is None


def test_detects_fastapi(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    cmd = detect_command(tmp_path)
    assert cmd is not None
    assert "uvicorn main:app" in cmd
    assert "--port $PORT" in cmd
    assert "pip install -r requirements.txt" in cmd


def test_detects_fastapi_with_custom_variable_name(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napi = FastAPI()\n")
    cmd = detect_command(tmp_path)
    assert "uvicorn app:api" in cmd


def test_detects_flask(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "main.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
    cmd = detect_command(tmp_path)
    assert "FLASK_APP=main:app" in cmd
    assert "flask run" in cmd


def test_requirements_without_recognizable_entrypoint_detects_nothing(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy\n")
    (tmp_path / "main.py").write_text("print('just a script')\n")
    assert detect_command(tmp_path) is None


def test_detects_vite(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5.0.0"}})
    )
    cmd = detect_command(tmp_path)
    assert "npm run dev -- --host 0.0.0.0 --port $PORT" in cmd


def test_detects_nextjs(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"dev": "next dev"}, "dependencies": {"next": "^14.0.0"}})
    )
    cmd = detect_command(tmp_path)
    assert "npm run dev -- -p $PORT -H 0.0.0.0" in cmd


def test_generic_npm_start_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
    cmd = detect_command(tmp_path)
    assert "PORT=$PORT npm start" in cmd


def test_malformed_package_json_detects_nothing_not_crashes(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json")
    assert detect_command(tmp_path) is None


def test_python_detection_takes_priority_over_node(tmp_path):
    # A project with both a requirements.txt+FastAPI app AND a package.json
    # (e.g. a FastAPI backend with a bundled frontend build step) should
    # detect the backend, since that's what --cmd would actually need to run.
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    cmd = detect_command(tmp_path)
    assert "uvicorn" in cmd
