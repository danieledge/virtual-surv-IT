#!/usr/bin/env python3
"""PreToolUse(Bash, Write, Edit, MultiEdit, NotebookEdit) redirect: keep an engaged plugin-mode
session out of the plugin's OWN installed tree (incident log #19/#20, 2026-08).

WHY THIS EXISTS. Two live incidents, same root cause - a plugin-mode session's identity is
the working PROJECT, never the installed plugin's own clone, but nothing stopped either from
pointing there:
  - #19 (2026-08-17): a `cd` into the plugin repo silently flipped plugin-mode into
    repo-as-project - the bootstrap's mode detection is `Path.cwd()`-based (see
    `find_plugin_root.py`), so a session that changes directory into its own installed copy
    starts answering every later question about a different project. The prose fix ("never
    prepend cd") stands; `find_plugin_root.py` also grew a same-day identity/mode-flip
    breadcrumb (`identity_warning`, `mode_flip_warning`) years after this doc was written -
    but neither the live steady-state probe path nor the cold-bootstrap heredoc twin in
    `probe-bootstrap.md` calls it, so that detector is not reachable from a real session
    today. This closes the gap from the other end: stop the `cd` before it lands, rather than
    only detect the fallout afterward.
  - #20 (2026-08-08, twice): deliverables were written into the plugin's own source tree
    instead of the working project, recurring on the very next run after being documented.
    Prose alone did not hold.

Deliberately narrow and advisory (redirect family, not the safety-guard family):
- fires only when this IS genuine plugin mode - `CLAUDE_PLUGIN_ROOT` is set, resolves to a
  real directory, and differs from the working project (repo-as-project is unaffected: there
  `scripts/`, `.claude/`, etc. under the project root ARE the correct destination);
- fires only in an ENGAGED session (same team-session stamp as the other redirects) - a
  dormant session is plain Claude Code and manages its own files freely;
- the `cd` check looks only at the LEADING simple command (matching the prose rule's own
  shape, "never PREPEND cd") - it does not trace multi-`cd` chains or subshells, and it
  redirects ONCE per resolved target per session (a deliberate look at the plugin's bundled
  source is legitimate; the point is stopping a session from silently working there);
- the Write/Edit check has no legitimate counter-case during an engagement (there is no
  reason a deliverable belongs inside the plugin's own installed copy), so it blocks every
  time rather than once;
- any doubt - no plugin root, unreadable stdin, weird input, resolution failure - allows
  (exit 0). Convenience/correctness redirect, not a security boundary: never block work it
  cannot improve, and never fail closed on its own crash.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys

_STAMP_NAME = ".team-session.json"
_MAX_STAMPED_SESSIONS = 8
_STATE_NAME = ".plugin-root-guard.json"
_MAX_REMEMBERED = 400


def _stamp_candidates(root: str):
    """Copied rather than imported (a hook must not depend on the scripts package being
    importable) - same two-layout rule as every sibling redirect (2026-09-12 audit, H-22)."""
    return (
        os.path.join(root, "VSIT", "engagements", _STAMP_NAME),
        os.path.join(root, "artifacts", _STAMP_NAME),
    )


def _state_dir(root: str) -> str:
    vsit = os.path.join(root, "VSIT", "engagements")
    if os.path.isdir(vsit):
        return vsit
    return os.path.join(root, "artifacts")


def _stamped_session_ids(stamp_path: str) -> tuple:
    try:
        with open(stamp_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 - absent/unreadable: arms nothing
        return ()
    if not isinstance(data, dict):
        return ()
    ids = []
    for key in ("session", "session_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            ids.append(value)
    sessions = data.get("sessions")
    if isinstance(sessions, list):
        for entry in sessions[-_MAX_STAMPED_SESSIONS:]:
            value = entry.get("id") if isinstance(entry, dict) else entry
            if isinstance(value, str) and value:
                ids.append(value)
    return tuple(ids)


def _team_invoked_this_session(payload: dict, root: str) -> bool:
    """Advisory polarity: anything unknown (no session id, no stamp) stays SILENT."""
    sid = payload.get("session_id")
    if not sid:
        return False
    return any(sid in _stamped_session_ids(path) for path in _stamp_candidates(root))


def _already_redirected(root: str, sid: str, key: str) -> bool:
    path = os.path.join(_state_dir(root), _STATE_NAME)
    digest = hashlib.sha256(f"{sid}\n{key}".encode("utf-8")).hexdigest()[:16]
    seen = []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("session") == sid:
            seen = data.get("seen") or []
    except Exception:
        seen = []
    if digest in seen:
        return True
    seen.append(digest)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"session": sid, "seen": seen[-_MAX_REMEMBERED:]}, fh)
    except Exception:  # nosec B110 - best-effort de-dup cache write: failure just means a redirect may repeat, never silently vanish
        pass
    return False


def _genuine_plugin_root(project_root: str) -> str:
    """`CLAUDE_PLUGIN_ROOT`, verbatim, if this is really an installed-plugin session working
    a DIFFERENT project - "" for repo-as-project (the two paths coincide) or no known root.
    Mirrors `module_form_redirect.py`'s own plugin-mode discrimination."""
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or ""
    if not env_root or not os.path.isdir(env_root):
        return ""
    try:
        plugin_real = os.path.normcase(os.path.realpath(env_root))
        project_real = os.path.normcase(os.path.realpath(project_root))
    except OSError:
        return ""
    return "" if plugin_real == project_real else env_root


def _under(candidate_real: str, root_real: str) -> bool:
    return candidate_real == root_real or candidate_real.startswith(root_real + os.sep)


_SEPARATOR_RE = re.compile(r"&&|;|\|\||\||`|\$\(|\n")


def _leading_command(command: str) -> str:
    m = _SEPARATOR_RE.search(command)
    return command[: m.start()] if m else command


def _cd_target(command: str) -> str | None:
    """The directory a leading, un-chained `cd [-L|-P] DIR` would land in, or None for
    anything else - multiple operands, no operand, or `cd` not the first word."""
    try:
        parts = shlex.split(_leading_command(command).strip(), posix=True)
    except ValueError:
        return None
    if not parts or parts[0] != "cd":
        return None
    operands = [p for p in parts[1:] if p not in ("-L", "-P")]
    return operands[0] if len(operands) == 1 else None


def _resolve(path: str, root: str) -> str | None:
    abspath = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        return os.path.normcase(os.path.realpath(abspath))
    except OSError:
        return None


def _cd_advice(target: str) -> str:
    return (
        f"Blocked (plugin-root guard, redirect): `cd {target}` lands inside the plugin's own "
        "installed copy, not the working project. The step-0 open's mode detection reads "
        "Path.cwd() - a cd here silently flips this session from plugin-mode to "
        "repo-as-project for every later call, pointing engagement state at the wrong "
        "project (incident log #19). Run team-script calls from wherever you already are; "
        "reach a bundled file by full path if you need one, never by cd-ing to it. If you "
        "do need to inspect the plugin's own source, repeat this exact command and it goes "
        "through - this redirect fires once per target per session."
    )


def _write_advice(tool: str, path: str) -> str:
    return (
        f"Blocked (plugin-root guard): this {tool} targets a path inside the plugin's own "
        "installed copy, not the working project. A deliverable belongs under the working "
        "project (its VSIT/engagements/<slug>/ workspace) - writing into the plugin's own "
        "tree either vanishes on the next update or corrupts the shared install for every "
        "project that uses it (incident log #20, recurred the very next run after being "
        "documented in prose). Point this write at the working project instead."
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    tool = payload.get("tool_name")
    if tool not in ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        return 0
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        if not _team_invoked_this_session(payload, root):
            return 0
        plugin_root = _genuine_plugin_root(root)
        if not plugin_root:
            return 0
        plugin_real = _resolve(plugin_root, root)
        if not plugin_real:
            return 0
        sid = str(payload.get("session_id") or "")

        if tool == "Bash":
            command = tool_input.get("command")
            if not isinstance(command, str) or not command:
                return 0
            target = _cd_target(command)
            if not target:
                return 0
            dest_real = _resolve(target, root)
            if not dest_real or not _under(dest_real, plugin_real):
                return 0
            if _already_redirected(root, sid, f"cd:{dest_real}"):
                return 0
            sys.stderr.write(_cd_advice(target) + "\n")
            return 2

        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not isinstance(path, str) or not path:
            return 0
        dest_real = _resolve(path, root)
        if not dest_real or not _under(dest_real, plugin_real):
            return 0
        sys.stderr.write(_write_advice(tool, path) + "\n")
        return 2
    except Exception:
        return 0  # advisory tier - never break a session over a correctness rule


if __name__ == "__main__":
    sys.exit(main())
