import asyncio
import tempfile
import webbrowser
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
import typer
import websockets
from rich.console import Console
from rich.table import Table

from . import github as gh
from .client import DISCONNECTED_MESSAGE, AgentClient
from .config import save_config
from .detect import detect_command
from .envfile import EnvFileError, parse_env_file
from .notebook_builder import build_notebook_json
from .project_config import CONFIG_FILENAME, ProjectConfigError, load_project_config, write_project_config


def _resolve_env(
    env_pairs: List[str],
    env_file: Optional[Path],
) -> Dict[str, str]:
    """--env-file values first, then --env KEY=VALUE overrides on conflicts."""
    resolved: Dict[str, str] = {}
    if env_file:
        try:
            resolved.update(parse_env_file(env_file))
        except EnvFileError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    for pair in env_pairs:
        if "=" not in pair:
            console.print(f"[red]--env expects KEY=VALUE, got: {pair!r}[/red]")
            raise typer.Exit(1)
        key, _, value = pair.partition("=")
        resolved[key] = value
    return resolved

app = typer.Typer(help="Run local code on Google Colab's free GPU.", add_completion=False)
console = Console()

# The runner notebook is identical for every user (nothing personalized is baked
# in - the agent's token is generated fresh at runtime in Colab). So instead of
# publishing a per-user copy somewhere, `launch` just opens FoxyGPU's own committed
# copy directly - Colab loads notebooks from any public GitHub repo with no auth
# at all, so no one needs to hand over a GitHub token for the default flow.
NOTEBOOK_REPO_URL = (
    "https://colab.research.google.com/github/Shamshadz/FoxyGPU/blob/main/"
    "notebook/FoxyGPU_Runner.ipynb"
)

DEFAULT_IGNORES = {
    ".git",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    ".foxygpu",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}


def _load_ignores(root: Path) -> Set[str]:
    ignores = set(DEFAULT_IGNORES)
    ignore_file = root / ".foxygpuignore"
    if ignore_file.exists():
        for line in ignore_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ignores.add(line)
    return ignores


def _zip_project(root: Path, ignores: Set[str]) -> Path:
    fd, tmp_name = tempfile.mkstemp(suffix=".zip")
    import os

    os.close(fd)
    tmp_zip = Path(tmp_name)
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            rel = path.relative_to(root)
            if any(part in ignores for part in rel.parts):
                continue
            zf.write(path, rel)
    return tmp_zip


async def _stream_logs(client: AgentClient, process_id: str) -> None:
    url = client.ws_logs_url(process_id)
    try:
        async with websockets.connect(url) as ws:
            async for message in ws:
                console.print(message)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print(
            f"\n[yellow]Detached.[/yellow] The remote process ({process_id}) keeps running on Colab.\n"
            f"  foxygpu logs {process_id}   # reconnect and watch logs again\n"
            f"  foxygpu stop {process_id}   # stop it"
        )
    except websockets.exceptions.ConnectionClosedOK:
        pass  # the process finished and the agent closed the stream normally
    except (websockets.exceptions.ConnectionClosedError, OSError):
        console.print(f"\n[red]{DISCONNECTED_MESSAGE.format(url=client.url)}[/red]")


@app.command()
def launch(
    gist: bool = typer.Option(
        False,
        "--gist",
        help="Publish your own copy to a GitHub Gist instead (needs a GitHub token). "
        "Only useful if you've modified foxygpu/agent_source.py locally and don't "
        "want to fork/host the repo yourself.",
    ),
    github_token: Optional[str] = typer.Option(
        None, "--github-token", help="GitHub PAT with 'gist' scope, used only with --gist"
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Print the Colab URL instead of opening a browser"
    ),
) -> None:
    """Open the FoxyGPU runner notebook in Colab.

    By default this opens FoxyGPU's own committed notebook straight from its public
    GitHub repo - Colab loads public GitHub files with no authentication, so this
    needs no token and no publishing step at all.
    """
    if gist:
        token = gh.get_or_prompt_token(github_token)
        console.print("Publishing your own copy as a Gist ...")
        notebook_json = build_notebook_json()
        gist_id, colab_url = gh.publish_notebook(token, notebook_json)
        console.print(f"[green]Notebook published[/green] (gist {gist_id})")
    else:
        colab_url = NOTEBOOK_REPO_URL

    console.print(f"Colab URL: {colab_url}")
    if not no_browser:
        webbrowser.open(colab_url)
    console.print(
        "\nIn Colab: select a GPU runtime, run all cells, then copy the "
        "`foxygpu connect ...` command it prints back here."
    )


@app.command()
def notebook(
    output: Path = typer.Argument(
        Path("FoxyGPU_Runner.ipynb"), help="Where to write the notebook file"
    ),
) -> None:
    """Write the runner notebook to a local file (manual-upload fallback for `launch`)."""
    output.write_text(build_notebook_json())
    console.print(f"[green]Wrote[/green] {output}")


@app.command()
def connect(
    url: str = typer.Argument(..., help="Control URL printed by the FoxyGPU notebook"),
    token: str = typer.Option(..., "--token", "-t", help="Bearer token printed by the notebook"),
) -> None:
    """Save the agent's control URL and token for future commands."""
    save_config(url, token)
    console.print(f"[green]Connected[/green] to {url}")


def _examples_epilog(command: str) -> str:
    return f"""
Examples:

FastAPI / Python web app:
  foxygpu {command} ./my-app --cmd 'pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port $PORT' --expose

Node.js app (read process.env.PORT in your server code):
  foxygpu {command} ./my-node-app --cmd 'npm install && node server.js' --expose

Frontend dev server (Vite/React/etc.):
  foxygpu {command} ./my-frontend --cmd 'npm install && npm run dev -- --host 0.0.0.0 --port $PORT' --expose

One-off script or training job (no server, skip --expose):
  foxygpu {command} ./train-job --cmd 'pip install -r requirements.txt && python train.py'

PowerShell / bash / zsh all use the same single-quote syntax above for --cmd.
cmd.exe does not - use PowerShell or a bash-like shell instead.
"""


RUN_EXAMPLES_EPILOG = _examples_epilog("run")
REDEPLOY_EXAMPLES_EPILOG = _examples_epilog("redeploy")


def _deploy(
    client: AgentClient,
    path: Path,
    cmd: str,
    name: Optional[str],
    expose_after: bool,
    stop_previous: bool,
    env: Optional[Dict[str, str]] = None,
) -> None:
    root = path.resolve()
    if not root.is_dir():
        console.print(f"[red]{root} is not a directory[/red]")
        raise typer.Exit(1)

    project_name = name or root.name

    if stop_previous:
        previous = client.latest_process_by_name(project_name)
        if previous and previous["status"] == "running":
            console.print(
                f"Stopping previous deployment of '{project_name}' ({previous['id']}) ..."
            )
            client.stop_process(previous["id"])

    ignores = _load_ignores(root)
    console.print(f"Zipping {root} ...")
    zip_path = _zip_project(root, ignores)
    try:
        console.print("Uploading ...")
        project_id = client.upload_project(str(zip_path), project_name)
        console.print(f"[green]Project uploaded[/green] ({project_id})")
        if env:
            console.print(f"Passing env vars: {', '.join(env.keys())} (values not shown/logged)")
        process_id, port = client.start_process(project_id, cmd, env=env)
        console.print(f"[green]Started[/green] process {process_id} on assigned port {port}")
        if expose_after:
            console.print(f"Requesting tunnel for port {port} ...")
            try:
                result = client.create_tunnel(port)
                console.print(f"[green]Public URL:[/green] {result['url']}")
            except requests.exceptions.HTTPError as e:
                console.print(
                    f"[yellow]Could not expose port {port} automatically[/yellow] ({e}). "
                    f"The process is still running — try `foxygpu expose {port}` again once resolved."
                )
        else:
            console.print(f"Run `foxygpu expose` (or `foxygpu expose {port}`) once it's listening.")
        console.print("Streaming logs (Ctrl+C stops watching, the remote process keeps running) ...\n")
        asyncio.run(_stream_logs(client, process_id))
    finally:
        zip_path.unlink(missing_ok=True)


@app.command(epilog=RUN_EXAMPLES_EPILOG)
def run(
    path: Path = typer.Argument(Path("."), help="Project directory to upload and run"),
    cmd: str = typer.Option(
        ...,
        "--cmd",
        "-c",
        help="Shell command to start the app. Reference $PORT for the port the "
        "agent assigns you, e.g. 'uvicorn main:app --host 0.0.0.0 --port $PORT'",
    ),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Project name"),
    expose_after: bool = typer.Option(
        False, "--expose", help="Immediately open a public tunnel to the assigned port"
    ),
    env_pairs: List[str] = typer.Option(
        [],
        "--env",
        "-e",
        help="Extra env var as KEY=VALUE (repeatable). Never embedded in --cmd, so it "
        "won't show up in `foxygpu status` or the logs, unlike 'export SECRET=x && ...'",
    ),
    env_file: Optional[Path] = typer.Option(
        None, "--env-file", help="Load KEY=VALUE lines from a file (e.g. .env)"
    ),
) -> None:
    """Zip PATH, upload it to the agent, and start CMD on the Colab VM.

    The agent picks a free port for you (env vars $PORT / $FOXYGPU_PORT) so you
    don't need to hardcode one or worry about colliding with the agent's own
    port - reference $PORT in --cmd instead of a literal number.
    """
    client = AgentClient.from_config()
    env = _resolve_env(env_pairs, env_file)
    _deploy(client, path, cmd, name, expose_after, stop_previous=False, env=env)


@app.command(epilog=REDEPLOY_EXAMPLES_EPILOG)
def redeploy(
    path: Path = typer.Argument(Path("."), help="Project directory to upload and run"),
    cmd: str = typer.Option(
        ...,
        "--cmd",
        "-c",
        help="Shell command to start the app. Reference $PORT for the port the "
        "agent assigns you, e.g. 'uvicorn main:app --host 0.0.0.0 --port $PORT'",
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Project name (also used to find the previous deployment to stop)"
    ),
    expose_after: bool = typer.Option(
        False, "--expose", help="Immediately open a public tunnel to the assigned port"
    ),
    env_pairs: List[str] = typer.Option(
        [],
        "--env",
        "-e",
        help="Extra env var as KEY=VALUE (repeatable). Never embedded in --cmd, so it "
        "won't show up in `foxygpu status` or the logs, unlike 'export SECRET=x && ...'",
    ),
    env_file: Optional[Path] = typer.Option(
        None, "--env-file", help="Load KEY=VALUE lines from a file (e.g. .env)"
    ),
) -> None:
    """Stop the previous deployment of this project (if any), then run the updated code.

    Identifies "the previous deployment" by project name — PATH's directory
    name by default, same as `run`, or --name if you passed one originally.
    If the new run happens to land back on the same port (likely, since
    stopping the old one just freed it), an existing exposed URL for that
    port keeps working automatically — no need to `expose` again.
    """
    client = AgentClient.from_config()
    env = _resolve_env(env_pairs, env_file)
    _deploy(client, path, cmd, name, expose_after, stop_previous=True, env=env)


@app.command()
def deploy(
    path: Path = typer.Argument(Path("."), help="Project directory to deploy"),
    env_pairs: List[str] = typer.Option(
        [],
        "--env",
        "-e",
        help="Extra env var as KEY=VALUE (repeatable), overriding foxygpu.yaml's env/env_file",
    ),
    env_file: Optional[Path] = typer.Option(
        None, "--env-file", help="Load KEY=VALUE lines from a file, overriding foxygpu.yaml's env"
    ),
) -> None:
    """One-command deploy: read PATH/foxygpu.yaml if present; otherwise try to
    detect your framework, write one, and use that.

    Behaves like `redeploy` (stops the previous deployment of the same
    project first). Supported detection today: a FastAPI or Flask app next
    to a requirements.txt, or a Vite/Next.js/generic npm-scripted project
    next to a package.json. Anything else: write foxygpu.yaml yourself, e.g.

    \b
      runtime: colab
      gpu: true
      command: pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port $PORT
      env_file: .env   # don't put real secrets directly under env: in a committed file

    """
    client = AgentClient.from_config()
    root = path.resolve()
    if not root.is_dir():
        console.print(f"[red]{root} is not a directory[/red]")
        raise typer.Exit(1)

    try:
        project_config = load_project_config(root)
    except ProjectConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if project_config is None:
        detected = detect_command(root)
        if not detected:
            console.print(
                f"[red]No {CONFIG_FILENAME} found in {root}, and couldn't auto-detect a "
                "framework.[/red]\n"
                f"Write a {CONFIG_FILENAME} yourself (see `foxygpu deploy --help`), or use "
                "`foxygpu run`/`redeploy` with an explicit --cmd instead."
            )
            raise typer.Exit(1)
        config_path = write_project_config(root, detected)
        console.print(f"[green]Detected a project[/green] — wrote {config_path.name}:")
        console.print(f"  command: {detected}")
        project_config = load_project_config(root)

    env = dict(project_config.env)
    env.update(_resolve_env(env_pairs, env_file))

    _deploy(
        client,
        path,
        project_config.command,
        project_config.name,
        project_config.expose,
        stop_previous=True,
        env=env,
    )


@app.command()
def expose(
    port: Optional[int] = typer.Argument(
        None, help="Port on the Colab VM to expose (defaults to the most recently started process's port)"
    ),
) -> None:
    """Ask the agent to open a public tunnel to PORT."""
    client = AgentClient.from_config()
    if port is None:
        port = client.latest_process_port()
        if port is None:
            console.print("[red]No running process to infer a port from - pass one explicitly.[/red]")
            raise typer.Exit(1)
        console.print(f"No port given, using the most recently started process's port: {port}")
    console.print(f"Requesting tunnel for port {port} ...")
    result = client.create_tunnel(port)
    console.print(f"[green]Public URL:[/green] {result['url']}")


@app.command()
def status() -> None:
    """Show GPU status and running processes."""
    client = AgentClient.from_config()
    gpu = client.gpu_status()
    console.print("[bold]GPU[/bold]")
    console.print(gpu["output"])

    processes = client.list_processes()
    table = Table(title="Processes")
    table.add_column("ID")
    table.add_column("Command")
    table.add_column("Status")
    table.add_column("PID")
    table.add_column("Port")
    table.add_column("Env vars")
    for p in processes:
        env_keys = p.get("env_keys") or []
        table.add_row(
            p["id"], p["cmd"], p["status"], str(p["pid"]), str(p.get("port")), ", ".join(env_keys)
        )
    console.print(table)


@app.command()
def logs(process_id: str = typer.Argument(..., help="Process ID from `foxygpu status`")) -> None:
    """Stream logs for a running process."""
    client = AgentClient.from_config()
    asyncio.run(_stream_logs(client, process_id))


@app.command()
def stop(
    process_id: Optional[str] = typer.Argument(None, help="Process ID from `foxygpu status`"),
    all_: bool = typer.Option(False, "--all", help="Stop every currently-running process"),
) -> None:
    """Stop a running process, or every running process with --all."""
    client = AgentClient.from_config()

    if all_:
        processes = [p for p in client.list_processes() if p["status"] == "running"]
        if not processes:
            console.print("No running processes.")
            return
        for p in processes:
            result = client.stop_process(p["id"])
            console.print(f"Process {p['id']}: {result['status']}")
        console.print(f"[green]Stopped {len(processes)} process(es).[/green]")
        return

    if not process_id:
        console.print("[red]Pass a process ID, or use --all to stop every running process.[/red]")
        raise typer.Exit(1)

    result = client.stop_process(process_id)
    console.print(f"Process {process_id}: {result['status']}")


if __name__ == "__main__":
    app()
