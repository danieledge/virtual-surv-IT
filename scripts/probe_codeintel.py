#!/usr/bin/env python3
"""Can this machine use the well-trodden code-intelligence tools? Run it and read the verdict.

WHY THIS EXISTS. The choice between "use tree-sitter / aider" and "keep an in-house floor"
turns on one factual question that only the target machine can answer: does a compiled
extension actually LOAD and PARSE here? Not "does pip succeed" - a wheel can install fine
and then fail to load under AppLocker, because a .pyd is a DLL. So this probes the thing
that matters, in that order.

SAFE BY DEFAULT: probes only, installs nothing, touches no project files, no network.
Add --try-install to attempt an isolated install into a throwaway temp directory (still
never touches your Python installation or any project). Nothing is left behind.

    python -m scripts.probe_codeintel                 # probe only
    python -m scripts.probe_codeintel --try-install   # also test whether it COULD work

On a corporate Windows box, from the plugin clone, with the interpreter spelled out
because PATH there is not reliable:

    C:\\Python313\\python.exe -m scripts.probe_codeintel

Delivered through the repo rather than as a file copy, because the machines that most
need answering are the ones you cannot install or copy onto - a `git pull` is the one
channel that already works there.
"""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import tempfile

CANDIDATES = [
    ("tree_sitter", "the parser core - COMPILED, the one that matters"),
    ("tree_sitter_language_pack", "grammars for ~100 languages, abi3"),
    ("tree_sitter_python", "single grammar, abi3"),
    ("grep_ast", "aider's tag layer, pure Python"),
    ("networkx", "aider's PageRank, pure Python"),
    ("diskcache", "aider's tag cache, pure Python"),
    ("aider", "the whole tool"),
]

BINARIES = [
    ("ctags", ["--version"], "universal-ctags - already a soft probe tier"),
    ("sg", ["--version"], "ast-grep - MIT single binary, structural search"),
    ("ast-grep", ["--version"], "ast-grep under its other name"),
    ("rg", ["--version"], "ripgrep"),
    ("git", ["--version"], "git"),
]


def line(text=""):
    print(text, flush=True)


def probe_imports() -> dict:
    found = {}
    for name, why in CANDIDATES:
        try:
            spec = importlib.util.find_spec(name)
        except Exception:
            spec = None
        found[name] = bool(spec)
        line(f"  {'YES' if spec else ' - '}  {name:28} {why}")
    return found


def probe_binaries() -> dict:
    found = {}
    for name, args, why in BINARIES:
        path = shutil.which(name)
        found[name] = bool(path)
        detail = ""
        if path:
            try:
                out = (
                    subprocess.run([path, *args], capture_output=True, text=True, timeout=15)
                    .stdout.strip()
                    .splitlines()
                )
                detail = f"  ({out[0][:50]})" if out else ""
            except Exception:
                detail = "  (found, but would not run)"
        line(f"  {'YES' if path else ' - '}  {name:28} {why}{detail}")
    return found


def can_it_actually_parse() -> bool:
    """THE decisive test. Importing is not enough - a compiled extension must load its DLL
    and produce a tree. This is what AppLocker or a policy-blocked DLL would stop."""
    try:
        import tree_sitter  # noqa: F401
    except Exception as exc:
        line(f"  tree_sitter does not import here: {type(exc).__name__}: {exc}")
        return False
    try:
        from tree_sitter_language_pack import get_parser

        parser = get_parser("python")
    except Exception:
        try:
            import tree_sitter_python
            from tree_sitter import Language, Parser

            parser = Parser(Language(tree_sitter_python.language()))
        except Exception as exc:
            line(f"  imports, but NO usable grammar: {type(exc).__name__}: {exc}")
            return False
    try:
        tree = parser.parse(b"def hello(name):\n    return name\n")
        root = tree.root_node
        ok = root.type == "module" and root.child_count > 0
        line(
            f"  parsed a sample: root={root.type!r}, children={root.child_count} -> "
            f"{'WORKS' if ok else 'unexpected shape'}"
        )
        return ok
    except Exception as exc:
        line(f"  grammar loaded but PARSE FAILED: {type(exc).__name__}: {exc}")
        return False


def try_install() -> None:
    """Isolated, throwaway, and explicitly asked for. Never touches your Python install."""
    target = tempfile.mkdtemp(prefix="codeintel-probe-")
    line(f"  installing into a temp dir (removed afterwards): {target}")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--target",
        target,
        "tree-sitter",
        "tree-sitter-language-pack",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as exc:
        line(f"  pip could not even start: {type(exc).__name__}: {exc}")
        shutil.rmtree(target, ignore_errors=True)
        return
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        line("  pip FAILED - this is the answer for this machine:")
        for row in tail:
            line(f"      {row[:110]}")
        shutil.rmtree(target, ignore_errors=True)
        return
    line("  pip succeeded. Now the real question - does the compiled extension LOAD?")
    sys.path.insert(0, target)
    for stale in [m for m in sys.modules if m.startswith("tree_sitter")]:
        del sys.modules[stale]
    can_it_actually_parse()
    shutil.rmtree(target, ignore_errors=True)
    line("  temp dir removed.")


def main() -> int:
    line("=" * 72)
    line("Code-intelligence probe")
    line("=" * 72)
    line(f"  python     {sys.version.split()[0]}  ({sys.executable})")
    line(f"  platform   {platform.platform()}")
    line(f"  machine    {platform.machine()}")
    line("")
    line("Python packages already importable here:")
    imports = probe_imports()
    line("")
    line("Binaries on PATH:")
    binaries = probe_binaries()
    line("")
    line("Does tree-sitter actually parse (not merely import)?")
    parses = can_it_actually_parse() if imports.get("tree_sitter") else False
    if not imports.get("tree_sitter"):
        line("  skipped - tree_sitter is not installed here")
    if "--try-install" in sys.argv:
        line("")
        line("Attempting an isolated install (--try-install was passed):")
        try_install()
    line("")
    line("=" * 72)
    line("VERDICT")
    if parses:
        line("  tree-sitter WORKS on this machine. Implementing the stubbed tier would")
        line("  use the mature parser here, with no install step for you.")
    elif imports.get("tree_sitter"):
        line("  tree-sitter is installed but does NOT work here - the compiled extension")
        line("  failed to load or parse. This is the AppLocker/DLL-policy case, and it is")
        line("  exactly why an in-house floor exists.")
    else:
        line("  tree-sitter is NOT available here. Re-run with --try-install to find out")
        line("  whether it COULD be, which is the question that decides the design.")
    if binaries.get("sg") or binaries.get("ast-grep"):
        line("  ast-grep IS present - a single MIT binary, no Python coupling. On this")
        line("  evidence it is the cheaper tier to wire up first.")
    if binaries.get("ctags"):
        line("  ctags is present - the existing ctags tier is live on this machine.")
    line("=" * 72)
    print(json.dumps({"imports": imports, "binaries": binaries, "parses": parses}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
