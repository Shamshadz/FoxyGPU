# Ollama chat example

A minimal ChatGPT-style app: a FastAPI backend that proxies chat requests to a
local Ollama server, plus a static frontend. Meant to run on a FoxyGPU-managed
Colab GPU, where `ollama serve` runs alongside it on `localhost:11434`.

## Deploying with FoxyGPU

After `foxygpu launch` and `foxygpu connect` (see the main [README](../../README.md)):

```bash
foxygpu run /path/to/examples/ollama-chat --cmd 'apt-get update -qq && apt-get install -y -qq zstd && curl -fsSL https://ollama.com/install.sh | sh && (ollama serve > ollama.log 2>&1 &) && sleep 8 && TERM=dumb ollama pull llama3.2:1b && pip install -q -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port $PORT' --expose
```

In PowerShell, use single quotes around `--cmd` exactly as above so `$PORT`
isn't expanded locally — it needs to reach the remote shell literally. This
does **not** work as written in `cmd.exe`, which has no concept of single
quotes as literal-string delimiters and will mangle the `&&`-chained command;
use PowerShell.

What each piece does:
- `apt-get install zstd` — Colab's base image is missing this, which Ollama's
  installer needs for extraction (fails with a clear error otherwise).
- `(ollama serve > ollama.log 2>&1 &)` — starts the Ollama server in the
  background, redirected to a log file so it doesn't interfere with this
  command's own output.
- **`TERM=dumb` before `ollama pull`** — without this, `ollama pull`'s
  animated progress renderer never exits once run through a non-interactive
  pipe (like the one FoxyGPU's agent uses to capture command output), even
  though the actual download completes. The whole `&&` chain then hangs
  forever waiting on a command that already succeeded (confirmable via
  `ollama list` mid-hang — the model shows up as downloaded). Setting
  `TERM=dumb` makes it fall back to plain, non-animated output that exits
  normally.

Swap `llama3.2:1b` for a different model in both the `ollama pull` command and
the `OLLAMA_MODEL` environment variable (defaults to `llama3.2:1b`, read in
[main.py](main.py)) if you want a different one.
