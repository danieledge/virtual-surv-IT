#!/usr/bin/env python3
"""Pin the release binaries the installer downloads: one version and one SHA-256 per asset.

WHY (2026-09-13 framework review, step 7.1). install_helper.py fetched osv-scanner, gitleaks,
shfmt, shellcheck and opengrep from GitHub's `/releases/latest` with no version pin and no
digest check, so two installs a week apart could differ silently and nothing verified the
bytes that landed in ~/.local/bin. A bank's security review stops on that. Now the installer
reads `config/release-tools.json` - a tracked table of {tool: {version, assets: {name:
sha256}}} - downloads exactly the pinned asset by tag, and refuses any file whose digest does
not match. This script is how the table is (re)generated.

HUMAN-RUN, AT RELEASE TIME, WITH NETWORK. It reads GitHub's release API, which publishes a
`digest` (sha256) per asset, so nothing is downloaded here: the digests are the publisher's
own. Bump a tool by running this and committing the table; pin a specific tag with
`--tag gitleaks=v8.30.1`. It is not part of the team's runtime tooling, so it is deliberately
absent from the execution gate's allow-list.

    python scripts/pin_release_tools.py            # every tool at its latest release
    python scripts/pin_release_tools.py --tag shfmt=v3.14.1 --check

`--check` writes nothing and exits 1 when the committed table differs from what the API
says, which is the shape a scheduled CI job can use to notice a new upstream release.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import install_helper as ih  # noqa: E402 - path fix above

_API = "https://api.github.com/repos/{repo}/releases/{which}"
# The machines the installer is expected to meet. An asset the table cannot name for one of
# these is reported, not hidden: a 404 on the user's laptop is worse than a line here.
_MACHINES = (
    ("linux", "x86_64"),
    ("linux", "aarch64"),
    ("darwin", "x86_64"),
    ("darwin", "arm64"),
    ("win32", "AMD64"),
)


def fetch_release(repo: str, tag: str | None = None, timeout: int = 30) -> dict:
    """The release JSON for `repo` - the latest one, or the one at `tag`."""
    url = _API.format(repo=repo, which=f"tags/{tag}" if tag else "latest")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "virt-surv-it-pin"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed https literal
        return json.loads(response.read().decode("utf-8"))


def pin_entry(spec: "ih.ReleaseTool", release: dict) -> dict:
    """One table row from one release: version, tag, every asset's sha256, and the asset names
    this installer would ask for on the expected machines that the release does not carry."""
    tag = str(release.get("tag_name") or "")
    version = tag[1:] if tag.startswith("v") else tag
    assets: dict[str, str] = {}
    for asset in release.get("assets") or []:
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:") and asset.get("name"):
            assets[asset["name"]] = digest.split(":", 1)[1]
    unpublished = []
    for platform_name, machine in _MACHINES:
        plat, arch = ih._release_platform_arch(platform_name, machine)
        name = spec.asset(plat, arch, version) if plat else ""
        if name and name not in assets:
            unpublished.append(name)
    return {"version": version, "tag": tag, "assets": assets, "unpublished": unpublished}


def build_table(tags: dict[str, str]) -> dict:
    tools = {}
    for name, spec in ih._RELEASE_TOOLS.items():
        tools[name] = pin_entry(spec, fetch_release(spec.repo, tags.get(name)))
    return {
        "generated": _dt.date.today().isoformat(),
        "source": "GitHub release API asset digests (publisher-reported sha256)",
        "tools": tools,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", action="append", default=[], help="tool=vX.Y.Z, repeatable")
    parser.add_argument("--out", type=Path, default=ih._RELEASE_PINS_PATH)
    parser.add_argument(
        "--check", action="store_true", help="compare, write nothing, exit 1 on drift"
    )
    args = parser.parse_args(argv)
    tags = dict(item.split("=", 1) for item in args.tag)
    table = build_table(tags)
    for name, row in table["tools"].items():
        print(f"{name}: {row['tag']} ({len(row['assets'])} assets)")
        for missing in row["unpublished"]:
            print(f"  ! no published asset named {missing}")
    if args.check:
        try:
            current = json.loads(args.out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        drift = [
            n
            for n, row in table["tools"].items()
            if (current.get("tools") or {}).get(n, {}).get("version") != row["version"]
        ]
        print("drift: " + (", ".join(drift) if drift else "none"))
        return 1 if drift else 0
    args.out.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
