"""Symbols for the languages a bank actually runs.

2026-08-24. Until now anything that was not Python or Markdown got NOTHING from the skeleton
beyond its own filename: tree-sitter and ctags are optional probes, and neither exists on a
locked-down corporate box (nor on the dev box). Surveillance systems are overwhelmingly Java,
C#, SQL and Scala, so the codebase map degraded to a file listing on exactly the work it was
built for.

Regex is a deliberate choice here, not a shortcut. A real parser for six languages cannot be
vendored under this repo's no-compiled-wheel constraint, and the alternative on offer was
nothing at all. It finds DECLARATION LINES, which is what first-contact orientation needs,
and it reports its own tier so a reader knows an `ast` listing is exact while this one is
indicative. These tests pin both halves: that it finds the declarations, and that it does not
invent them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "repo_skeleton", REPO_ROOT / "scripts" / "repo_skeleton.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["repo_skeleton"] = m
    spec.loader.exec_module(m)
    return m


def _symbols(tmp_path: Path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return _mod().extract_symbols(path)


def test_java_yields_types_and_methods(tmp_path):
    syms, tier = _symbols(
        tmp_path,
        "AlertEngine.java",
        "public final class AlertEngine implements Runnable {\n"
        "    public List<Alert> evaluate(Order o) throws RuleException {\n"
        "        if (o == null) { return null; }\n"
        "        for (int i = 0; i < 3; i++) { go(i); }\n"
        "        return null;\n"
        "    }\n"
        "}\n"
        "interface RuleSet { }\n",
    )
    assert tier == "regex"
    assert "type AlertEngine" in syms and "method evaluate" in syms
    assert "type RuleSet" in syms


def test_control_flow_is_not_mistaken_for_a_method(tmp_path):
    """`if (...)  {` and `for (...) {` are shaped exactly like a method declaration. Without
    the keyword guard, every branch in a Java file becomes a symbol and the listing is
    worthless."""
    syms, _ = _symbols(
        tmp_path,
        "Guard.java",
        "public class Guard {\n"
        "    void run() {\n"
        "        if (x) { }\n"
        "        while (y) { }\n"
        "        switch (z) { }\n"
        "        catch (Exception e) { }\n"
        "    }\n"
        "}\n",
    )
    for keyword in ("if", "while", "switch", "catch"):
        assert f"method {keyword}" not in syms, f"{keyword} was read as a declaration"


def test_commented_declarations_are_ignored(tmp_path):
    """A commented-out class is noise, and in a legacy surveillance codebase there is a lot
    of it."""
    syms, _ = _symbols(
        tmp_path,
        "Old.java",
        "// public class CommentedOut {}\n"
        "/* public class BlockCommented {} */\n"
        "public class Live {}\n",
    )
    assert "type Live" in syms
    assert not any("Commented" in s for s in syms)


def test_sql_reports_the_object_type_not_just_the_name(tmp_path):
    """Knowing a name is a VIEW rather than a PROCEDURE is most of the value of seeing it at
    all in a surveillance schema."""
    syms, tier = _symbols(
        tmp_path,
        "schema.sql",
        "-- CREATE TABLE commented (x int);\n"
        "CREATE OR REPLACE VIEW vw_spoof AS SELECT 1;\n"
        "CREATE TABLE IF NOT EXISTS surv.order_book (id BIGINT);\n"
        "CREATE PROCEDURE sp_recalc AS BEGIN SELECT 1 END;\n"
        "CREATE MATERIALIZED VIEW mv_daily AS SELECT 1;\n",
    )
    assert tier == "regex"
    assert "view vw_spoof" in syms
    assert "table surv.order_book" in syms, "schema-qualified names must survive"
    assert "procedure sp_recalc" in syms
    assert "materialized view mv_daily" in syms
    assert not any("commented" in s for s in syms)


def test_scala_csharp_and_typescript(tmp_path):
    scala, _ = _symbols(
        tmp_path,
        "S.scala",
        "case class Score(id: String)\nobject Scoring {\n  def compute = 1\n}\n",
    )
    assert "type Score" in scala and "def compute" in scala
    cs, _ = _symbols(
        tmp_path,
        "M.cs",
        "public sealed class TradeMonitor : IMonitor {\n"
        "    public async Task<bool> EvaluateAsync(Order o) {\n        return true;\n    }\n}\n",
    )
    assert "type TradeMonitor" in cs and "method EvaluateAsync" in cs
    ts, _ = _symbols(
        tmp_path,
        "d.ts",
        "export class AlertGrid {}\n"
        "export async function fetchAlerts(q) { return []; }\n"
        "export const useAlerts = (id) => null;\n",
    )
    assert "class AlertGrid" in ts and "function fetchAlerts" in ts and "arrow useAlerts" in ts


def test_python_still_uses_the_exact_ast_tier(tmp_path):
    """The regex tier sits BELOW ast and must never shadow it - an ast listing is exact and
    a regex one is indicative, and silently downgrading Python would be a regression."""
    _syms, tier = _symbols(tmp_path, "m.py", "def f():\n    pass\n")
    assert tier == "ast"


def test_an_unknown_language_still_falls_through_to_the_floor(tmp_path):
    _syms, tier = _symbols(tmp_path, "notes.txt", "hello\n")
    assert tier == "floor"


def test_a_huge_generated_file_cannot_blow_the_budget(tmp_path):
    """Bounded like every other tier here: a 100k-line generated file must not consume the
    whole skeleton."""
    mod = _mod()
    body = "\n".join(f"public class C{i} {{}}" for i in range(5000))
    syms, _ = _symbols(tmp_path, "Big.java", body)
    assert len(syms) <= mod._REGEX_MAX_SYMBOLS


def test_the_tier_name_travels_with_the_output(tmp_path):
    """The whole honesty story rests on this: a reader must be able to tell an exact listing
    from an indicative one."""
    mod = _mod()
    assert mod._TIER_REGEX == "regex"
    _syms, tier = _symbols(tmp_path, "A.java", "public class A {}\n")
    assert tier == mod._TIER_REGEX
