# Worked example

> Moved out of README.md on 2026-09-14 (framework review, step 6.8).


A complete reference scenario ships with the repo so the conventions are concrete, the
**bundled example** (the worked example, not the agents themselves):

```
rules/spoofing.py            # MAR spoofing detection (deterministic, explainable)
scripts/gen_synthetic.py     # synthetic order-flow generator (§5 - no real data)
tests/test_spoofing.py       # true-positive + false-positive cases (§4)
docs/scenarios/spoofing.md   # audit trail: alert → logic → obligation
```

(The full repo structure is in [Layout](../README.md#-layout). New to the spoofing example?
[`docs/OVERVIEW.md` §6](OVERVIEW.md) explains it in plain English.)

Quickstart:

```bash
pip install -r requirements-dev.txt
pytest                                   # all tests green
python -m scripts.gen_synthetic --kind spoofing --out data/synthetic/spoofing.jsonl
pre-commit install                       # optional: enable local guardrails
```

Add a new detection with `/new-scenario <requirement>`, which chains
business-analyst (consulting the `docs/sme/` pack) → rules-developer → code-reviewer →
compliance-reviewer per the
handbook.

<sub>[↑ Back to top](../README.md#readme-top)</sub>
