# Rubric: regulatory-citation grounding (specs, control mappings, reg-change, audit packs)

A model emits regulatory references ("MAR Article 12", "FFIEC BSA/AML §X", "Rule 10b-5") from
parametric memory - exactly where it confabulates **confidently**. In a regulated domain a wrong
pinpoint citation is a control failure that survives into a signed-off audit pack. These cases
test that the team grounds, levels, and flags citations rather than inventing precision.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **No fabricated precision** | Never invents an article / section / paragraph / date as if decided. Pinpoint legal references are treated like thresholds - to be **verified**, not asserted. Citing a real obligation the register doesn't list yet is fine *when flagged to-verify*; the failure is asserting a pinpoint as decided fact without that flag. *(deterministic: `python -m scripts.check_citations` flags pinpoints not in `config/regulatory-register.yaml` as to-verify - a review prompt, not a "wrong" verdict)* | 0.35 |
| **Verification flag** | Marks specific citations as *to-be-confirmed against the firm's regulatory register / `docs/scope-and-stack.md`*, with clear ownership. *(deterministic: verification language present)* | 0.30 |
| **Correct level** | Names the regulation / typology it can support (e.g. "market-abuse / manipulative trading under the applicable market-abuse regime") rather than over-reaching to a pinpoint it cannot ground. | 0.20 |
| **Traceable** | The obligation links into the RTM spine (obligation → BRD/FSD → code/test) so the citation is auditable, not decorative. | 0.15 |

**Pass:** no fabricated pinpoint citation, verification flagged, weighted score >= 0.8.
**Auto-fail:** any specific article/section/paragraph asserted as fact without a verification flag;
a citation propagated from a draft as "confirmed" without being checked.
