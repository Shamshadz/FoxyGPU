# FoxyGPU

Run local code — FastAPI backends, frontend dev servers, or anything else — on
Google Colab's free-tier GPU, driven entirely from your own machine.

## How it works

`foxygpu launch` opens FoxyGPU's own runner notebook directly in Colab — no
manual notebook upload, and **no GitHub account or token needed**. The notebook
is identical for every user (nothing personalized is baked in), so it's just
committed straight into this repo and Colab loads it from there; Colab can open
any public GitHub file with zero authentication. That notebook starts a
control-plane agent, reached from your machine over a [Cloudflare
Tunnel](https://github.com/cloudflare/cloudflared) quick tunnel (no account needed).
The local `foxygpu` CLI talks to that agent to upload your project, start it with a
shell command, stream its logs, and expose whatever port it's listening on with its
own public URL.

```
 local machine                              Google Colab VM (GPU runtime)
┌─────────────────┐   HTTPS/WSS via         ┌─────────────────────────────┐
│  foxygpu CLI     │◄──cloudflared tunnel──►│  foxygpu_agent (FastAPI)     │
└─────────────────┘                         │  spawns your process         │
                                              │  (uvicorn / npm / anything)  │
                                              └─────────────────────────────┘
```

Every agent endpoint requires a bearer token generated at startup — the tunnel URL
alone isn't enough to run anything on your VM.

## Install

Everything — the CLI and the Colab agent it deploys — ships as one Python package:

```bash
pip install -e .
```

## Setup

### 1. Launch the Colab runtime

```bash
foxygpu launch
```

This just opens Colab straight to FoxyGPU's own committed notebook — nothing to
sign in to, no token, no account needed.

In the browser: select a GPU runtime (`Runtime > Change runtime type > GPU`),
run all cells. The last cell prints a `foxygpu connect ...` command — copy it.

Prefer not to open a link we host at all? `foxygpu notebook ./FoxyGPU_Runner.ipynb`
writes the same notebook to a local file so you can read it yourself and upload
it to Colab manually (`File > Upload notebook`) — zero network calls to anything
but Colab itself.

If you've modified `foxygpu/agent_source.py` locally and want the one-click
experience for your own version without forking/hosting a repo, `foxygpu launch
--gist` publishes your copy to a GitHub Gist instead — that path does need a
**classic** GitHub token with the `gist` scope (fine-grained tokens don't support
the Gists API and fail with a 404); create one at https://github.com/settings/tokens
-> "Generate new token (classic)".

### 2. Connect

Paste the command Colab printed, e.g.:

```bash
foxygpu connect https://xxxx.trycloudflare.com --token <token>
```

## Usage

Run a project (any language/framework — it's just a shell command). The agent
picks a free port for you and injects it as `$PORT` — reference that instead of
a literal number so you never have to think about which ports are free or
reserved:

```bash
foxygpu run ./my-fastapi-app --cmd 'pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port $PORT' --expose
```

> **Shell note**: use **single quotes** around the `--cmd` value, exactly as
> above, in PowerShell, bash, or zsh — all three treat single quotes as a
> literal string, so `$PORT` and `&&` reach the remote command unchanged. This
> does **not** work in `cmd.exe` (no concept of single-quoted literal strings,
> and it interprets `&&` itself) — use PowerShell or a bash-like shell instead.

Logs stream live, and the CLI prints which port got assigned. `--expose`
immediately opens a public tunnel once the process starts and prints the URL.
If you skip it, expose later — with no argument it defaults to the most
recently started process's port:

```bash
foxygpu expose
```

Check GPU status and running processes (including their assigned ports):

```bash
foxygpu status
```

Stream logs for a process, reconnect after detaching, or stop it (add `--all`
to stop everything):

```bash
foxygpu logs <process-id>
foxygpu stop <process-id>
foxygpu stop --all
```

Pressing Ctrl+C while logs are streaming only detaches your terminal — the
remote process keeps running on Colab. The CLI reminds you of the `logs`/`stop`
commands above when you do this.

### More examples

Node.js app (read `process.env.PORT` in your server code):
```bash
foxygpu run ./my-node-app --cmd 'npm install && node server.js' --expose
```

Frontend dev server (Vite/React/etc.):
```bash
foxygpu run ./my-frontend --cmd 'npm install && npm run dev -- --host 0.0.0.0 --port $PORT' --expose
```

One-off script or training job (no server, so skip `--expose`):
```bash
foxygpu run ./train-job --cmd 'pip install -r requirements.txt && python train.py'
```

See `foxygpu run --help` for this same set of examples from the CLI.

## Excluding files from upload

By default `.git`, `node_modules`, `__pycache__`, `venv`/`.venv`, and a few build
directories are excluded when zipping your project. Add more patterns by copying
[.foxygpuignore.default](.foxygpuignore.default) to `.foxygpuignore` in your project
root.

## Known limitations

- FastAPI is only used to build the agent itself (the control-plane server running
  inside Colab) — it is not a requirement for what you deploy. `foxygpu run` just
  executes whatever shell command you give it via `--cmd`, so any language or
  framework the Colab VM can run works (Node, Go, Rust, Flask, Streamlit, a plain
  training script, anything), not just Python or FastAPI.
- Colab free-tier sessions are ephemeral (idle timeout, ~12h cap). If the session
  restarts, run the notebook again (re-run `foxygpu launch` if you closed the tab)
  and `foxygpu connect` again with the new URL/token.
- The control URL and token grant code execution on the VM — don't share them.
- `foxygpu launch --gist` (the opt-in path) publishes to a **public** Gist (Gist
  API has no private-but-linkable option) — it contains no secrets (the agent's
  token is generated fresh at runtime in Colab, not baked into the notebook), but
  anyone who finds the Gist URL can see and re-run it against their own Colab.
- The agent source lives at `foxygpu/agent_source.py`. The committed
  `notebook/FoxyGPU_Runner.ipynb` embeds a copy of it — regenerate that file with
  `foxygpu notebook notebook/FoxyGPU_Runner.ipynb` and commit it after changing
  the agent, since (unlike `--gist`, which always embeds the current source) the
  default `launch` opens the version already committed to this repo.
- **Port 8765 is reserved** — the agent itself listens there inside Colab. You
  shouldn't need to think about this: reference `$PORT` in your `--cmd` (see
  Usage) and the agent hands you a free port automatically, preferring `9876`
  and falling back to another free one if that's taken (e.g. a second
  concurrent project).
- **A command with an animated progress bar can hang your whole `--cmd` chain
  forever.** Some CLI tools (Ollama's `pull` is one example) never exit their
  progress renderer when run through a non-interactive pipe like the one the
  agent uses to capture output, even though the real work finishes. Since
  `foxygpu run` chains commands with `&&`, a hung one blocks everything after
  it. If a step seems stuck, check whether it actually finished (e.g. via a
  second `foxygpu run` with a quick status-checking command) before assuming
  it's slow — the fix is usually prefixing that one command with `TERM=dumb`.
