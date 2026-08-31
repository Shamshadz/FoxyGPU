# Contributing to FoxyGPU

Thanks for taking a look. This is a small project, so the process is
lightweight — no CLA, no formal RFC process, just working code and a clear PR.

## Setup

```bash
git clone https://github.com/Shamshadz/FoxyGPU.git
cd FoxyGPU
pip install -e ".[dev]"
pytest
```

The test suite runs a real instance of the agent locally (no Colab account or
GPU needed) and drives it over HTTP/WebSocket, plus in-process CLI tests via
Typer's test runner. It's isolated from your real `~/.foxygpu/config.json` —
every test gets a throwaway one automatically (see `tests/conftest.py`). If
you're adding a test that touches config, gist state, or the agent's global
process/project registries, use the existing `isolated_config` /
`clean_agent_state` autouse fixtures rather than writing to real state
directly — a version of this project's own history got that wrong once and
overwrote a real developer's live connection.

## Project layout

- `foxygpu/main.py` — the CLI (Typer commands)
- `foxygpu/client.py` — HTTP/WebSocket client for talking to the agent
- `foxygpu/agent_source.py` — the control-plane agent that actually runs
  *inside Colab*. This file is never imported by the CLI in normal use — it's
  read as text (`notebook_builder.py`) and embedded into the generated
  notebook. The test suite does import and run it directly, which is why
  `fastapi`/`uvicorn`/`python-multipart` are dev-only dependencies, not core
  ones.
- `foxygpu/github.py` — Gist publishing for the `--gist` launch path
- `foxygpu/notebook_builder.py` — builds the runner notebook from
  `agent_source.py`
- `notebook/FoxyGPU_Runner.ipynb` — the **committed, static** copy of that
  notebook that `foxygpu launch`'s default (no-token) path opens directly from
  this repo on GitHub. If you change `agent_source.py`, regenerate it:
  ```bash
  foxygpu notebook notebook/FoxyGPU_Runner.ipynb
  ```
  and commit the result — otherwise `launch`'s default path keeps serving the
  old agent code.
- `examples/ollama-chat/` — a full working example (FastAPI + Ollama chat app)
- `tests/` — the pytest suite

## Testing a change to the agent itself

Since `agent_source.py` only really "runs" inside Colab, there are two ways to
verify a change beyond the unit tests:
1. `foxygpu launch --gist` with your own GitHub token publishes *your* current
   `agent_source.py` to a personal Gist and opens it in Colab — no need to
   push to a fork first.
2. Or `foxygpu notebook out.ipynb` + manually upload `out.ipynb` in Colab.

## Submitting a change

1. Fork, branch, make your change.
2. Add or update tests — a PR that changes behavior without a test covering
   it will likely get asked for one.
3. `pytest` locally before opening the PR; CI runs the same suite across
   Python 3.9/3.12 on Linux, Windows, and macOS.
4. Open a PR describing what changed and why. Small, focused PRs are easier
   to review than large ones.

## Reporting bugs / requesting features

Use the issue templates — they ask for the minimum needed to act on a report
(repro steps, environment, expected vs. actual) without excessive ceremony.
