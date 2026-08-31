import sys
from typing import Optional

import requests

from .config import load_config

DISCONNECTED_MESSAGE = (
    "Could not reach the Colab agent at {url}.\n"
    "The Colab runtime likely disconnected or the session expired (free-tier "
    "sessions are ephemeral). Run `foxygpu launch` again, then `foxygpu connect` "
    "with the new URL/token it prints."
)


class AgentClient:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def from_config(cls) -> "AgentClient":
        cfg = load_config()
        if not cfg:
            print("Not connected. Run `foxygpu connect <url> --token <token>` first.", file=sys.stderr)
            raise SystemExit(1)
        return cls(cfg["url"], cfg["token"])

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            resp = requests.request(method, f"{self.url}{path}", headers=self.headers, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            raise SystemExit(DISCONNECTED_MESSAGE.format(url=self.url))
        resp.raise_for_status()
        return resp

    def upload_project(self, zip_path: str, name: str) -> str:
        with open(zip_path, "rb") as f:
            resp = self._request(
                "post",
                "/projects",
                files={"file": (f"{name}.zip", f, "application/zip")},
                data={"name": name},
                timeout=120,
            )
        return resp.json()["project_id"]

    def start_process(self, project_id: str, cmd: str):
        """Returns (process_id, port) — the agent picks a free port and injects it
        into the command's environment as $PORT."""
        resp = self._request(
            "post", f"/projects/{project_id}/start", data={"cmd": cmd}, timeout=30
        )
        data = resp.json()
        return data["process_id"], data["port"]

    def latest_process_port(self) -> Optional[int]:
        """Port of the most recently started process, or None if there isn't one."""
        processes = self.list_processes()
        for p in reversed(processes):
            if p.get("port"):
                return p["port"]
        return None

    def list_processes(self):
        return self._request("get", "/processes", timeout=15).json()

    def stop_process(self, process_id: str):
        return self._request("post", f"/processes/{process_id}/stop", timeout=15).json()

    def gpu_status(self):
        return self._request("get", "/gpu", timeout=15).json()

    def create_tunnel(self, port: int):
        return self._request("post", "/tunnels", data={"port": port}, timeout=30).json()

    def ws_logs_url(self, process_id: str) -> str:
        base = self.url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/ws/logs/{process_id}?token={self.token}"
