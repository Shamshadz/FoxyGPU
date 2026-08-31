# FoxyGPU

Run local code — FastAPI backends, frontend dev servers, or anything else — on
Google Colab's free-tier GPU, driven entirely from your own machine.

## Install

```bash
pip install foxygpu
```

## How it works

`foxygpu launch` opens FoxyGPU's own runner notebook directly in Colab — no
manual notebook upload, and no GitHub account or token needed for the default
path. That notebook starts a control-plane agent, reached from your machine
over a Cloudflare Tunnel (no account needed). The local `foxygpu` CLI talks to
that agent to upload your project, start it with a shell command, stream its
logs, and expose whatever port it's listening on with its own public URL.

```
┌───────────────────┐
│    foxygpu CLI    │
│  (local machine)  │
└───────────────────┘
          │
          │  HTTPS/WSS via a Cloudflare Tunnel
          ▼
┌──────────────────────────────┐
│         foxygpu_agent        │
│    (Colab VM, GPU runtime)   │
│      spawns your process     │
│  (uvicorn / npm / anything)  │
└──────────────────────────────┘
```

## Quickstart

```bash
foxygpu launch                     # opens Colab, no token needed
# run the cells; copy the `foxygpu connect ...` command it prints
foxygpu connect <url> --token <token>

foxygpu run ./my-app --cmd 'pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port $PORT' --expose
```

The agent picks a free port for you and injects it as `$PORT` — you never have
to think about which ports are free. Once you know your `--cmd`, save it to a
`foxygpu.yaml` and just run `foxygpu deploy` from then on — it also
auto-detects common frameworks (FastAPI/Flask, Vite/Next.js) if you don't have
one yet.

Made changes and want to update what's running? `foxygpu redeploy` stops the
previous deployment of the same project before starting the new one.

Need to pass a database URL or API key? Use `--env`/`--env-file` — never embed
secrets directly in `--cmd`, since that gets shown in `foxygpu status` and the
logs.

## Any language, any framework

`foxygpu run`/`deploy` just execute a shell command on the VM — Node, Go,
Rust, Flask, Streamlit, a plain training script, anything the Colab VM can
run works, not just Python or FastAPI.

## Full documentation

The [GitHub README](https://github.com/Shamshadz/FoxyGPU#readme) has the
complete command reference, a full working example (a real GPU-backed Ollama
chat app), known limitations, and contributor docs.
