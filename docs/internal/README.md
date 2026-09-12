# docs/internal/ - maintainer documentation (not loaded by the plugin)

The split (2026-07-29, user request during the workflow-robustness remediation):

- **`docs/` (parent)** holds what the TEAM actually loads or follows at runtime - the
  operating guide, scope-and-stack, house rules, the DoD, review method + `review/`,
  `templates/`, `adr/`, coding standards, WAYS-OF-WORKING, agent-design, `scenarios/`
  (the demo rule's audit trail), `demos/` (pointed at by `/demo`) - plus the small
  user-facing set (OVERVIEW, FAQ, glossary, EXTENDING) linked from the README.
- **`docs/internal/` (here)** holds documentation ABOUT the product that nothing at
  runtime reads: research and evidence bases, design specs and roadmaps, flow
  diagrams/posters, and point-in-time eval baselines.

Rule of thumb for new documents: if a skill, script, hook or template references it, or a
working-project engagement is expected to read it, it goes in `docs/`; if only a maintainer
of THIS repo reads it, it goes here.

Contents:

| File | What it is |
|---|---|
| `research-virtual-team.md` | The research base behind the team design (referenced as rationale by skills/hooks, never loaded) |
| `evidence-base.md` | Claim-by-claim evidence inventory from the verification engagement |
| `eval-baseline-2026-07-06.md` | Point-in-time eval baseline (later baselines live in `evals/`) |
| `prepare-data-design.md` / `prepare-data-roadmap.md` | Design spec + roadmap for the assisted-masking evolution (**partly built**: the roadmap's format-adapter item is largely `scripts/convert_file.py`, which handles xlsx, xls, csv, pdf, docx, eml and msg) |
| `engagement-flow-spec.md` | The normative spec of the engagement machine (hooks, gates, close order) |
| `engagement-flow-diagram.md` / `engagement-flow-poster-flowchart.html` | Flow visuals / marketing poster |
| `resolved-issues.md` | Archive of previously reported known issues that are resolved or fully mitigated (the README keeps only open ones) |
| `cross-platform-portability-roadmap.md` | Research + plan for running this team under GitHub Copilot as well as Claude Code (not yet built) |
| `large-context-review-splitting-plan.md` | Design record for component-wise review splitting - fixes corp-proxy timeouts on large-context reviewer calls and improves review focus generally (implemented; behaviour lives in `docs/team-operating-guide.md`) |
| `cache-contract.md` | What each cache under `VSIT/local/` promises, and its TTL |
| `incident-log.md` | Append-only record of live failures and what fixed them |
| `windows-test-vm-access.md` | How to reach the Windows test VM (git-ignored) |
| `whole-plugin-review-2026-08-05.md` | Full-product review, point-in-time |
| `dev-briefing-2026-08-10-plugin-engineering-challenges.md` | What is hard about building this, for a new maintainer |
| `resolved-issues.md` | Archive of README known-issues entries that are now closed |

**Dated working documents are NOT listed individually here** (corrected 2026-09-10: the
table above claimed to be the contents and named nine files while the directory held
thirty-five, which is what happens to any hand-maintained inventory of a growing folder).
Three families, each file carrying its own status line:

- **`plan-*.md`** - a design worked out before building it. **The status line is the
  contract**: when the thing ships, that line says so, names the version and names the
  module. Six of these still said "nothing built" about shipped features until 2026-09-10,
  which is worse than being merely old, because a reader consulting a plan to find out what
  the system does is told the opposite of the truth.
- **`backlog-*.md`** - work parked deliberately, with the reason and what would unblock it.
- **Dated audits and reviews** (`*-audit-*.md`, `*-review-*.md`, `*-baseline-*.md`) -
  point-in-time records. These are archives: they are supposed to accumulate and should
  not be "tidied up".

Several files here are **git-ignored** by deliberate choice, so a fresh clone shows fewer
files than a working checkout. Check before assuming something is missing.

## `docs/adr/` in numbers

`docs/adr/` (architecture decision records) is entirely git-ignored (`.gitignore`, 2026-08-13
owner decision): `git ls-files docs/adr` returns 0 on every clone, while a working dev checkout
holds the files locally (15 as of this measurement). Tracked files across the repo cite bare
`ADR-0xx` numbers in prose roughly 595 times, spanning ADR-001 through ADR-014 - those citations
are prose, not paths, so a link checker cannot chase them and the owner has accepted this volume
as unavoidable. A small, checkable subset cites a *specific* `docs/adr/ADR-0xx-*.md` filename via
path syntax instead of prose; `scripts/validate_references.py` treats those as resolvable
references, and (as of the 2026-09-12 audit) carries an explicit `_KNOWN_ABSENT` entry for each
one actually cited from a tracked file, recording which file cites it and why it can never resolve
from a fresh clone:

- `docs/adr/ADR-002-safety-hook-threat-model.md` - cited by `CLAUDE.md` and
  `.claude/skills/security-audit/SKILL.md`
- `docs/adr/ADR-005-persona-reanchoring-hook.md` - cited by
  `docs/internal/backlog-persona-quality-ablation-2026-08-15.md`
- `../../adr/ADR-014-persistent-guard-daemon.md` - the relative cite from
  `docs/internal/adr-014-spike/README.md`

Before `_KNOWN_ABSENT` carried these three, `validate_references.py` failed in CI on every push
(the files resolve on the maintainer's own machine, where `docs/adr/` still physically exists,
but never on a fresh `actions/checkout`) - this is what closed that gap. If a new tracked file
adds a path-shaped `docs/adr/ADR-0xx-*.md` citation, either add a matching `_KNOWN_ABSENT` entry
or, preferably, cite the ADR number in prose instead (which the checker's path pattern does not
catch), consistent with the volume already accepted above.

## Regenerating the tracked PDFs (`docs/quick-start.pdf`, `docs/internal/engagement-flow-poster-flowchart.pdf`)

Both PDFs are print renders of their `.html` sibling. A browser print-to-PDF resolves each page's
relative links against the local file path it was opened from, so the PDF ends up with embedded
`file:///home/<user>/...` link annotations - a local-path/username leak in a tracked, publicly
readable file (found 2026-09-12: 7 hits in `quick-start.pdf`, 2 in the flowchart PDF). No
generator script is checked in; neither `weasyprint`, `reportlab` nor `playwright` is present in
`.venv`, so until one of those is added, the fix is to strip the offending link annotations from
the existing PDF with the vendored `pypdf` (deps vendored, no pip):

```
python3 -c "
import sys; sys.path.insert(0, 'vendor')
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, ArrayObject

def fix(path):
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        annots = page.get('/Annots')
        if not annots:
            continue
        keep = ArrayObject(
            a for a in annots
            if not str(a.get_object().get('/A', {}).get('/URI', '')).startswith('file:///home/')
        )
        if keep:
            page[NameObject('/Annots')] = keep
        elif '/Annots' in page:
            del page['/Annots']
    writer.write(path)

fix('docs/quick-start.pdf')
fix('docs/internal/engagement-flow-poster-flowchart.pdf')
"
```

Verify with `grep -a -c '/home/' docs/quick-start.pdf docs/internal/engagement-flow-poster-flowchart.pdf`
(expect `0` for both). This removes the clickable links entirely (the visible text is unaffected);
it does not restore working cross-document links. A proper fix regenerates the PDF from the
`.html` source from a neutral working directory with relative or `https://github.com/...` links
baked in before the print step - out of scope until a headless-render tool is vendored or added to
`.venv`.
