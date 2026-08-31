"""Best-effort framework detection for `foxygpu deploy`.

Deliberately limited to a handful of common, unambiguous cases. When nothing
is recognized, callers should ask the user to write a foxygpu.yaml (or pass
--cmd explicitly to `run`/`redeploy`) rather than guessing wrong — a
confidently incorrect guess is worse than admitting we don't know.
"""

import json
import re
from pathlib import Path
from typing import Optional

_FASTAPI_APP = re.compile(r"^(\w+)\s*=\s*FastAPI\(", re.MULTILINE)
_FLASK_APP = re.compile(r"^(\w+)\s*=\s*Flask\(", re.MULTILINE)
_ENTRYPOINT_CANDIDATES = ("main.py", "app.py")


def _detect_python(root: Path) -> Optional[str]:
    if not (root / "requirements.txt").exists():
        return None

    for filename in _ENTRYPOINT_CANDIDATES:
        entry = root / filename
        if not entry.exists():
            continue
        text = entry.read_text(errors="ignore")
        module = filename[:-3]

        match = _FASTAPI_APP.search(text)
        if match:
            return (
                "pip install -r requirements.txt && "
                f"uvicorn {module}:{match.group(1)} --host 0.0.0.0 --port $PORT"
            )

        match = _FLASK_APP.search(text)
        if match:
            return (
                "pip install -r requirements.txt && "
                f"FLASK_APP={module}:{match.group(1)} flask run --host 0.0.0.0 --port $PORT"
            )

    return None


def _detect_node(root: Path) -> Optional[str]:
    package_json = root / "package.json"
    if not package_json.exists():
        return None

    try:
        pkg = json.loads(package_json.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    scripts = pkg.get("scripts", {}) or {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}

    if "vite" in deps and "dev" in scripts:
        return "npm install && npm run dev -- --host 0.0.0.0 --port $PORT"

    if "next" in deps:
        script_name = "dev" if "dev" in scripts else "start" if "start" in scripts else None
        if script_name:
            return f"npm install && npm run {script_name} -- -p $PORT -H 0.0.0.0"

    if "start" in scripts:
        return "npm install && PORT=$PORT npm start"

    if "dev" in scripts:
        # No standard $PORT convention for an arbitrary "dev" script — best
        # effort, may need editing in the generated foxygpu.yaml.
        return "npm install && npm run dev"

    return None


def detect_command(root: Path) -> Optional[str]:
    """Returns a shell command guess for the project at `root`, or None if
    nothing recognized. Checked in order; the first match wins."""
    for detector in (_detect_python, _detect_node):
        result = detector(root)
        if result:
            return result
    return None
