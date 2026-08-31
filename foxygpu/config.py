import json
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".foxygpu"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _read() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def _write(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def save_config(url: str, token: str) -> None:
    data = _read()
    data["url"] = url.rstrip("/")
    data["token"] = token
    _write(data)


def load_config() -> Optional[dict]:
    data = _read()
    if "url" not in data or "token" not in data:
        return None
    return data


def get_github_token() -> Optional[str]:
    return _read().get("github_token")


def save_github_token(token: str) -> None:
    data = _read()
    data["github_token"] = token
    _write(data)


def get_gist_id() -> Optional[str]:
    return _read().get("gist_id")


def save_gist_id(gist_id: str) -> None:
    data = _read()
    data["gist_id"] = gist_id
    _write(data)
