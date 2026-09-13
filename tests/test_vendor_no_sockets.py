"""No vendored module opens a socket (2026-09-13 framework review, step 7.9).

prompt_toolkit ships a full telnet server and an ssh contrib package; neither is used here
and a telnet server in a compliance repository is scanner bait at best. Both are pruned at
vendoring (vendor/MANIFEST.md, refresh procedure). This keeps them pruned, and catches any
future vendored package that brings a socket listener with it."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_ALLOWED: set[str] = set()  # relative paths under vendor/ that may import socket, with a reason


def test_no_vendored_module_imports_socket():
    offenders = []
    for path in sorted((REPO / "vendor").rglob("*.py")):
        rel = str(path.relative_to(REPO / "vendor")).replace("\\", "/")
        if rel in _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*(?:import socket\b|from socket import)", text, re.M):
            offenders.append(rel)
    assert not offenders, f"vendored modules open sockets: {offenders}"


def test_the_telnet_and_ssh_contrib_packages_stay_pruned():
    contrib = REPO / "vendor" / "prompt_toolkit" / "contrib"
    assert not (contrib / "telnet").exists()
    assert not (contrib / "ssh").exists()
