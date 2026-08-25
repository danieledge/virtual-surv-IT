# Plan: a clean container to test the plugin properly

**Status:** proposal, 2026-08-25. Nothing built.
**Ask (owner):** "set up a clean container on this host eg a docker where i can fully test the
plugin - i don't want it to just run here, i want to be able to test it cleanly."
**Host survey:** run first, read-only. Findings inline below.

---

## 1. The finding that shapes the whole design

`run-guard.sh` probes for an interpreter and, **if it finds none, exits 0 - allow**. On a base
image without `python3` on PATH, every safety guard is silently inert: the raw-data block, the
execution gate, the consent-write protection. No error, no warning, nothing in the output. The
container would look like it was testing the plugin and would be testing it with the safety
switched off.

That is not hypothetical: `node:20-slim` is already cached on this host and is exactly the
sort of base image someone would reach for.

**Therefore the container must prove its guards are armed before any test is believed.** Not
assume it, not assert it in a comment - actually fire a call that must be blocked, at startup,
and fail loudly if it comes back allowed. Everything else here is ordinary engineering; this
is the part that decides whether the results mean anything.

A second, related gap: plugin installs ship **no `permissions.deny` list**, so the OS-level
backstop for the protected data directory has to be recreated in the test project's
`.claude/settings.json`. The container should do that during setup rather than leave it to
whoever runs it.

## 2. Two containers, because "test the plugin" means two different things

They have different contents and different purposes, and conflating them is how you get one
image that does neither job honestly.

### (a) `suite` - run the tests

A dev checkout: Python 3.12, `requirements-dev.txt`, `git`, `ruff`, `shellcheck`. Runs
`pytest`, the validators and the lint legs. This is CI on your desk, and it is the *cheap*
one - no auth, no API spend, no `claude` binary needed.

**It must be a real git clone, not `COPY . .`** - several tests shell out to `git`
(`test_release_gate`, `test_map_integrity`, `test_repo_skeleton`), and a tree with no history
fails them for the wrong reason.

### (b) `fresh` - be a new user

**This is the one that answers the ask.** A machine that has never seen this plugin: empty
`~/.claude`, no alias, no config, nothing vendored on the path. Install the plugin the way a
real user does, open a project that is not this repo, and use it.

It is the only way to test what has actually broken this month, all of which lives in the gap
between "works in the repo" and "works installed":

- plugin-mode path resolution (`CLAUDE_PLUGIN_ROOT` vs repo-as-project);
- the execution guard's allow-list against absolute paths from a foreign project - the exact
  shape of the 2026-08-01 defect, where the team's own tooling prompted for consent;
- the alias install and its self-healing;
- first-run setup, and the launcher on a machine with no terminal emulator and no X display;
- whether `claude plugin marketplace add` works against a local clone offline.

The repo mounts **read-only** here, if at all. A `fresh` container that can write to the repo
is not a fresh machine.

## 3. Authentication - the sharpest decision

Two paths exist on this host and they are not equivalent:

| Path | Verdict |
|---|---|
| **`ANTHROPIC_API_KEY`** | Already in `~/.secrets.env`. Pass with `--env-file`. Nothing mounted, nothing shared, revocable on its own. **Use this.** |
| **Mounting the OAuth credentials file** | A live, refreshable session. The container would share your actual Claude session and could refresh its tokens. **Do not.** |

And in both cases: **never mount the host `~/.claude/`**. It holds 135 project directories,
plugin state and settings. A container that inherits it is not clean by any definition, and
its results would not transfer to a real new machine.

## 4. Shape

```
docker/
  Dockerfile.suite      # python:3.12-slim + git + dev deps    -> pytest
  Dockerfile.fresh      # python:3.12-slim + git + claude CLI  -> a new user's machine
  compose.yml           # both, named, with the mounts spelled out
  armed.sh              # the guard self-test from section 1
  README.md             # what each is for, and what each proves
```

`claude` in the `fresh` image: install via the official script at build time (network) rather
than copying the host's binary. It is a static ELF and would probably work, but "probably" is
not a property to build a test environment on, and pinning the version in the Dockerfile is
worth more than saving a download.

Base image `python:3.12-slim`, not `node:20-slim` - see section 1. Not Alpine either: musl
against a static-ELF binary is an unknown nobody needs.

## 5. What it will not do

Stated so nobody discovers it as a fault:

- **No X display**, so the new-window launch degrades to in-place. `launch_terminal.available()`
  already returns `""` and falls back, which is correct - and worth confirming here rather
  than only on Windows.
- **The interactive TUI needs `docker run -it`.** The launcher gates on `isatty()`; without a
  TTY it takes its non-interactive path, which is a different code path and also worth
  testing - deliberately, both ways.
- **Real API spend** in `fresh` whenever a session runs. `-p` runs with `--max-budget-usd` are
  the safe way to exercise it; the suite container spends nothing.
- **Nested containers** are not attempted. This host is itself a Proxmox guest, and whether its
  Docker can run privileged nested workloads was not established.

## 6. Risks and unknowns from the survey

- **Full-suite duration is recorded nowhere** - CI allows 30 minutes a job and that is the only
  bound in evidence. It needs measuring once, in the container, before any timeout is chosen.
  A guessed limit that bites intermittently is worse than no limit.
- **Network is required at build time** for the base image, `pip`, `apt` and the `claude`
  installer. Only the plugin's own front-door tooling is offline-safe, via `vendor/`. An
  air-gapped variant is a separate exercise and should not be smuggled into this one.
- **Disk**: 44G free, `/var/lib/docker` already at 15G. Two images plus the `claude` binary is
  comfortable, not unlimited.
- **`dashboard-ui/`** needs `npm ci` (network; `node_modules` is git-ignored) if it is in
  scope. Proposed out of scope for v1 - said explicitly rather than silently omitted.

## 7. Build order

1. `Dockerfile.suite` + `compose.yml`, and **measure** the full suite once. No auth and no
   spend, so it is the cheap way to prove the shape works.
2. `armed.sh`, wired into both images as a startup gate. Nothing else is trustworthy until it
   exists.
3. `Dockerfile.fresh` with the `claude` CLI pinned, an empty `~/.claude`, repo read-only.
4. A scripted first run: install the plugin, open a scratch project, assert the guards are
   armed *there*, and run one `-p` engagement with a hard cap.
5. Document what each container proves - and, more usefully, what it does not.
