#!/usr/bin/env python3
"""Why did (or didn't) the Textual tier draw?

    python scripts/tier_probe.py

Run it IN THE TERMINAL YOU ARE ASKING ABOUT. Every gate below is answered from this
process, so a probe run through a pipe, an SSH command string or a CI job is answering
about that, not about your terminal - which is the whole reason the tier can decline on a
machine where everything looks installed.

Written because the launcher's tiers degrade silently ON PURPOSE - a console that cannot
host a full-screen app must still get a working launcher, so every failure returns None
rather than raising. That is right, and it means "I am not seeing the new interface" has
no error message anywhere. This prints the answer each gate actually gave.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _line(label: str, value, note: str = "") -> None:
    tail = f"   {note}" if note else ""
    print(f"  {label:<34} {value}{tail}")


def main() -> int:
    print(f"\nvirt-surv tier probe   ({REPO})\n")

    print("1. opt-outs")
    for name in ("VIRT_SURV_NO_APP", "VIRT_SURV_NO_TEXTUAL", "VIRT_SURV_FORCE_PTK"):
        raw = os.environ.get(name)
        _line(name, raw or "(unset)", "<- this alone disables a tier" if raw else "")

    print("\n2. streams  (the tier needs a REAL terminal on stderr and stdin)")
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            tty = stream.isatty() if stream is not None else None
        except Exception as exc:  # noqa: BLE001 - a stream that cannot answer is a no
            tty = f"error: {exc}"
        note = ""
        if name in ("stdin", "stderr") and tty is not True:
            note = "<- BLOCKS the Textual tier"
        if name == "stdout" and tty is not True:
            note = "(fine - `virt-surv go` captures stdout by design)"
        _line(f"sys.{name}.isatty()", tty, note)

    print("\n3. terminal size")
    _line("COLUMNS env", os.environ.get("COLUMNS") or "(unset)")
    try:
        size = shutil.get_terminal_size((0, 0))
        _line("shutil.get_terminal_size()", f"{size.columns}x{size.lines}")
    except Exception as exc:  # noqa: BLE001
        _line("shutil.get_terminal_size()", f"error: {exc}")
    for name in ("stderr", "stdout"):
        stream = getattr(sys, name, None)
        try:
            size = os.get_terminal_size(stream.fileno())
            _line(f"os.get_terminal_size({name})", f"{size.columns}x{size.lines}")
        except Exception as exc:  # noqa: BLE001
            _line(f"os.get_terminal_size({name})", f"error: {type(exc).__name__}")

    print("\n4. imports")
    for path in (REPO / "vendor", REPO / "scripts"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    for module in ("rich", "textual", "prompt_toolkit", "launcher_tiers", "launcher_textual"):
        try:
            loaded = __import__(module)
            where = getattr(loaded, "__file__", "?") or "?"
            inside = "vendored" if str(REPO / "vendor") in str(where) else "site-packages"
            _line(module, f"OK ({inside})")
        except Exception as exc:  # noqa: BLE001
            _line(module, f"FAILS: {type(exc).__name__}: {exc}")

    print("\n5. the verdict")
    try:
        import launcher_textual

        answer = launcher_textual.available()
        _line(
            "launcher_textual.available()",
            answer,
            "<- True means `virt-surv go` draws with Textual" if answer else "<- falls back",
        )
    except Exception as exc:  # noqa: BLE001
        _line("launcher_textual.available()", f"FAILS: {type(exc).__name__}: {exc}")

    print("\n6. which screens are ported to Textual today")
    try:
        import launcher_textual as lt

        ported = [
            n
            for n in ("run_app", "request_screen", "settings_screen", "chooser_screen")
            if hasattr(lt, n)
        ]
        _line("ported", ", ".join(ported) or "(none)")
        _line("NOT ported", "setup_screen, archive, jira, browse, artifacts, monitor, update")
        print("     so a first-time setup screen is prompt_toolkit even when Textual works.")
    except Exception:  # noqa: BLE001
        pass
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
