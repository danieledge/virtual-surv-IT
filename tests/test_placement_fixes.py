"""Phase 3 mechanical fixes of the 2026-07-29 remediation (register P3/P5/P7).

P3 (D4 ruling): `REVIEW-<slug>.md` is close-only - the prose said so while
`check_artifacts --fix` manufactured it mid-engagement at any status. The tool now aligns
with the prose: findings packs render only during 🔒 closing / ✅ closed, and an uppercase
REVIEW-*.md existing before the close window is FINAL-BEFORE-CLOSE (case-sensitive: the
interim `review-pass-N.md` names stay legal).

P5: findings packs were validated non-recursively; nested packs and the ROOT data/ lane in
workspace mode are now validated too.

P7: STATE-STALE-RENDER caught only JSON-to-index divergence - a hand-edit of the index kept
the copied state-hash and went undetected, and `--fix` destroyed hand-edits by re-rendering
silently. The render now embeds a content hash: hand-edits surface as INDEX-HAND-EDITED and
`--fix` backs the hand-edited file up before re-rendering.
"""

from __future__ import annotations

import copy
import json

from scripts.check_artifacts import apply_fixes, check, main as ca_main

_VALID_PACK = {
    "slug": "t",
    "scope": "s",
    "mode": "audit",
    "verdict": "conditional",
    "findings": [
        {
            "id": "F1",
            "title": "t",
            "severity": "warning",
            "location": "a.py:1",
            "basis": "coded",
            "standard": "CWE-1",
            "problem": "p",
            "likely_cause": "c",
            "impact": "i",
            "fix": {"diff": "-x\n+y", "why": "w"},
            "disposition": "open",
        }
    ],
}


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _index(art, status, listed=()):
    rows = "\n".join(f"- `{name}` - purpose" for name in listed)
    _touch(art / "START-HERE.md", f"# START HERE\n\n| **Status** | {status} |\n\n{rows}\n")
    _touch(art / "START-HERE.html")


def _pack(art, obj, name="findings-t.jsonl", sub=""):
    from scripts.findings_pack_io import write_pack

    d = art / "data" / sub if sub else art / "data"
    write_pack(d / name, obj)


# --- P3: REVIEW render is close-only ------------------------------------------------------


def test_fix_does_not_render_review_mid_engagement(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, "⏳ IN PROGRESS")
    _pack(art, _VALID_PACK)
    apply_fixes(art)
    assert not (art / "REVIEW-t.md").exists()


def test_fix_renders_review_during_closing(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, "🔒 CLOSING - finishing close artifacts")
    _pack(art, _VALID_PACK)
    apply_fixes(art)
    assert (art / "REVIEW-t.md").is_file()


def test_review_md_before_close_is_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "REVIEW-t.md", "# review\n")
    _touch(art / "REVIEW-t.html")
    _index(art, "⏳ IN PROGRESS", listed=["REVIEW-t.md"])
    codes = "".join(check(art))
    assert "FINAL-BEFORE-CLOSE" in codes and "REVIEW-t.md" in codes


def test_lowercase_review_pass_stays_interim_legal(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md", "# interim\n")
    _touch(art / "review-pass-1.html")
    _index(art, "⏳ IN PROGRESS", listed=["review-pass-1.md"])
    assert not any("FINAL-BEFORE-CLOSE" in f for f in check(art))


# --- P5: findings packs validated recursively + the root lane -----------------------------


def test_nested_findings_pack_validated(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, "⏳ IN PROGRESS")
    bad = copy.deepcopy(_VALID_PACK)
    del bad["findings"][0]["likely_cause"]
    _pack(art, bad, name="findings-nested.jsonl", sub="cycle-2")
    assert any("FINDINGS-INVALID" in f for f in check(art))


def test_root_data_lane_validated_in_workspace_mode(tmp_path, capsys):
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    es_main(["--dir", str(art / "audit"), "init", "--title", "a", "--slug", "audit"])
    bad = copy.deepcopy(_VALID_PACK)
    del bad["findings"][0]["impact"]
    _pack(art, bad, name="findings-root.jsonl")
    capsys.readouterr()
    rc = ca_main(["check_artifacts", str(art)])
    out = capsys.readouterr().out
    assert rc == 1 and "FINDINGS-INVALID" in out and "findings-root.jsonl" in out


# --- P7: hand-edited index detected and backed up -----------------------------------------


def _state_pack(tmp_path):
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"])
    return art


def test_hand_edited_index_flagged(tmp_path):
    art = _state_pack(tmp_path)
    index = art / "START-HERE.md"
    index.write_text(
        index.read_text(encoding="utf-8") + "\nHand-added claim: QA passed.\n", encoding="utf-8"
    )
    assert any("INDEX-HAND-EDITED" in f for f in check(art))


def test_fresh_render_not_flagged_as_hand_edited(tmp_path):
    art = _state_pack(tmp_path)
    assert not any("INDEX-HAND-EDITED" in f for f in check(art))


def test_legacy_render_without_content_hash_tolerated(tmp_path):
    art = _state_pack(tmp_path)
    index = art / "START-HERE.md"
    # Simulate a pre-P7 render: strip the content-hash half of the marker.
    import re

    text = index.read_text(encoding="utf-8")
    text = re.sub(r"\s+content-hash:\s*[0-9a-f]+", "", text)
    index.write_text(text, encoding="utf-8")
    assert not any("INDEX-HAND-EDITED" in f for f in check(art))


def test_fix_backs_up_hand_edited_index_before_rerender(tmp_path):
    art = _state_pack(tmp_path)
    index = art / "START-HERE.md"
    edited = index.read_text(encoding="utf-8") + "\nHand-added claim: QA passed.\n"
    index.write_text(edited, encoding="utf-8")
    log = "\n".join(apply_fixes(art))
    assert "INDEX-HAND-EDITED" in log
    backup = art / "START-HERE.md.hand-edited.bak"
    assert backup.is_file() and "Hand-added claim" in backup.read_text(encoding="utf-8")
    # The live index is a fresh render again - the hand-edit is preserved only in the backup.
    assert "Hand-added claim" not in index.read_text(encoding="utf-8")
    assert not any("INDEX-HAND-EDITED" in f for f in check(art))
