# virt-surv2

A Textual front end for the installer and launcher. It runs **alongside `virt-surv`**,
not instead of it, so the two can be compared on the same machine.

```
python -m virt_surv2 --demo        dry run: executes nothing, writes nothing
python -m virt_surv2               install / reconfigure
python -m virt_surv2 --launch      the launcher screen
python -m virt_surv2 --settings    project settings
python -m virt_surv2 --alias       register the 'virt-surv2' shell shortcut
```

`scripts/virt-surv2` is the same thing as an executable, resolved through symlinks so a
link on `PATH` works.

## It does not reimplement the engine

`install_helper.py` is imported and driven. Every fix in it — `find_claude`,
`find_working_claude`, the PATH-shim fallback, `windows_shim_cmdline`,
`_windows_registry_path_dirs`, `register_plugin_directly`, the cp1252 handling — applies
here unchanged. `virt_surv2/engine.py` only changes **where the output goes** and **where
the questions are answered**, through three seams:

| seam | |
|---|---|
| **output** | `Installer.observer` — `line` / `step` / `result`, already in the engine |
| **input** | module-level `ask()` / `confirm()`, patched for the run and restored in a `finally` |
| **strays** | stdout/stderr captured for the duration — two raw `print()` calls survive in the bashrc step (install_helper.py 3571, 3577) and a stray write tears a full-screen frame |

The step list, its order and its count come from `Installer.build_plan()`. The UI holds no
copy of it, so a step added to the engine appears here for free.

## Decide first, then run uninterrupted

A full run asks **28 questions** and stops at steps 2, 3, 4, 7, 8, 12, 13 and 14, so it can
never run unattended — and its "go with the recommended defaults for all of these?" fast
path is not offered until **step 7**, after three of those have already been answered.

Here every routine decision is taken up front and the run then goes start to finish.
Questions that are *not* routine still stop and ask, in a modal:

- **The safety set is never auto-answered.** `stash`, `discard`, `bring you up to date`,
  the claude-CLI path, `replace the existing status line` — two of those can destroy
  uncommitted work, so they always reach a human.
- Everything the decide screen covers is answered from it.

`VS_TUI_TRACE=/path/to/log` records every prompt and answer. A full-screen app redraws
over its own history, so this is the only way to see what the engine actually asked.

## Capabilities the old path never installed

`requirements-review.txt` holds seven packages. `code_intel_step` installs only the two
`tree-sitter` ones — by design ("the analysers in it are a separate decision") — so
**ruff, black, mypy, bandit and sqlfluff were never installed by any path**, and the probe
then reports them missing. That is what Advanced option 14 ("re-probe installed tools")
exists to paper over.

virt-surv2 offers all three capabilities, defaulted on, with the pins from the file:

| | |
|---|---|
| Document output | `requirements-dev.txt` — python-docx, Markdown, bleach. **`python-docx` is what the `docx export` setting runs on**, so calling these "only needed to contribute" was wrong |
| Code intelligence | the `tree-sitter` pair, via the engine's own step |
| Review analysers | ruff, black, mypy, bandit, sqlfluff — the gap above |

None of them is fatal: a locked-down box with no pip degrades to a skip, matching the
contract the engine already uses for its own optional steps.

## Vendored, so a user installs nothing

`textual`, `platformdirs` and `typing_extensions` are in `vendor/` alongside `rich`. All
pure Python (no `.so`/`.pyd`), so one copy serves Linux, macOS and Windows, and
`python3 -S -m virt_surv2` works with no site-packages at all.

Two things deliberately **not** vendored:

- **Textual's `syntax` extra** — 14 `tree-sitter-*` packages with compiled C extensions,
  which are platform-specific wheels and would break the vendoring model outright.
- **`pygments` and `markdown-it-py`** — declared requirements, but verified not imported
  by anything this uses. They are only pulled in by the `Markdown` and `Syntax` widgets.
  Including them would add ~6M for nothing.

`rich` is already vendored at 15.0.0 and Textual needs `>=14.2.0`, so it is untouched.
Once `virt-surv` no longer needs `prompt_toolkit` (1.7M) and `wcwidth` (1.8M — nothing
outside `vendor/` references it), dropping both makes this close to a net-zero change.

## Terminal target

A modern VT terminal: truecolor, UTF-8, GPU-composited. Windows 11 makes Windows Terminal
the default, so that is the floor. There is **no 16-colour or ASCII design tier** — that
is what produced the 373-line hand-drawn `scripts/tui_chrome.py`. Tier 0 is plain text
with no chrome, for pipes, CI and dumb SSH.

Layout is responsive: under 76 columns it collapses to a single column and the detail pane
moves to the footer line. Verified on a phone.

## Tests

```
python3 tests/test_virt_surv2_regressions.py    every case is a bug that happened
python3 tests/test_virt_surv2_matrix.py         the combinatorial pass
```

Both are also pytest-discoverable. ~730 checks: all 32 build_args combinations, every
`ANSWER_MAP` entry both ways, every decide and settings row through every option, key
fuzz on every screen, the responsive breakpoint, every engine failure mode (crash,
KeyboardInterrupt, OSError, SystemExit, app-gone-mid-run), and the modal's every
kind × key.

> **Do not test the worker with Textual's `run_test()`.** It deadlocks when a thread
> worker calls `call_from_thread`, which is exactly what the bridge does. Anything
> involving the engine thread has to run under a real pty.

One class of bug the matrix originally missed, now covered: it asserted **model state**
and never **rendered output**, so a screen whose rows rendered a different object than the
one the toggles mutated passed every check while doing nothing visible.
