"""Persistent per-project configuration (foxygpu.yaml).

Lets a project remember how to deploy itself instead of retyping --cmd every
time. Only 'colab' is a supported runtime today — the `runtime` field exists
now so multi-runtime support (Kaggle, RunPod, Lambda, local GPU — see the
project's GitHub issues) doesn't require breaking the file format later.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

CONFIG_FILENAME = "foxygpu.yaml"
SUPPORTED_RUNTIMES = {"colab"}


class ProjectConfigError(ValueError):
    pass


@dataclass
class ProjectConfig:
    command: str
    runtime: str = "colab"
    gpu: bool = True
    name: Optional[str] = None
    expose: bool = True


def load_project_config(root: Path) -> Optional[ProjectConfig]:
    """Returns None if no foxygpu.yaml exists in root. Raises
    ProjectConfigError if one exists but is invalid."""
    path = root / CONFIG_FILENAME
    if not path.exists():
        return None

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ProjectConfigError(f"{CONFIG_FILENAME} is not valid YAML: {e}")

    if not isinstance(data, dict):
        raise ProjectConfigError(f"{CONFIG_FILENAME} must be a YAML mapping, got {type(data).__name__}")

    if "command" not in data:
        raise ProjectConfigError(f"{CONFIG_FILENAME} is missing the required 'command' field")

    runtime = data.get("runtime", "colab")
    if runtime not in SUPPORTED_RUNTIMES:
        raise ProjectConfigError(
            f"runtime: {runtime!r} is not supported yet (only {sorted(SUPPORTED_RUNTIMES)} "
            "currently work) — see the project's GitHub issues for multi-runtime progress"
        )

    return ProjectConfig(
        command=data["command"],
        runtime=runtime,
        gpu=bool(data.get("gpu", True)),
        name=data.get("name"),
        expose=bool(data.get("expose", True)),
    )


def write_project_config(root: Path, command: str, name: Optional[str] = None) -> Path:
    data = {"runtime": "colab", "gpu": True, "command": command}
    if name:
        data["name"] = name
    path = root / CONFIG_FILENAME
    path.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
    return path
