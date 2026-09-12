"""Atomic file writes, shared by every script that persists state.

WHY (2026-09-12 audit). The engagement-state writer already did this right (write a
sibling temp file, then os.replace) but it was the only place that did. Findings packs,
marker files, the auto-pending file that arms an unattended run, the launcher's machine
config and check_artifacts' own state fix-ups each wrote in place, so a crash or a second
process mid-write could leave a half-written JSON file where a whole one was expected.
Several of those files gate safety decisions. One helper, used everywhere, instead of the
same four lines re-typed with slightly different mistakes.

Contract:
  * The temp file is unique per call (pid + random suffix), so two concurrent writers of
    the same target never share a staging file; the last os.replace wins whole, never mixed.
  * Encoding is always explicit (utf-8) - Windows consoles default to cp1252 and a bare
    open() there has bitten this repo before.
  * The parent directory is created if missing.
  * On any failure the temp file is removed and the original is untouched.
  * Windows holds files open a moment longer than POSIX does (an indexer or an AV scanner
    can have the target open when os.replace lands), so replace and unlink retry briefly on
    PermissionError rather than failing a write that would have succeeded 20ms later.
  * Python 3.10 compatible (no 3.11+ syntax): pyproject's floor is 3.10 and CI tests it.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

# How hard to try again when Windows says "file in use". Sixteen attempts with a backoff
# that starts at 20ms and caps at 250ms, about 2.5s in all: eight threads replacing the
# same target on the Windows runner exhausted the first version's four tries in 150ms
# (test_fsutil, 2026-09-12), while a genuinely locked file still fails within seconds
# rather than hanging a CLI command.
_RETRY_ATTEMPTS = 16
_RETRY_SLEEP_SECONDS = 0.02
_RETRY_SLEEP_CAP_SECONDS = 0.25


def _retry_sleep(attempt: int) -> None:
    time.sleep(min(_RETRY_SLEEP_SECONDS * (1.5**attempt), _RETRY_SLEEP_CAP_SECONDS))


def _tmp_sibling(target: Path) -> Path:
    return target.with_name(f".{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """os.replace, retried past a transient Windows PermissionError. POSIX never hits the
    retry (rename over an open file is fine there), so this costs nothing on Linux/macOS."""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            _retry_sleep(attempt)


def unlink_quietly(path: str | os.PathLike[str], *, missing_ok: bool = True) -> bool:
    """Delete `path`, tolerating the Windows "file in use" window. True when it is gone
    afterwards. Never raises: every caller here is removing a temp or marker file, where a
    failure to delete is untidy rather than wrong."""
    target = Path(path)
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            target.unlink(missing_ok=missing_ok)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == _RETRY_ATTEMPTS - 1:
                return not target.exists()
            _retry_sleep(attempt)
        except OSError:
            return not target.exists()
    return not target.exists()


def atomic_write_text(path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8") -> None:
    """Write `text` to `path` so readers see either the old file or the new one, never a mix."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_sibling(target)
    try:
        with open(tmp, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, target)
    except BaseException:
        unlink_quietly(tmp)
        raise


def atomic_write_json(
    path: str | os.PathLike[str], obj: Any, *, indent: int = 2, sort_keys: bool = False
) -> None:
    """json.dumps + atomic_write_text, with the repo's usual shape (indent 2, trailing newline,
    non-ASCII kept as-is)."""
    text = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=sort_keys) + "\n"
    atomic_write_text(path, text)


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    """Read a JSON file; return `default` if it is missing. A present-but-corrupt file raises,
    on purpose: silently treating corruption as 'empty' is how a broken control looks healthy
    (audit finding S-17, W-10)."""
    target = Path(path)
    if not target.is_file():
        return default
    with open(target, encoding="utf-8") as fh:
        return json.load(fh)
