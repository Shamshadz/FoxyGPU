import sys
from typing import Optional

import requests

from .config import load_config


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

    def upload_project(self, zip_path: str, name: str) -> str:
        with open(zip_path, "rb") as f:
            resp = requests.post(
                f"{self.url}/projects",
                headers=self.headers,
                files={"file": (f"{name}.zip", f, "application/zip")},
                data={"name": name},
                timeout=120,
            )
        resp.raise_for_status()
        return resp.json()["project_id"]

    def start_process(self, project_id: str, cmd: str):
        """Returns (process_id, port) — the agent picks a free port and injects it
        into the command's environment as $PORT."""
        resp = requests.post(
            f"{self.url}/projects/{project_id}/start",
            headers=self.headers,
            data={"cmd": cmd},
            timeout=30,
        )
        resp.raise_for_status()
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
        resp = requests.get(f"{self.url}/processes", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def stop_process(self, process_id: str):
        resp = requests.post(f"{self.url}/processes/{process_id}/stop", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def gpu_status(self):
        resp = requests.get(f"{self.url}/gpu", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def create_tunnel(self, port: int):
        resp = requests.post(
            f"{self.url}/tunnels", headers=self.headers, data={"port": port}, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def ws_logs_url(self, process_id: str) -> str:
        base = self.url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/ws/logs/{process_id}?token={self.token}"
