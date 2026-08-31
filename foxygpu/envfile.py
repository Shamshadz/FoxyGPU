"""Minimal .env-style file parsing — no new dependency for something this small.

Supports KEY=VALUE per line, blank lines, '#' comments, and optionally
single/double-quoted values. Deliberately not a full dotenv implementation
(no variable expansion, no multiline values) — good enough for passing
secrets through to a deployed process.
"""

from pathlib import Path
from typing import Dict


class EnvFileError(ValueError):
    pass


def parse_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        raise EnvFileError(f"env file not found: {path}")

    result: Dict[str, str] = {}
    for lineno, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EnvFileError(f"{path}:{lineno}: expected KEY=VALUE, got {raw_line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not key:
            raise EnvFileError(f"{path}:{lineno}: empty key in {raw_line!r}")
        result[key] = value
    return result
