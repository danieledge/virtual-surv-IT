# Plan: bring `virt-surv` (no arguments) up to the standard of `virt-surv go`

**Status:** proposal, 2026-08-25. Nothing built.
**Ask (owner):** "explore elegant TUI interfaces to replace the `virt-surv` (no parameters)
path - diagnostics, installing the plugin, updating, setting machine defaults. The current
solution feels behind the `virt-surv go` route."
**Research:** an agent audited both front doors read-only first. Evidence inline.

---

## 1. What is actually there today

`virt-surv` with no arguments reaches `choose_action()` - a `print()` loop with `input()`,
about 170 lines, three levels deep in one place. Twenty-one options across a top menu,
Diagnostics and Advanced, plus a third level inside "manage the alias".

Ten of those twenty-one write **outside the repo**: shell rc files, `~/.claude/settings.json`,
`~/.config/virt-surv-it/installer.json`, an `rmtree` of stale plugin caches, and two that
start a real background daemon. Today the menu says almost nothing about which is which. That
is the substantive complaint hiding inside "feels behind": the launcher explains every setting
in a pane beside it, and the installer - which does far more dangerous things - explains
none of them.

The audit also turned up a stale cross-reference: the update notice points at
"Diagnostics (5)" when Diagnostics is option **3**.

## 2. The finding that makes this cheap instead of risky

Fifty test references touch this menu, which looks like a large blast radius. It is not.

`_menu_session`, the test harness, fakes **stdin only** - and under pytest `sys.stderr` is not
a tty. The launcher's availability gate `_ptk_ui()` requires **both** stdin and stderr to be
ttys. So if the new chooser is gated the same way, **all twenty-one scripted-menu tests keep
running the numbered path, unchanged, and keep passing.**

What actually breaks: three exact-dict assertions, and only if the option set itself changes.

That single fact is what turns this from a rewrite into an addition.

## 3. Recommendation

**Reuse the launcher's chrome, in-process, for the CHOOSER LAYER ONLY.**

`screen()`, `glyphs()`, `PALETTE` and the 2:1 pane split are already written, already
pty-verified, and already carry the things that took three attempts to get right: cp1252
glyph fallbacks, the pane ratio that stops labels clipping, eager-Esc, and the Windows
`CONOUT$` rebinding. They need exactly two attributes off the module handed to them -
`_can_encode` and `_morgan_line` - and `project_dir` is already optional. The chrome is
context-free; the *screens* above it are not.

So: a new `scripts/installer_app.py` exposing a menu screen, and `choose_action()` becomes a
short try/fallback wrapper. On no tty, no `vendor/`, no `scripts/`, or any exception at all,
it falls through to today's numbered menu untouched.

**Do not make the steps full-screen.** Roughly 7,400 of the installer's 8,039 lines interleave
logic with streaming subprocess output - git, pip, `claude plugin install`. A full-screen app
fights that for no gain. The app should exit *before* a step runs, exactly as `virt-surv go`
exits before launching Claude.

### Rejected, with reasons

- **Subprocess to a launcher-side screen.** The menu loops back after every action, so this
  pays a process spawn per iteration, and it introduces a second "stdout is the decision
  channel" protocol - a pattern with a live-bug history in this repo.
- **A hand-rolled stdlib key-reader.** Raw-mode restore, Ctrl-C, resize, Windows two-byte
  arrow sequences, PowerShell vs Git Bash vs ConEmu. That is the exact list `prompt_toolkit`
  was vendored to avoid, and it would break all twenty-one `_menu_session` tests because raw
  reading bypasses `input()`. It buys a worse version of something already paid for.

### Sequencing: content first, then chrome

**Phase 0 - the option table.** Move the twenty-one options into one table carrying, per
option: label, action, one-paragraph explanation, **what it writes**, and whether it needs
network. Render the existing numbered menu from that table, grouped, with destructive options
marked. Fix the stale "Diagnostics (5)".

This is a day's work, it improves the fallback tier that has to keep existing anyway, and it
produces the copy the explanation pane will consume. Same content, two renderers, one source -
which is the lesson the launcher already learned when its two menu tiers drifted apart.

**Phase 1 - the chooser.** Arrow navigation, framed two-pane, explanation on the right,
destructive options visibly marked. Headless tests copied wholesale from the launcher's.

**Phase 2, only if wanted.** The four settings-shaped options - statusline, preferences,
model, machine defaults - become toggle-in-place screens like the launcher's settings editor,
rather than wizard walks.

## 4. Decisions I have taken, so they are visible rather than buried

- **Render to stderr**, matching `screen()`'s default and the launcher's encoding probe, and
  leave step output on stdout. Mixing the two channels mid-run is what `_can_encode` exists
  to prevent, and the launcher's Windows console handling is already built around stderr.
- **"Stdlib-only" means no non-stdlib import at module scope.** The import is lazy, guarded,
  and absent entirely when `vendor/` is not there. The docstring should be amended to say so
  rather than left to look violated.
- **The single-file bootstrap keeps a plain menu.** There is already a code path that detects
  "this is the bootstrap download, not the full clone"; it has no `vendor/` and must degrade,
  not fail.

## 5. Questions that are genuinely yours

1. **Should the option set change, or only its presentation?** Three candidates: the
   three-level alias path; the two prototype diagnostics that start a real daemon (do they
   belong in a user-facing menu at all?); and whether Diagnostics and Advanced are the right
   two groupings for twenty-one options. Changing the set costs the three dict tests - cheap -
   but it is a product decision, not a technical one.
2. **Does `run_configure` come too?** It is the richest interactive flow - seven numbered
   steps, 368 lines, its own progress display - and the single biggest scope decision here.
   My instinct is no for v1: it is a wizard, and wizards are the one thing a scrolling console
   does well.
3. **Mouse support** is on by default in the launcher's chrome. Keep it for the installer on
   the corporate Windows target, or turn it off?

## 6. Risk

The honest one: this adds a second consumer to `screen()` and friends, so a change made for
the launcher can now break the installer. That is the cost of not duplicating them, and it is
the better trade - but it argues for the shared chrome being tested on its own, rather than
only through whichever screen happens to exercise it.
