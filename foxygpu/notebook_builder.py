"""Builds the FoxyGPU Colab runner notebook in-memory.

Used by `foxygpu launch` (publish + open in Colab) and `foxygpu notebook`
(write to a local file for manual upload). The agent source is bundled as a
package resource (`agent_source.py`) and embedded verbatim via `%%writefile`,
so there is a single source of truth for what actually runs in Colab.
"""

import json
from importlib import resources


def _agent_source() -> str:
    return resources.files("foxygpu").joinpath("agent_source.py").read_text()


def _code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def build_notebook() -> dict:
    agent_src = _agent_source()

    cells = [
        _markdown_cell(
            "# FoxyGPU Runner\n"
            "\n"
            "Run this notebook with a **GPU runtime** selected "
            "(`Runtime > Change runtime type > GPU`).\n"
            "\n"
            "It starts a small control-plane agent and a public tunnel to it. Copy the "
            "printed `foxygpu connect ...` command into your local terminal to start "
            "driving this Colab GPU from the `foxygpu` CLI.\n"
        ),
        _markdown_cell("## 1. Install dependencies and download `cloudflared`"),
        _code_cell(
            "%%bash\n"
            "pip install -q fastapi uvicorn python-multipart websockets\n"
            "if [ ! -f ./cloudflared ]; then\n"
            "  wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared\n"
            "  chmod +x cloudflared\n"
            "fi\n"
            "echo done\n"
        ),
        _markdown_cell(
            "## 2. Write the agent\n"
            "\n"
            "This cell was generated from `foxygpu/agent_source.py` in the `foxygpu` "
            "package installed on your machine — it stays in sync automatically every "
            "time you run `foxygpu launch`."
        ),
        _code_cell("%%writefile foxygpu_agent.py\n" + agent_src),
        _markdown_cell("## 3. Start the agent and the control-plane tunnel"),
        _code_cell(
            "import re\n"
            "import subprocess\n"
            "import time\n"
            "\n"
            "from foxygpu_agent import TOKEN, start_in_background\n"
            "\n"
            "server, thread = start_in_background(port=8765)\n"
            "time.sleep(2)\n"
            "\n"
            "proc = subprocess.Popen(\n"
            "    [\"./cloudflared\", \"tunnel\", \"--url\", \"http://localhost:8765\"],\n"
            "    stdout=subprocess.PIPE,\n"
            "    stderr=subprocess.STDOUT,\n"
            "    text=True,\n"
            ")\n"
            "pattern = re.compile(r\"https://[a-zA-Z0-9\\-]+\\.trycloudflare\\.com\")\n"
            "control_url = None\n"
            "deadline = time.time() + 30\n"
            "while time.time() < deadline and control_url is None:\n"
            "    line = proc.stdout.readline()\n"
            "    if not line:\n"
            "        continue\n"
            "    match = pattern.search(line)\n"
            "    if match:\n"
            "        control_url = match.group(0)\n"
            "\n"
            "if not control_url:\n"
            "    raise RuntimeError(\"Timed out waiting for the cloudflared tunnel URL\")\n"
            "\n"
            "print(\"Control URL:\", control_url)\n"
            "print(\"Token:\", TOKEN)\n"
            "print()\n"
            "print(\"On your local machine, run:\")\n"
            "print(f\"  foxygpu connect {control_url} --token {TOKEN}\")\n"
        ),
        _markdown_cell(
            "## Notes\n"
            "\n"
            "- Keep this notebook running for as long as you want the agent reachable. "
            "Colab free-tier sessions are ephemeral (idle timeout, ~12h cap) — if the "
            "session restarts, re-run these cells and `foxygpu connect` again with the "
            "new URL/token.\n"
            "- Anyone with the control URL **and** the token can execute code on this "
            "VM. Don't share them.\n"
            "- Port **8765** is used by this agent itself — don't run your own app on "
            "that port, or its server won't be able to bind it.\n"
        ),
    ]

    return {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"name": "FoxyGPU_Runner.ipynb", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def build_notebook_json() -> str:
    return json.dumps(build_notebook(), indent=1)
