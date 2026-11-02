"""Minimal .env loader (no extra dependency).

Reads KEY=VALUE lines; never overrides variables already set in the process
environment (so a host's secret store always wins). Set VERIFAI_SKIP_DOTENV=1
to disable (the test suite does this so local keys never reach tests).
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> list[str]:
    if os.environ.get('VERIFAI_SKIP_DOTENV') == '1' or not path.is_file():
        return []
    loaded = []
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if key and key not in os.environ and value != '':
            os.environ[key] = value
            loaded.append(key)
    return loaded
