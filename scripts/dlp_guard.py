#!/usr/bin/env python3
"""Hard-reject content containing blocked keywords (employer, colleague names, internal hosts).

Nothing identifying is committed - not the terms, not a hash of them. This repository
is public and the terms are the very words that must not appear in it.

An earlier draft committed SHA-256 digests so a fresh clone inherited the list. That
was wrong: a digest of a short unsalted word is a confirmable fingerprint, so a
stranger who merely GUESSES a blocked term can prove the guess with one sha256 call.
Publishing that is an oracle for exactly the words being suppressed. Salting only
moves the problem - the salt then has to ship somewhere too.

So this module carries mechanism only. Both data files are gitignored:
  .dlp-keywords.local   the terms, plaintext, never leaves the machine
  .dlp-blocklist        their digests, generated locally by --rehash
CI gets the digests from the DLP_BLOCKLIST repo secret via $DLP_BLOCKLIST. Digests
rather than plaintext even there, so a mistake in the workflow cannot echo a term.

Matching is per token: text is split on non-alphanumeric runs and lowercased, so
`ACME_KEY`, `acme.com`, `a@acme.co.uk` and `C:\\Users\\jsmith` all reduce to a bare
token that matches. A term buried inside one alphanumeric run (`xacmex`) does not
match - that is the deliberate trade for a hashed list, which cannot do substring
search.

The examples above are deliberately placeholders. The first draft of this file used
real blocked terms to illustrate the same four shapes, which put them in plaintext in
a public repo - precisely what the module exists to prevent. Documentation about a
secret must not carry the secret; keep every example here fictional.

A matched term is NEVER printed: CI logs on a public repo are public, and echoing
the term would leak it exactly where it must not appear. Reports carry the file,
the line number and a short hash prefix only.

Usage:
    dlp_guard.py FILE...     scan the given files (how pre-commit invokes it)
    dlp_guard.py --all       scan every tracked + addable file (CI)
    dlp_guard.py --rehash    regenerate .dlp-blocklist from .dlp-keywords.local
    dlp_guard.py --check TERM  report whether TERM is already blocked (prints no terms)

Exit status: 0 clean, 1 blocked content found, 2 misconfiguration.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess  # nosec B404 - fixed `git ls-files` argv, no shell
import sys
from pathlib import Path

BLOCKLIST = ".dlp-blocklist"
KEYWORDS_LOCAL = ".dlp-keywords.local"

# Split on anything that is not a letter or digit, so punctuation, path separators,
# `@` and `_` all act as token boundaries.
TOKEN_RE = re.compile(r"[^0-9a-z]+")

# Skip binaries and anything whose contents we cannot meaningfully tokenise.
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".xz",
    ".zst",
    ".tar",
    ".whl",
    ".pyc",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp4",
    ".mov",
    ".mp3",
    ".parquet",
}

# The blocklist itself is hashes; scanning it would be pointless. The local keyword
# file is plaintext by design and gitignored - never scan or report on it.
SKIP_PATHS = {BLOCKLIST, KEYWORDS_LOCAL}


def repo_root() -> Path:
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def digest(term: str) -> str:
    return hashlib.sha256(term.strip().lower().encode("utf-8")).hexdigest()


def blocklist_path(root: Path) -> Path:
    """Where to read digests from: $DLP_BLOCKLIST if set, else the gitignored local file.

    CI has no local file - the repo deliberately carries neither the terms nor their
    digests - so the workflow materialises the DLP_BLOCKLIST secret to a temp file and
    points this at it."""
    env = os.environ.get("DLP_BLOCKLIST")
    return Path(env) if env else root / BLOCKLIST


def load_blocklist(root: Path) -> set:
    path = blocklist_path(root)
    if not path.is_file():
        return set()
    hashes = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if len(line) == 64 and all(c in "0123456789abcdef" for c in line):
            hashes.add(line)
    return hashes


def tokens(text: str):
    for tok in TOKEN_RE.split(text.lower()):
        if tok:
            yield tok


def scan_file(path: Path, blocked: set, root: Path) -> list:
    """(line_number, hash_prefix) for each blocked token found. Never returns the term."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    if rel in SKIP_PATHS or path.suffix.lower() in SKIP_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return []
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for tok in tokens(line):
            h = digest(tok)
            if h in blocked:
                hits.append((lineno, h[:8]))
    return hits


def scannable_files(root: Path) -> list:
    """Tracked files, plus untracked ones git would let you add (ignored files excluded).

    Tracked-only was the first cut, and it hid a real leak: this module's own docstring
    carried blocked terms while the file was still untracked, so `--all` reported the
    repo clean and the terms were caught later by the staged-file path instead. A file
    that is one `git add` from being public is in scope for an audit. Ignored files stay
    out - .dlp-keywords.local is plaintext by design and never leaves the machine.
    """
    paths = []
    for extra in (["-z"], ["-z", "--others", "--exclude-standard"]):
        try:
            out = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
                ["git", "-C", str(root), "ls-files", *extra],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            paths += [root / p for p in out.stdout.split("\0") if p]
    return paths


def rehash(root: Path) -> int:
    src = root / KEYWORDS_LOCAL
    if not src.is_file():
        print(
            f"error: {KEYWORDS_LOCAL} not found - create it with one term per line.",
            file=sys.stderr,
        )
        return 2
    terms = []
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            terms.append(line.lower())
    if not terms:
        print(f"error: {KEYWORDS_LOCAL} has no terms.", file=sys.stderr)
        return 2
    body = [
        "# Blocked-term digests (SHA-256 of the lowercased term). Generated - do not edit.",
        f"# Regenerate:  python3 scripts/{Path(__file__).name} --rehash",
        f"# Plaintext master list: {KEYWORDS_LOCAL} (gitignored, never committed).",
        "",
    ]
    body += sorted({digest(t) for t in terms})
    (root / BLOCKLIST).write_text("\n".join(body) + "\n", encoding="utf-8")
    # Deliberately reports only a count - printing the terms would defeat the point.
    print(f"wrote {BLOCKLIST}: {len(set(terms))} term(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("files", nargs="*", help="files to scan")
    ap.add_argument("--all", action="store_true", help="scan every tracked and addable file")
    ap.add_argument(
        "--rehash", action="store_true", help="regenerate the blocklist from the local keyword file"
    )
    ap.add_argument(
        "--check", metavar="TERM", help="report whether TERM is blocked (prints no terms)"
    )
    args = ap.parse_args()

    root = repo_root()

    if args.rehash:
        return rehash(root)

    blocked = load_blocklist(root)

    if args.check:
        print("blocked" if digest(args.check) in blocked else "not blocked")
        return 0

    if not blocked:
        # No list yet is a no-op, not a failure: the repo must stay clonable and
        # committable before anyone has configured their local keyword file.
        return 0

    targets = scannable_files(root) if args.all else [Path(f) for f in args.files]
    findings = []
    for f in targets:
        if f.is_file():
            for lineno, prefix in scan_file(f, blocked, root):
                try:
                    rel = f.relative_to(root).as_posix()
                except ValueError:
                    rel = f.as_posix()
                findings.append((rel, lineno, prefix))

    if not findings:
        return 0

    print("BLOCKED: content matches a term on the DLP blocklist.", file=sys.stderr)
    print(
        "The term is not shown here on purpose - this output reaches public CI logs.",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for rel, lineno, prefix in findings[:50]:
        print(f"  {rel}:{lineno}  (term digest {prefix}...)", file=sys.stderr)
    if len(findings) > 50:
        print(f"  ... and {len(findings) - 50} more", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Identify it locally with:  grep -nif {KEYWORDS_LOCAL} <file>", file=sys.stderr)
    print(
        "Remove the term, then commit again. Deliberate bypass: git commit --no-verify",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
