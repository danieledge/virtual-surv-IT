#!/usr/bin/env python3
"""Generate prototypes/textual/settings_data.py from the real launcher.

The settings list, its grouping and its help text are transcribed from nothing — they
are read out of `scripts/virt_team_launcher.py` (`_SETTING_GROUPS`, `_SETTING_HELP`)
so the screen cannot drift from the thing it configures. Re-run after either changes.

    tools/gen_settings.py [--repo PATH]
"""

from __future__ import annotations

import argparse
import ast
import re
import pathlib
import pprint

DEFAULT_REPO = str(pathlib.Path(__file__).resolve().parent.parent)

# Row key -> the label the launcher renders. Two labels are module constants rather
# than literals, so they are resolved here.
CONST_LABELS = {"_ENV_ROW_LABEL": "env tuning", "_JIRA_ROW_LABEL": "jira"}

# Row key -> label, for the keys named in _SETTING_GROUPS.
KEY_TO_LABEL = {
    "extra_formats": "docx export",
    "regulatory_citations": "regulatory citations",
    "evidence_room": "evidence room at close",
    "standards_critique": "standards critique",
    "qa_depth": "qa depth",
    "large_context_review_split": "large-context review split",
    "parallel_dispatch_via_workflow": "parallel dispatch (Workflow)",
    "autonomous_mode": "autonomous mode offered",
    "autonomous_default": "start work unattended",
    "new_window": "open the session in a new window",
    "map_skeleton": "codebase-map skeleton",
    "document_map": "document map",
    "data_profiling": "data profiling tools",
    "jira": "jira",
    "integrations.jira.mirror": "jira mirror",
    "probe_cache": "probe pre-cache at go",
    "guard_daemon": "guard daemon",
    "env_tuning": "env tuning",
}

# Settings that cannot work unless requirements-dev.txt was installed. The installer
# offers that as "Document output"; without it these are switches onto nothing.
NEEDS = {
    "docx export": "needs python-docx — the installer's 'Document output' option",
}

# The two rows that are not booleans, with the values the launcher offers.
CHOICES = {
    "qa depth": ("auto", "quick", "deep"),
    "jira mirror": ("close-only", "live"),
}

DEFAULTS_ON = {
    "docx export": False, "regulatory citations": True, "evidence room at close": True,
    "standards critique": False, "large-context review split": True,
    "parallel dispatch (Workflow)": False, "autonomous mode offered": True,
    "start work unattended": False, "open the session in a new window": False,
    "codebase-map skeleton": True, "document map": False, "data profiling tools": True,
    "jira": False, "probe pre-cache at go": True, "guard daemon": True,
    "env tuning": True,
}


def literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return ast.unparse(node)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    a = ap.parse_args()

    src = pathlib.Path(a.repo) / "scripts" / "virt_team_launcher.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    groups, help_map = None, {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        name = getattr(node.targets[0], "id", "")
        if name == "_SETTING_GROUPS":
            groups = literal(node.value)
        elif name == "_SETTING_HELP":
            for k, v in zip(node.value.keys, node.value.values):
                key = k.value if isinstance(k, ast.Constant) else ast.unparse(k)
                key = CONST_LABELS.get(key, key)
                parts = [literal(e) for e in v.elts] if isinstance(v, ast.Tuple) else []
                help_map[key] = tuple(" ".join(str(p).split()) for p in parts)

    if not groups or not help_map:
        print("could not read _SETTING_GROUPS / _SETTING_HELP", file=stderr())
        return 1

    # The per-project analyser toggles. They live in install_helper's _REVIEW_TOOLS,
    # not in _SETTING_GROUPS, because the classic UI asked them in a separate step
    # ("Project preferences"). That step is redundant now - project settings belong on
    # the project you are in - so the toggles move here, read from the same tuple so the
    # list cannot drift from the analysers the reviewers actually run.
    tools = []
    m = re.search(r"_REVIEW_TOOLS = \(([^)]*)\)", (pathlib.Path(a.repo) / "install_helper.py")
                  .read_text(encoding="utf-8"))
    if m:
        tools = [t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()]

    out = []
    for title, keys in groups:
        rows = []
        for key in keys:
            label = KEY_TO_LABEL.get(key, key)
            what, off = (help_map.get(label) + ("", ""))[:2]
            rows.append({
                "key": key,
                "label": label,
                "kind": "choice" if label in CHOICES else "toggle",
                "options": CHOICES.get(label, ()),
                "value": CHOICES[label][0] if label in CHOICES else DEFAULTS_ON.get(label, False),
                "what": what,
                "off": off,
                "needs": NEEDS.get(label, ""),
            })
        out.append((title, rows))

    if tools:
        out.append((
            "Analysers (this project)",
            [{
                "key": f"review_tools.{t}",
                "label": t,
                "kind": "toggle",
                "options": (),
                "value": True,
                "what": f"Run {t} as part of a review in this project. Off means the "
                        f"reviewers skip it here, even if it is installed.",
                "off": "Off: not run for this project.",
                "needs": "",
            } for t in tools],
        ))

    dst = pathlib.Path(__file__).resolve().parent.parent / "virt_surv2" / "settings_data.py"
    body = pprint.pformat(out, width=96, sort_dicts=False)
    dst.write_text(
        '"""GENERATED by tools/gen_settings.py — do not edit by hand.\n\n'
        "Groups, labels and help text come from scripts/virt_team_launcher.py\n"
        "(_SETTING_GROUPS, _SETTING_HELP), so this screen cannot drift from the thing\n"
        'it configures. Re-run the generator after either changes.\n"""\n\n'
        f"SETTING_GROUPS = {body}\n",
        encoding="utf-8",
    )
    total = sum(len(r) for _t, r in out)
    print(f"wrote {dst} — {len(out)} groups, {total} settings")
    missing = [r["label"] for _t, rows in out for r in rows if not r["what"]]
    if missing:
        print("  WARNING no help text for: " + ", ".join(missing))
    return 0


def stderr():
    import sys
    return sys.stderr


if __name__ == "__main__":
    raise SystemExit(main())
