#!/usr/bin/env python3
"""Where do the seconds go on every hook call?

    python -m scripts.hook_latency_probe [--runs 15] [--json FILE]

Run it ON THE MACHINE THAT IS SLOW, from the project directory the slow session runs in.
Every number below is measured in this process, on this box, against the real launcher.

The report it answers: every PreToolUse safety hook costing seconds per Bash and Read call,
enough to dominate a parallel review. The code that runs on each call has four suspects in
its own comments (the Git Bash `sh` spawn, the Python cold start, the fan-out lock,
endpoint-security scanning of each new process) and no way to tell them apart on the
affected box. A total is not a root cause. This tool reproduces the total
with the real launcher, then times each layer of the path on its own and attributes the
milliseconds, so the layers add up to something close to the total and the biggest one is
named, with the specific fix that exists for it.

What one hook call does (`.claude/hooks/run-guard.sh scripts/bash_hook_dispatcher.py`):

  1. Claude Code spawns `sh` (Git Bash on Windows) on the launcher.
  2. The launcher resolves an interpreter: a read of the .guard-interpreter cache plus
     `command -v` on a hit; on a miss it executes each candidate to version-check it.
  3. Daemon route (the default since 2026-08-25, `team-preferences.json` "guard_daemon"):
     with a cache hit it goes STRAIGHT to `python -S guard_daemon_client.py`, no lock. The
     client connects to the daemon over loopback and relays the answer. If no daemon
     answers, the client spawns a detached daemon for next time and falls back to a SECOND
     Python process running the dispatcher directly: two cold starts per call, every call,
     until a daemon is up.
  4. Cold route (daemon off): the mkdir fan-out lock, two `cat`s of state files, then
     `python -S bash_hook_dispatcher.py`, which imports every applicable guard and runs it.

The probe executes only the team's own launcher, the team's own scripts, `sh -c` with shell
builtins, and `python -c pass`. Nothing under review is run. Standard library only, no
network beyond the loopback socket the guard daemon already uses, no installs.

Side effect to know about: reproducing the real path means that if the daemon is enabled
and not running, the launcher itself will start one, exactly as a real session would.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import math
import os
import platform
import shutil
import subprocess  # nosec B404 - fixed argv, shell=False, the team's own launcher and sh -c
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parent.parent

DEFAULT_RUNS = 15
DEFAULT_FANOUT = 4
_TIMEOUT = 60.0

# Route names (which path a steady-state call takes on this box).
ROUTE_DAEMON = "daemon"
ROUTE_DAEMON_UNREACHABLE = "daemon-unreachable"
ROUTE_COLD = "cold"

# Every layer the decomposition can name, with the fix that exists for it. Remediation text is
# chosen per layer at verdict time (see _remediation) because the right fix depends on the
# route and on the environment facts, not on the layer alone.
LAYER_TITLES = {
    "sh_startup": "sh startup (the shell spawn per hook call)",
    "interp_resolution": "interpreter resolution (cache read + command -v)",
    "interp_resolution_cold": "interpreter resolution with no cache (executes candidates)",
    "lock_cycle": "fan-out lock acquire + stamp + release (mkdir, date, echo, rm)",
    "python_cold_start": "Python cold start (python -S -c pass)",
    "python_cold_start_fallback": "second Python cold start (daemon fallback runs the dispatcher)",
    "client_import": "daemon client imports (json, socket)",
    "daemon_roundtrip": "daemon round-trip over loopback",
    "connect_failure": "failed connect to the daemon (before the fallback)",
    "dispatcher_imports": "dispatcher + guard module imports",
    "guard_logic": "guard logic itself (dispatcher run minus start-up and imports)",
    "unattributed": "unattributed (process creation of the launcher, AV scan of each spawn, scheduling)",
}

_AV_VENDOR_DIRS = (
    ("Windows Defender", r"C:\Program Files\Windows Defender"),
    ("CrowdStrike", r"C:\Program Files\CrowdStrike"),
    ("Sophos", r"C:\Program Files\Sophos"),
    ("SentinelOne", r"C:\Program Files\SentinelOne"),
    ("Carbon Black", r"C:\Program Files\Confer"),
    ("Cylance", r"C:\Program Files\Cylance"),
    ("Trellix / McAfee", r"C:\Program Files\McAfee"),
    ("Trellix", r"C:\Program Files\Trellix"),
    ("Symantec", r"C:\Program Files\Symantec"),
    ("Tanium", r"C:\Program Files\Tanium"),
    ("Cisco Secure Endpoint", r"C:\Program Files\Cisco\AMP"),
    (
        "Microsoft Defender for Endpoint",
        r"C:\Program Files\Windows Defender Advanced Threat Protection",
    ),
)


# ----------------------------------------------------------------------------- statistics


def median(values: list) -> float:
    good = sorted(v for v in values if v is not None)
    if not good:
        return 0.0
    n = len(good)
    return good[n // 2] if n % 2 else (good[n // 2 - 1] + good[n // 2]) / 2


def percentile(values: list, pct: float) -> float:
    """Nearest-rank percentile over the successful samples. pct in [0, 100]."""
    good = sorted(v for v in values if v is not None)
    if not good:
        return 0.0
    rank = max(1, math.ceil(pct / 100.0 * len(good)))
    return good[min(rank, len(good)) - 1]


def steady(values: list) -> float:
    """The number to attribute: the median after dropping the single slowest sample when
    there are at least four, so one AV scan or scheduling hiccup does not become the layer."""
    good = sorted(v for v in values if v is not None)
    if len(good) >= 4:
        good = good[:-1]
    return median(good)


def summarise(values: list) -> dict:
    good = [v for v in values if v is not None]
    return {
        "n": len(values),
        "failed": len(values) - len(good),
        "p50_ms": round(median(good), 1),
        "p90_ms": round(percentile(good, 90), 1),
        "max_ms": round(max(good), 1) if good else 0.0,
        "min_ms": round(min(good), 1) if good else 0.0,
        "first_ms": round(good[0], 1) if good else 0.0,
        "steady_ms": round(steady(good), 1),
        "samples_ms": [None if v is None else round(v, 1) for v in values],
    }


def warm_vs_cold(values: list) -> dict:
    """First spawn against the steady state of identical later spawns. A first call several
    times slower than the rest, on a command whose binary never changes, is the shape an
    endpoint-security first-seen scan leaves; a flat series is the shape of per-process
    scanning (or of no scanning at all, when the numbers are small)."""
    good = [v for v in values if v is not None]
    if len(good) < 3:
        return {"verdict": "insufficient", "first_ms": None, "steady_ms": None, "ratio": None}
    first = good[0]
    rest = steady(good[1:])
    ratio = (first / rest) if rest > 0 else None
    if ratio is not None and ratio >= 2.0 and first - rest >= 100:
        verdict = "first-spawn-penalty"
    else:
        verdict = "flat"
    return {
        "verdict": verdict,
        "first_ms": round(first, 1),
        "steady_ms": round(rest, 1),
        "ratio": None if ratio is None else round(ratio, 2),
    }


# ----------------------------------------------------------------------------- measuring


def measure_repeated(
    argv_fn: Callable[[], tuple], n: int, timeout: float = _TIMEOUT, runner=None
) -> list:
    """n separate, fresh subprocess invocations, one after another. argv_fn() returns
    (argv, kwargs) recomputed each call so the payload can vary. Elapsed milliseconds per
    call; None means that call errored or timed out. `runner` replaces subprocess.run in
    tests. The same shape as install_helper._measure_repeated, copied rather than imported so
    this probe never pulls a 12,000-line installer into a diagnostic (and never creates an
    import cycle the other way)."""
    run = runner or subprocess.run
    samples = []
    for _ in range(n):
        argv, kwargs = argv_fn()
        start = time.monotonic()
        try:
            run(argv, capture_output=True, timeout=timeout, **kwargs)  # nosec B603
            samples.append((time.monotonic() - start) * 1000.0)
        except (OSError, subprocess.TimeoutExpired):
            samples.append(None)
    return samples


def measure_repeated_rc(
    argv_fn: Callable[[], tuple], n: int, timeout: float = _TIMEOUT, runner=None
) -> tuple:
    """As measure_repeated, and also returns each call's exit code (None on error)."""
    run = runner or subprocess.run
    samples, codes = [], []
    for _ in range(n):
        argv, kwargs = argv_fn()
        start = time.monotonic()
        try:
            proc = run(argv, capture_output=True, timeout=timeout, **kwargs)  # nosec B603
            samples.append((time.monotonic() - start) * 1000.0)
            codes.append(getattr(proc, "returncode", None))
        except (OSError, subprocess.TimeoutExpired):
            samples.append(None)
            codes.append(None)
    return samples, codes


def measure_concurrent(
    argv_fn: Callable[[], tuple], n: int, timeout: float = _TIMEOUT, runner=None
):
    """n concurrent invocations (the fan-out a parallel review produces). Returns
    (per-call ms list, total wall ms)."""
    run = runner or subprocess.run

    def _one(_i):
        argv, kwargs = argv_fn()
        start = time.monotonic()
        try:
            run(argv, capture_output=True, timeout=timeout, **kwargs)  # nosec B603
            return (time.monotonic() - start) * 1000.0
        except (OSError, subprocess.TimeoutExpired):
            return None

    batch_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, n)) as pool:
        samples = list(pool.map(_one, range(n)))
    return samples, (time.monotonic() - batch_start) * 1000.0


# ----------------------------------------------------------------------------- environment


def resolve_sh() -> Optional[str]:
    """The POSIX shell Claude Code will run the launcher with. CLAUDE_CODE_GIT_BASH_PATH
    first (the documented Windows override), then PATH, then the usual Git for Windows
    locations, derived from git.exe where possible."""
    override = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if override:
        p = Path(override)
        candidates = []
        if p.is_file():
            candidates += [p.parent / "sh.exe", p]
        elif p.is_dir():
            candidates += [p / "sh.exe", p / "bin" / "sh.exe", p / "usr" / "bin" / "sh.exe"]
        for c in candidates:
            if c.is_file():
                return str(c)
    found = shutil.which("sh")
    if found:
        return found
    if sys.platform == "win32":
        import ntpath

        roots = []
        git_exe = shutil.which("git")
        if git_exe:
            roots.append(ntpath.dirname(ntpath.dirname(git_exe)))
        roots += [r"C:\Program Files\Git", r"C:\Program Files (x86)\Git"]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(ntpath.join(local, "Programs", "Git"))
        for root in roots:
            for rel in (("bin", "sh.exe"), ("usr", "bin", "sh.exe")):
                candidate = ntpath.join(root, *rel)
                if Path(candidate).is_file():
                    return candidate
    return None


def interpreter_cache_path(project_root: Path) -> Path:
    """The same two-location rule run-guard.sh uses: VSIT/local first, then .claude/."""
    new = project_root / "VSIT" / "local" / "guard-interpreter"
    if new.is_file():
        return new
    return project_root / ".claude" / ".guard-interpreter"


def _json_key_is(path: Path, key: str, value: str) -> bool:
    """run-guard.sh's `_json_has`: whitespace stripped, literal `"key":value` anywhere."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    compact = "".join(text.split())
    return f'"{key}":{value}' in compact


def daemon_preference(project_root: Path, installer_json: Optional[Path] = None) -> dict:
    """Replicates run-guard.sh's precedence: on by default; installer.json
    default_guard_daemon:false turns it off; a project team-preferences.json wins in both
    directions (the launcher only honours the OFF direction from an owned, non-symlink file;
    the probe reports the file's own say and notes the trust check separately)."""
    if installer_json is None:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        installer_json = Path(base) / "virt-surv-it" / "installer.json"
    prefs = project_root / ".claude" / "team-preferences.json"
    enabled = True
    source = "default (on since 2026-08-25)"
    if installer_json.is_file() and _json_key_is(installer_json, "default_guard_daemon", "false"):
        enabled = False
        source = f"{installer_json} default_guard_daemon:false"
    prefs_value = None
    if prefs.is_file():
        if _json_key_is(prefs, "guard_daemon", "false"):
            prefs_value = False
            enabled = False
            source = f"{prefs} guard_daemon:false"
        elif _json_key_is(prefs, "guard_daemon", "true"):
            prefs_value = True
            enabled = True
            source = f"{prefs} guard_daemon:true"
    return {
        "enabled": enabled,
        "source": source,
        "prefs_file_present": prefs.is_file(),
        "prefs_value": prefs_value,
    }


def _load_client(plugin_root: Path):
    path = plugin_root / "scripts" / "guard_daemon_client.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_vsit_guard_daemon_client_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
    except Exception:  # noqa: BLE001 - a client that cannot load is a fact, not a crash
        return None


def daemon_reachability(
    plugin_root: Path, project_root: Path, payload_text: str, tries: int = 5
) -> dict:
    """Is a daemon answering, and how long does one round-trip take in-process (no Python
    start-up in the number, just the socket)? Uses the client's own _try_daemon so the
    protocol, token and staleness handling are the real ones."""
    port_file = project_root / ".claude" / ".guard-daemon-port"
    backoff = project_root / ".claude" / ".guard-daemon-start-backoff"
    result = {
        "port_file_present": port_file.is_file(),
        "start_backoff_marker_present": backoff.is_file(),
        "reachable": False,
        "roundtrip_samples_ms": [],
        "connect_failure_samples_ms": [],
    }
    client = _load_client(plugin_root)
    if client is None:
        result["note"] = "guard_daemon_client.py not found or failed to import"
        return result
    for _ in range(tries):
        start = time.monotonic()
        try:
            answer = client._try_daemon(str(project_root), "bash_hook_dispatcher", payload_text)
        except Exception:  # noqa: BLE001
            answer = None
        elapsed = (time.monotonic() - start) * 1000.0
        if answer is None:
            result["connect_failure_samples_ms"].append(round(elapsed, 1))
        else:
            result["roundtrip_samples_ms"].append(round(elapsed, 1))
            result["reachable"] = True
            result["last_exit_code"] = answer[0]
    return result


def _windows_defender_hints() -> list:
    """Read-only registry peeks that need no admin. Absent keys are a fact too."""
    hints = []
    if sys.platform != "win32":
        return hints
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return hints
    probes = (
        (r"SOFTWARE\Microsoft\Windows Defender\Real-Time Protection", "DisableRealtimeMonitoring"),
        (
            r"SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection",
            "DisableRealtimeMonitoring",
        ),
        (r"SOFTWARE\Policies\Microsoft\Windows Defender", "DisableAntiSpyware"),
    )
    for key, name in probes:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                value, _kind = winreg.QueryValueEx(handle, name)
                hints.append(f"HKLM\\{key}\\{name} = {value}")
        except OSError:
            continue
    for key in (
        r"SOFTWARE\Microsoft\Windows Defender\Exclusions\Paths",
        r"SOFTWARE\Policies\Microsoft\Windows Defender\Exclusions\Paths",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                count = winreg.QueryInfoKey(handle)[1]
                hints.append(f"HKLM\\{key}: {count} exclusion path(s) readable")
        except OSError:
            hints.append(f"HKLM\\{key}: not readable without admin, or no exclusions")
    return hints


def av_hints() -> list:
    """Endpoint-security presence that can be read without admin: vendor install directories
    and Defender registry values. Presence, not activity: tagged inferred by the caller."""
    hints = []
    for name, folder in _AV_VENDOR_DIRS:
        if Path(folder).is_dir():
            hints.append(f"{name} install directory present ({folder})")
    hints += _windows_defender_hints()
    return hints


def _is_git_bash(sh_path: Optional[str], probe_output: str) -> Optional[bool]:
    if not sh_path:
        return None
    lowered = sh_path.replace("/", "\\").lower()
    if "\\git\\" in lowered or lowered.endswith("\\git\\bin\\sh.exe"):
        return True
    text = probe_output.upper()
    if "MINGW" in text or "MSYS" in text:
        return True
    return False


def gather_environment(
    plugin_root: Path, project_root: Path, sh_path: Optional[str], interpreter: str, runner=None
) -> list:
    """Every fact the verdict leans on, each tagged observed or inferred."""
    run = runner or subprocess.run
    facts = []

    def fact(name, value, tag, note=""):
        facts.append({"name": name, "value": value, "tag": tag, "note": note})

    fact("os", platform.platform(), "observed")
    if sys.platform == "win32":
        release, version, csd, ptype = platform.win32_ver()
        fact("windows_version", f"{release} {version} {csd} {ptype}".strip(), "observed")
    fact("probe_python", sys.version.split()[0] + " at " + sys.executable, "observed")

    cache = interpreter_cache_path(project_root)
    cached = None
    if cache.is_file():
        try:
            cached = cache.read_text(encoding="utf-8").strip()
        except OSError:
            cached = None
    fact("interpreter_cache_present", cache.is_file(), "observed", str(cache))
    fact("interpreter_cache_value", cached, "observed")
    if cached:
        resolved = (
            shutil.which(cached)
            if not os.path.isabs(cached)
            else (cached if os.path.isfile(cached) else None)
        )
        fact(
            "interpreter_how_resolved",
            "cache hit"
            if resolved
            else "cache names a command that does not resolve; every call re-probes",
            "observed",
            resolved or "",
        )
    else:
        fact(
            "interpreter_how_resolved",
            "no cache; the launcher probes candidates on every call until it can write one",
            "observed",
        )
    fact("interpreter_used_for_layers", interpreter, "observed")

    coldstart_cache = project_root / ".claude" / ".guard-coldstart-ms"
    coldstart_value = None
    if coldstart_cache.is_file():
        try:
            coldstart_value = coldstart_cache.read_text(encoding="utf-8").strip()
        except OSError:
            coldstart_value = None
    fact("coldstart_cache_ms", coldstart_value, "observed", str(coldstart_cache))
    lock_dir = project_root / ".claude" / ".guard-lock"
    fact(
        "lock_dir_present_before_run",
        lock_dir.is_dir(),
        "observed",
        "a leftover lock means a waiter pays the poll budget",
    )

    fact("sh_path", sh_path, "observed")
    probe_output = ""
    if sh_path:
        try:
            proc = run(  # nosec B603 - fixed argv: the resolved sh with builtins only
                [
                    sh_path,
                    "-c",
                    'echo "${MSYSTEM:-}"; echo "${OSTYPE:-}"; echo "${BASH_VERSION:-}"',
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            probe_output = (getattr(proc, "stdout", "") or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            probe_output = ""
    fact(
        "sh_is_git_bash",
        _is_git_bash(sh_path, probe_output),
        "inferred",
        probe_output.replace("\n", " | "),
    )
    fact("CLAUDE_CODE_GIT_BASH_PATH", os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), "observed")
    fact("CLAUDE_PROJECT_DIR", os.environ.get("CLAUDE_PROJECT_DIR"), "observed")
    fact("CLAUDE_PLUGIN_ROOT", os.environ.get("CLAUDE_PLUGIN_ROOT"), "observed")

    pref = daemon_preference(project_root)
    fact("guard_daemon_enabled", pref["enabled"], "observed", pref["source"])
    fact(
        "team_preferences_present",
        pref["prefs_file_present"],
        "observed",
        str(project_root / ".claude" / "team-preferences.json"),
    )

    hints = av_hints()
    fact(
        "av_endpoint_hints",
        hints or ["none readable without admin"],
        "inferred",
        "presence of a product, not proof it scans each spawn; the warm-vs-cold delta is the behavioural signal",
    )
    return facts


# ----------------------------------------------------------------------------- the probe


def _payload(project_root: Path, flavour: str) -> str:
    """A benign PreToolUse payload with a fresh session id, so no session-scoped guard is
    armed and every real guard returns allow. Read of README, or a Bash `true`."""
    if flavour == "Bash":
        tool_input = {"command": "true"}
    else:
        readme = project_root / "README.md"
        tool_input = {"file_path": str(readme if readme.is_file() else project_root / "CLAUDE.md")}
    return json.dumps(
        {
            "session_id": f"probe-{uuid.uuid4().hex}",
            "hook_event_name": "PreToolUse",
            "tool_name": flavour,
            "tool_input": tool_input,
            "cwd": str(project_root),
        }
    )


class Probe:
    """One run. Every subprocess goes through self.runner so tests can replace timing."""

    def __init__(
        self,
        plugin_root: Path,
        project_root: Path,
        runs: int = DEFAULT_RUNS,
        fanout: int = DEFAULT_FANOUT,
        runner=None,
        interpreter: Optional[str] = None,
        sh_path: Optional[str] = None,
        reachability_fn=None,
    ):
        self.plugin_root = plugin_root
        self.project_root = project_root
        self.runs = max(3, runs)
        self.fanout = max(0, fanout)
        self.runner = runner
        self.sh = sh_path if sh_path is not None else resolve_sh()
        self.interpreter = interpreter or self._interpreter_from_cache() or sys.executable
        self.reachability_fn = reachability_fn or daemon_reachability
        self.launcher = plugin_root / ".claude" / "hooks" / "run-guard.sh"
        self.dispatcher = plugin_root / "scripts" / "bash_hook_dispatcher.py"
        self.notes: list = []

    def _interpreter_from_cache(self) -> Optional[str]:
        cache = interpreter_cache_path(self.project_root)
        try:
            value = cache.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not value:
            return None
        if os.path.isabs(value):
            return value if os.path.isfile(value) else None
        return shutil.which(value)

    # -- helpers -------------------------------------------------------------------------

    def _env(self) -> dict:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.project_root)
        env["CLAUDE_PLUGIN_ROOT"] = str(self.plugin_root)
        return env

    def _sh(self, script: str, *args: str) -> tuple:
        return (
            [self.sh, "-c", script, "sh", *args],
            {"env": self._env(), "cwd": str(self.project_root)},
        )

    def _py(self, *args: str) -> tuple:
        return (
            [self.interpreter, "-S", *args],
            {"env": self._env(), "cwd": str(self.project_root)},
        )

    def _launcher(self, flavour: str) -> tuple:
        return (
            [self.sh, str(self.launcher), str(self.dispatcher)],
            {
                "input": _payload(self.project_root, flavour),
                "text": True,
                "env": self._env(),
                "cwd": str(self.project_root),
            },
        )

    def _timed(self, argv_fn, n: int) -> list:
        return measure_repeated(argv_fn, n, runner=self.runner)

    # -- stages --------------------------------------------------------------------------

    def reproduce(self) -> dict:
        """The number the owner sees: the real launcher, the real dispatcher, benign payloads,
        alternating Read and Bash, fresh session id each time."""
        flavours = ["Read" if i % 2 == 0 else "Bash" for i in range(self.runs)]
        samples, codes = [], []
        for flavour in flavours:
            s, c = measure_repeated_rc(lambda f=flavour: self._launcher(f), 1, runner=self.runner)
            samples += s
            codes += c
        by_flavour = {
            "Read": [s for s, f in zip(samples, flavours) if f == "Read"],
            "Bash": [s for s, f in zip(samples, flavours) if f == "Bash"],
        }
        nonzero = [c for c in codes if c not in (0, None)]
        if nonzero:
            self.notes.append(
                f"{len(nonzero)} of {len(codes)} end-to-end calls exited non-zero ({sorted(set(nonzero))}); "
                "a benign payload should exit 0, so a guard is blocking or crashing on this box"
            )
        out = summarise(samples)
        out["exit_codes"] = codes
        out["flavours"] = flavours
        out["by_flavour_p50_ms"] = {k: round(median(v), 1) for k, v in by_flavour.items()}
        out["warm_vs_cold"] = warm_vs_cold(samples)
        return out

    def fanout_burst(self) -> Optional[dict]:
        if self.fanout < 2:
            return None
        samples, total = measure_concurrent(
            lambda: self._launcher("Read"), self.fanout, runner=self.runner
        )
        out = summarise(samples)
        out["concurrency"] = self.fanout
        out["total_wall_ms"] = round(total, 1)
        return out

    def decompose(self, route: str, reach: dict) -> dict:
        """Each layer in isolation, N samples each, in the order a first spawn of each binary
        would happen in a fresh session so the first-sample column keeps its meaning."""
        n = self.runs
        layers: dict = {}
        cache = interpreter_cache_path(self.project_root)
        cache_present = cache.is_file()

        # 1. Python first: its first spawn in this process is the cleanest AV signal.
        layers["python_cold_start"] = self._timed(lambda: self._py("-c", "pass"), n)
        # 2. sh alone.
        layers["sh_startup"] = self._timed(lambda: self._sh(":"), n)
        # 3. Interpreter resolution as the launcher does it on this route.
        if cache_present:
            if route == ROUTE_COLD:
                # cold route: `cat` twice (coldstart cache, interpreter cache) then command -v
                layers["interp_resolution"] = self._timed(
                    lambda: self._sh(
                        'a=$(cat "$1" 2>/dev/null); b=$(cat "$2" 2>/dev/null); command -v "$b" >/dev/null 2>&1',
                        str(self.project_root / ".claude" / ".guard-coldstart-ms"),
                        str(cache),
                    ),
                    n,
                )
            else:
                # daemon fast path: builtin read, then command -v
                layers["interp_resolution"] = self._timed(
                    lambda: self._sh(
                        'IFS= read -r c 2>/dev/null <"$1"; command -v "$c" >/dev/null 2>&1',
                        str(cache),
                    ),
                    n,
                )
        order = "python py python3" if os.environ.get("OS") == "Windows_NT" else "python3 python py"
        layers["interp_resolution_cold"] = self._timed(
            lambda: self._sh(
                'for i in $1; do command -v "$i" >/dev/null 2>&1 && "$i" -c '
                '"import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1 && exit 0; done; exit 0',
                order,
            ),
            max(3, n // 3),
        )
        # 4. The mkdir lock cycle, in a scratch directory so the live lock is never touched.
        with tempfile.TemporaryDirectory(prefix="vsit-probe-lock-") as scratch:
            layers["lock_cycle"] = self._timed(
                lambda: self._sh(
                    'd="$1/lock"; if mkdir "$d" 2>/dev/null; then { date +%s; echo "$$"; } 2>/dev/null >"$d/acquired-at"; fi; rm -rf "$d"',
                    scratch,
                ),
                n,
            )
        # 5. Dispatcher + one guard import, then the whole dispatcher run.
        import_snippet = (
            "import importlib.util; "
            f"spec = importlib.util.spec_from_file_location('d', {str(self.dispatcher)!r}); "
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
            "name, path, _t, _f = m._CHECKS[0]; m._load(name, path)"
        )
        layers["dispatcher_imports_raw"] = self._timed(lambda: self._py("-c", import_snippet), n)
        layers["dispatcher_run_raw"] = self._timed(
            lambda: (
                [self.interpreter, "-S", str(self.dispatcher)],
                {
                    "input": _payload(self.project_root, "Read"),
                    "text": True,
                    "env": self._env(),
                    "cwd": str(self.project_root),
                },
            ),
            n,
        )
        layers["client_import_raw"] = self._timed(
            lambda: self._py("-c", "import json, os, socket, sys, time"), max(3, n // 3)
        )
        layers["daemon_roundtrip"] = list(reach.get("roundtrip_samples_ms") or [])
        layers["connect_failure"] = list(reach.get("connect_failure_samples_ms") or [])
        return layers


# ----------------------------------------------------------------------------- attribution


def route_for(pref_enabled: bool, reachable: bool) -> str:
    if not pref_enabled:
        return ROUTE_COLD
    return ROUTE_DAEMON if reachable else ROUTE_DAEMON_UNREACHABLE


def attribute(route: str, raw: dict, end_to_end_ms: float) -> dict:
    """Turn raw per-layer samples into the layers that actually make up one call on this
    route, in milliseconds, and compare their sum with the measured end-to-end figure.
    Derived layers subtract their baseline and are clamped at zero: a negative difference is
    measurement noise, not a saving."""
    st = {k: steady(v) for k, v in raw.items()}
    py = st.get("python_cold_start", 0.0)
    sh = st.get("sh_startup", 0.0)

    def derived(key: str, base: float) -> float:
        return max(0.0, st.get(key, 0.0) - base)

    imports = derived("dispatcher_imports_raw", py)
    logic = max(0.0, st.get("dispatcher_run_raw", 0.0) - py - imports)
    client_import = derived("client_import_raw", py)
    resolution = (
        derived("interp_resolution", sh)
        if "interp_resolution" in raw
        else derived("interp_resolution_cold", sh)
    )
    resolution_key = "interp_resolution" if "interp_resolution" in raw else "interp_resolution_cold"
    lock = derived("lock_cycle", sh)

    layers: list = []

    def add(key: str, ms: float):
        layers.append({"layer": key, "title": LAYER_TITLES[key], "ms": round(ms, 1)})

    add("sh_startup", sh)
    add(resolution_key, resolution)
    if route == ROUTE_COLD:
        add("lock_cycle", lock)
        add("python_cold_start", py)
        add("dispatcher_imports", imports)
        add("guard_logic", logic)
    elif route == ROUTE_DAEMON:
        add("python_cold_start", py)
        add("client_import", client_import)
        add("daemon_roundtrip", st.get("daemon_roundtrip", 0.0))
    else:  # enabled, nobody answering: client start, failed connect, then a full cold start
        add("python_cold_start", py)
        add("client_import", client_import)
        add("connect_failure", st.get("connect_failure", 0.0))
        add("python_cold_start_fallback", py)
        add("dispatcher_imports", imports)
        add("guard_logic", logic)

    attributed = sum(item["ms"] for item in layers)
    residual = end_to_end_ms - attributed
    add("unattributed", max(0.0, residual))
    # What the SAME call would cost on the other route, from the same samples: the daemon's
    # benefit (or the cost of losing it) stated in this box's own milliseconds.
    alternatives = {
        "daemon_route_ms": round(
            sh + resolution + py + client_import + st.get("daemon_roundtrip", 0.0), 1
        ),
        "cold_route_ms": round(sh + resolution + lock + py + imports + logic, 1),
        "daemon_unreachable_route_ms": round(
            sh
            + resolution
            + py
            + client_import
            + st.get("connect_failure", 0.0)
            + py
            + imports
            + logic,
            1,
        ),
    }
    total = end_to_end_ms if end_to_end_ms > 0 else attributed
    for item in layers:
        item["share_pct"] = round(100.0 * item["ms"] / total, 1) if total > 0 else 0.0
    return {
        "route": route,
        "end_to_end_ms": round(end_to_end_ms, 1),
        "attributed_ms": round(attributed, 1),
        "residual_ms": round(residual, 1),
        "residual_pct": round(100.0 * residual / total, 1) if total > 0 else 0.0,
        "sums_within_tolerance": abs(residual) <= max(0.25 * total, 50.0),
        "layers": layers,
        "alternatives": alternatives,
    }


def _remediation(layer: str, route: str, facts: dict, reach: dict) -> str:
    git_bash = facts.get("sh_is_git_bash") is True
    win = sys.platform == "win32" or facts.get("os", "").lower().startswith("windows")
    bash_path_set = bool(facts.get("CLAUDE_CODE_GIT_BASH_PATH"))
    if layer == "sh_startup":
        if git_bash or win:
            text = (
                "Git Bash spawn cost. Run the Git Bash speed fix (install helper, Advanced menu #9: "
                "core.fscache plus AV exclusions for the Git install and the project)."
            )
            if not bash_path_set:
                text += " Set CLAUDE_CODE_GIT_BASH_PATH to Git's bin\\sh.exe so Claude Code does not walk a stale PATH to find it."
            return text
        return "Shell spawn is slow on this host; check what the shell sources at start-up and whether the binary is AV-scanned on each launch."
    if layer in ("python_cold_start", "python_cold_start_fallback"):
        text = "Python start-up per call. Add the interpreter directory to the AV exclusions (Advanced menu #9 covers Git; extend it to the Python install)."
        if route == ROUTE_COLD:
            text += " Enabling guard_daemon does not remove this start (the client is still a fresh interpreter) but it removes the imports and guard work behind it."
        if layer == "python_cold_start_fallback":
            text = (
                "A SECOND Python start on every call because the daemon is enabled but nobody answers. "
                + text
                + " Fix the daemon first (Diagnostics option 7: why won't the guard daemon start)."
            )
        return text
    if layer in ("dispatcher_imports", "guard_logic"):
        if route == ROUTE_COLD:
            return 'Guard imports and logic run in a fresh process each call. Enable guard_daemon (team-preferences.json "guard_daemon": true, or remove an explicit false) so this moves into one persistent process.'
        return "This work should be in the daemon, not the client. The daemon is enabled but unreachable: run Diagnostics option 7 (why won't the guard daemon start)."
    if layer == "lock_cycle":
        return "The fan-out lock (mkdir, date, echo, rm as separate spawns). The daemon fast path skips it entirely once the interpreter cache exists; enable guard_daemon."
    if layer in ("interp_resolution", "interp_resolution_cold"):
        if not facts.get("interpreter_cache_present"):
            return "No interpreter cache, so every call re-executes interpreter candidates. Check that .claude/ (or VSIT/local/) is writable; the install helper writes the cache during configure."
        return "Cache read plus command -v. If the cached value is a bare name rather than an absolute path, re-run configure so the absolute path is cached and PATH is not walked per call."
    if layer == "daemon_roundtrip":
        return "Loopback round-trip to the daemon. If this is large the daemon is busy or the guard work itself is slow; run Diagnostics option 7 and check the daemon's own log."
    if layer == "connect_failure":
        return "The client waits on a connect that never answers. A firewall dropping loopback, or a stale port file. Diagnostics option 7."
    if layer == "client_import":
        return (
            "The client's own stdlib imports (json, socket, and enum behind socket), read from disk on every "
            "call. A fixed cost; when it rivals the Python start itself the interpreter's library files are "
            "being scanned on read, which the AV exclusion for the Python install (extend Advanced menu #9) removes."
        )
    if layer == "unattributed":
        text = "Cost not explained by any single layer: process creation of the launcher itself, endpoint-security scanning of each new process, scheduling."
        if reach.get("start_backoff_marker_present") or route == ROUTE_DAEMON_UNREACHABLE:
            text += " On this route it also holds the detached daemon spawn attempt the client makes on every call."
        text += " Compare the warm-vs-cold column: a flat series with a large residual points at per-process scanning, which only AV exclusions or fewer processes (the daemon) reduce."
        return text
    return ""


def verdict(attribution: dict, facts: list, reach: dict, e2e_first_ms: float, wvc: dict) -> list:
    """Ranked root causes: every layer that carries at least 5 percent of the call, biggest
    first, with its fix. Environment-driven lines (daemon enabled but unreachable, cache
    missing) are added on top because they explain WHY a layer is on the path at all."""
    fact_map = {f["name"]: f["value"] for f in facts}
    route = attribution["route"]
    ranked = sorted(attribution["layers"], key=lambda item: item["ms"], reverse=True)
    lines = []
    for item in ranked:
        if item["share_pct"] < 5.0 and item["ms"] < 50:
            continue
        lines.append(
            {
                "layer": item["layer"],
                "title": item["title"],
                "ms": item["ms"],
                "share_pct": item["share_pct"],
                "remediation": _remediation(item["layer"], route, fact_map, reach),
            }
        )
    if route == ROUTE_DAEMON_UNREACHABLE:
        lines.insert(
            0,
            {
                "layer": "route",
                "title": "guard_daemon is enabled but no daemon answers",
                "ms": attribution["end_to_end_ms"],
                "share_pct": 100.0,
                "remediation": (
                    "Every call pays the client start, a failed connect, a detached daemon spawn attempt and a full cold-start "
                    "fallback. Run Diagnostics option 7 (why won't the guard daemon start) and fix that first; the rest of "
                    "this list is what remains once it is up."
                ),
            },
        )
    if route == ROUTE_COLD and fact_map.get("guard_daemon_enabled") is False:
        lines.append(
            {
                "layer": "route",
                "title": "guard_daemon is off",
                "ms": 0.0,
                "share_pct": 0.0,
                "remediation": 'Cold start on every call by configuration. Set "guard_daemon": true in .claude/team-preferences.json (or remove the false) to route through the persistent daemon.',
            }
        )
    if wvc.get("verdict") == "first-spawn-penalty":
        lines.append(
            {
                "layer": "warm_vs_cold",
                "title": "first spawn is much slower than steady state",
                "ms": wvc.get("first_ms") or 0.0,
                "share_pct": 0.0,
                "remediation": "Consistent with a first-seen scan by endpoint security that is then cached. A session pays it once per binary; AV exclusions (Advanced menu #9) remove it.",
            }
        )
    for rank, line in enumerate(lines, 1):
        line["rank"] = rank
    return lines


# ----------------------------------------------------------------------------- reporting


def _fmt_ms(value) -> str:
    return "n/a" if value is None else f"{value:.0f}ms"


def render_console(report: dict) -> str:
    out = []
    rep = report["reproduce"]
    out.append(f"\nvirt-surv hook latency probe   ({report['plugin_root']})")
    out.append(
        f"project: {report['project_root']}   runs: {rep['n']}   generated: {report['generated_at']}\n"
    )

    out.append(
        "1. reproduce  (real launcher, real dispatcher, benign Read and Bash payloads, fresh session id)"
    )
    out.append(
        f"   end to end   p50 {_fmt_ms(rep['p50_ms'])}   p90 {_fmt_ms(rep['p90_ms'])}   max {_fmt_ms(rep['max_ms'])}"
        f"   first {_fmt_ms(rep['first_ms'])}   failed {rep['failed']}"
    )
    out.append(
        f"   per flavour  Read p50 {_fmt_ms(rep['by_flavour_p50_ms'].get('Read'))}   Bash p50 {_fmt_ms(rep['by_flavour_p50_ms'].get('Bash'))}"
    )
    codes = rep.get("exit_codes") or []
    out.append(
        f"   exit codes   {sorted(set(c for c in codes if c is not None)) or 'none'}  (0 expected)"
    )
    fan = report.get("fanout")
    if fan:
        out.append(
            f"   fan-out x{fan['concurrency']}  per call p50 {_fmt_ms(fan['p50_ms'])}   max {_fmt_ms(fan['max_ms'])}"
            f"   whole burst {_fmt_ms(fan['total_wall_ms'])}"
        )

    out.append("\n2. environment  (observed = read from this box; inferred = a reading of it)")
    for f in report["environment"]:
        value = f["value"]
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        note = f"   {f['note']}" if f.get("note") else ""
        out.append(f"   {f['tag']:<8} {f['name']:<32} {value}{note}")
    reach = report["daemon"]
    out.append(
        f"   observed daemon route                     {report['attribution']['route']}"
        f"   (port file {'present' if reach.get('port_file_present') else 'absent'}, "
        f"{'answering' if reach.get('reachable') else 'not answering'}, "
        f"start-backoff marker {'present' if reach.get('start_backoff_marker_present') else 'absent'})"
    )

    att = report["attribution"]
    out.append(
        f"\n3. decompose  (steady-state ms per layer on the '{att['route']}' route; first vs steady exposes a first-spawn scan)"
    )
    raw = report["layers_raw"]
    for item in att["layers"]:
        key = item["layer"]
        src = {
            "dispatcher_imports": "dispatcher_imports_raw",
            "guard_logic": "dispatcher_run_raw",
            "client_import": "client_import_raw",
            "python_cold_start_fallback": "python_cold_start",
        }.get(key, key)
        wvc = raw.get(src, {}).get("warm_vs_cold", {}) if isinstance(raw.get(src), dict) else {}
        first = wvc.get("first_ms")
        col = (
            f"first {_fmt_ms(first):>7}  steady {_fmt_ms(wvc.get('steady_ms')):>7}"
            if first is not None
            else " " * 29
        )
        out.append(f"   {item['ms']:>8.0f}ms  {item['share_pct']:>5.1f}%  {col}  {item['title']}")
    out.append(
        f"   {'sum of layers':>10} {att['attributed_ms']:.0f}ms vs end to end {att['end_to_end_ms']:.0f}ms; "
        f"residual {att['residual_ms']:.0f}ms ({att['residual_pct']:.0f}%)"
        f"{'' if att['sums_within_tolerance'] else '  <- layers do not add up; see unattributed'}"
    )
    alt = att.get("alternatives") or {}
    if alt:
        out.append(
            f"   the same call by route (layers only, residual excluded): daemon {alt['daemon_route_ms']:.0f}ms, "
            f"cold start {alt['cold_route_ms']:.0f}ms, daemon enabled but unreachable {alt['daemon_unreachable_route_ms']:.0f}ms"
        )
    extra = raw.get("interp_resolution_cold", {})
    if extra:
        out.append(
            f"   for reference: interpreter resolution with NO cache would cost {extra.get('steady_ms', 0):.0f}ms per call "
            "(executes each candidate); paid only while the cache is missing or unwritable"
        )

    out.append(
        "\n4. verdict  (ranked; each line names the layer, its share, and the fix that exists)"
    )
    for line in report["verdict"]:
        share = f"{line['share_pct']:.0f}%" if line["share_pct"] else "  "
        out.append(f"   {line['rank']}. {line['title']}  [{line['ms']:.0f}ms, {share}]")
        out.append(f"      fix: {line['remediation']}")
    for note in report.get("notes", []):
        out.append(f"   note: {note}")
    return "\n".join(out)


def build_report(probe: Probe) -> dict:
    payload_text = _payload(probe.project_root, "Read")
    pref = daemon_preference(probe.project_root)
    # Warm the path once so the interpreter cache exists and a first-call daemon start is
    # not counted as steady state; the warm call's own time is kept as a fact.
    warm_ms = None
    if probe.sh and probe.launcher.is_file() and probe.dispatcher.is_file():
        warm = measure_repeated(lambda: probe._launcher("Read"), 1, runner=probe.runner)
        warm_ms = warm[0]
    reach = probe.reachability_fn(probe.plugin_root, probe.project_root, payload_text)
    route = route_for(pref["enabled"], reach.get("reachable", False))

    rep = probe.reproduce()
    fan = probe.fanout_burst()
    raw = probe.decompose(route, reach)
    facts = gather_environment(
        probe.plugin_root, probe.project_root, probe.sh, probe.interpreter, runner=probe.runner
    )
    facts.append(
        {
            "name": "warm_up_call_ms",
            "value": None if warm_ms is None else round(warm_ms, 1),
            "tag": "observed",
            "note": "the very first launcher call of this probe",
        }
    )
    att = attribute(route, raw, rep["steady_ms"])
    lines = verdict(att, facts, reach, rep["first_ms"], rep["warm_vs_cold"])
    layers_raw = {k: summarise(v) for k, v in raw.items()}
    for k, v in raw.items():
        layers_raw[k]["warm_vs_cold"] = warm_vs_cold(v)
    return {
        "probe_version": 1,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugin_root": str(probe.plugin_root),
        "project_root": str(probe.project_root),
        "reproduce": rep,
        "fanout": fan,
        "environment": facts,
        "daemon": reach,
        "layers_raw": layers_raw,
        "attribution": att,
        "verdict": lines,
        "notes": probe.notes,
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"end-to-end and per-layer samples (default {DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--fanout",
        type=int,
        default=DEFAULT_FANOUT,
        help=f"concurrent launcher calls in one burst, 0 to skip (default {DEFAULT_FANOUT})",
    )
    parser.add_argument(
        "--json", metavar="FILE", help="also write the full machine-readable report here"
    )
    parser.add_argument(
        "--plugin-root",
        default=str(REPO),
        help="where run-guard.sh and scripts/ live (default: this checkout)",
    )
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
        help="the project whose hook state to measure (default: CLAUDE_PROJECT_DIR or cwd)",
    )
    parser.add_argument(
        "--quiet-json", action="store_true", help="do not echo the JSON to the console"
    )
    args = parser.parse_args(argv)

    plugin_root = Path(args.plugin_root).resolve()
    project_root = Path(args.project_dir).resolve()
    probe = Probe(plugin_root, project_root, runs=args.runs, fanout=args.fanout)
    if not probe.sh:
        print(
            "no POSIX sh found (PATH, CLAUDE_CODE_GIT_BASH_PATH, Git for Windows locations); the launcher cannot be timed here",
            file=sys.stderr,
        )
        return 2
    if not probe.launcher.is_file() or not probe.dispatcher.is_file():
        print(
            f"launcher or dispatcher missing under {plugin_root}; pass --plugin-root",
            file=sys.stderr,
        )
        return 2

    report = build_report(probe)
    print(render_console(report))
    text = json.dumps(report, indent=2, default=str)
    if args.json:
        try:
            Path(args.json).write_text(text + "\n", encoding="utf-8")
            print(f"\nJSON written to {args.json}")
        except OSError as exc:
            print(f"\ncould not write {args.json}: {exc}", file=sys.stderr)
    if not args.quiet_json:
        print("\n===== hook_latency_probe JSON (copy this whole block off the box) =====")
        print(text)
        print("===== end JSON =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
