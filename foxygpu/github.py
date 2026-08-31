"""Publishes the FoxyGPU runner notebook as a GitHub Gist so Colab can open it
directly by URL — Colab only supports loading a notebook by URL from GitHub
(a repo file or a Gist), not from an arbitrary host or a local file.
"""

from typing import Optional, Tuple

import requests
import typer

from . import config

API_BASE = "https://api.github.com"
NOTEBOOK_FILENAME = "FoxyGPU_Runner.ipynb"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "foxygpu-cli",
    }


def get_or_prompt_token(explicit: Optional[str] = None) -> str:
    """Return a GitHub PAT, prompting once and caching it if none is known yet."""
    if explicit:
        config.save_github_token(explicit)
        return explicit
    token = config.get_github_token()
    if token:
        return token
    typer.echo(
        "FoxyGPU needs a GitHub Personal Access Token with the 'gist' scope to "
        "publish the Colab notebook. It must be a CLASSIC token — fine-grained "
        "tokens don't support the Gists API. Create one at "
        "https://github.com/settings/tokens -> Generate new token (classic)."
    )
    token = typer.prompt("GitHub token", hide_input=True)
    config.save_github_token(token)
    return token


def publish_notebook(token: str, notebook_json: str) -> Tuple[str, str]:
    """Create or update the FoxyGPU gist. Returns (gist_id, colab_url)."""
    body = {
        "description": "FoxyGPU Colab runner (auto-generated, safe to make public)",
        "public": True,
        "files": {NOTEBOOK_FILENAME: {"content": notebook_json}},
    }

    gist_id = config.get_gist_id()
    resp = None
    if gist_id:
        resp = requests.patch(f"{API_BASE}/gists/{gist_id}", headers=_headers(token), json=body, timeout=30)
        if resp.status_code == 404:
            gist_id = None  # stale/deleted gist id, fall through and create a new one

    if not gist_id:
        resp = requests.post(f"{API_BASE}/gists", headers=_headers(token), json=body, timeout=30)

    if resp.status_code == 401:
        raise SystemExit(
            "GitHub rejected the token (401 Unauthorized). Re-run with "
            "`foxygpu launch --github-token <new-token>` to update it, and make sure "
            "the token has the 'gist' scope."
        )
    if resp.status_code == 404 and not gist_id:
        raise SystemExit(
            "GitHub returned 404 Not Found creating the gist. The most common cause: "
            "the token is a *fine-grained* personal access token — those don't support "
            "the Gists API at all. Create a *classic* token instead "
            "(https://github.com/settings/tokens -> Generate new token (classic)) with "
            "the 'gist' scope, then re-run `foxygpu launch --github-token <new-token>`."
        )
    if not resp.ok:
        raise SystemExit(
            f"GitHub API error {resp.status_code} publishing the gist:\n{resp.text}"
        )

    data = resp.json()
    config.save_gist_id(data["id"])
    colab_url = "https://colab.research.google.com/gist/" + data["html_url"].split("gist.github.com/")[1]
    return data["id"], colab_url
