"""The safety boundary (POC, 2026-08-20) - virt-surv decides, the model requests.

This module exists to make one architectural claim testable: **no provider or framework
is ever asked whether an operation is allowed.** The model emits a ToolCall; this decides.
If a future adapter is swapped in, or a framework offers its own "tool approval" feature,
nothing here changes and nothing here is bypassed - the loop calls `Policy.check()` before
it calls a handler, full stop.

Scope note for the POC: this is a DEMONSTRATION of the boundary shape, not a replacement
for the production guard hooks. The real controls (guard-raw-data.py,
guard-code-execution.py, guard-consent-writes.py) stay exactly where they are, outside any
model runtime, and would remain the enforcement layer. What this proves is that the
decision point survives the removal of the CLI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .contract import ToolCall


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


# Mirrors the always-on production rule (CLAUDE.md §5): data/raw/ never reaches a model,
# in any session, engaged or not. Pattern kept deliberately blunt - a POC that tried to be
# clever about path normalisation would be claiming more assurance than it has.
_RAW_DATA = re.compile(r"(^|[/\\])data[/\\]raw([/\\]|$)")


class Policy:
    """Allow-list plus explicit refusals. Default is DENY: a tool the workflow did not
    declare cannot run, even if the model asks confidently and by exact name."""

    def __init__(self, allowed_tools: set[str], *, workspace: Path | None = None) -> None:
        self._allowed = set(allowed_tools)
        self._workspace = workspace.resolve() if workspace else None
        self.refusals: list[tuple[str, str]] = []  # (tool, reason) - evidence, not logging

    def check(self, call: ToolCall) -> Decision:
        if call.name not in self._allowed:
            return self._refuse(call, f"tool {call.name!r} is not declared for this workflow")
        for key, value in (call.arguments or {}).items():
            if not isinstance(value, str):
                continue
            if _RAW_DATA.search(value):
                return self._refuse(
                    call, f"argument {key!r} resolves into data/raw/ - hard-blocked (§5)"
                )
            if self._workspace and key in ("path", "file", "target"):
                if not self._within_workspace(value):
                    return self._refuse(call, f"argument {key!r} escapes the engagement workspace")
        return Decision(True)

    def _within_workspace(self, value: str) -> bool:
        try:
            candidate = (self._workspace / value).resolve()
        except (OSError, ValueError):
            return False
        return self._workspace in candidate.parents or candidate == self._workspace

    def _refuse(self, call: ToolCall, reason: str) -> Decision:
        self.refusals.append((call.name, reason))
        return Decision(False, reason)
