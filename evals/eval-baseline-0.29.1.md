# Eval baseline — 0.29.1 (patch promotion record)

Scope: deterministic-only
Date: 2026-07-27
Method: pytest + the deterministic scorer only, per CONTRIBUTING's patch-release path. This
patch changes NO prompt surface: it fixes the code-execution guard's team-tooling allow-list
(consent prompts were forced for `engagement_state.py` by path and for any quoted plugin
install path containing spaces) and tightens the half-quoted-path acceptance. Behaviour under
prompt evaluation is unchanged from the 0.29.0 baseline, which remains the live-evidence
record.

## Evidence

- Full pytest suite green, including 6 new guard tests covering both directions (new
  allowances by every invocation form; non-team basenames, chained executions and half-quoted
  smuggles still blocked) and a live/staged parity check.
- The exec pattern list is asserted byte-identical to the pre-patch guard - only the team
  allow-list changed.
- Guard installed by the human via `scripts/apply-guard-exec-allow.sh` (ADR-002 rec 5).

## Verdict

**PASS for promotion (deterministic scope)** — no prompt changes; 0.29.0's golden-slice
baseline carries the live-orchestration evidence.
