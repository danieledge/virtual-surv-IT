"""A stand-in for install_helper.py with the same seams, so the bridge can be tested
without a real install: `Installer` + `observer`, and module-level `ask`/`confirm`
called as globals exactly the way the real engine calls them."""


class Style:
    def __init__(self, colour=False):
        self.colour = colour

    def dim(self, s):
        return s

    def yellow(self, s):
        return s

    def bold(self, s):
        return s

    def cyan(self, s):
        return s


def run_cmd(argv, cwd=None, timeout=300):
    raise AssertionError("real run_cmd reached during a dry run")


def make_demo_runner(style):
    """The dry-run stand-in, same contract as install_helper's."""
    import subprocess

    def runner(argv, cwd=None, timeout=300):
        return subprocess.CompletedProcess([str(a) for a in argv], 0, stdout="", stderr="")

    return runner


def marks():
    return {"ok": "*", "fail": "x", "skip": "-"}


def ask(prompt, default, assume_yes=False, style=None):
    raise AssertionError("real ask() reached — the bridge did not patch it")


def confirm(prompt, default, assume_yes=False, style=None):
    raise AssertionError("real confirm() reached — the bridge did not patch it")


MODE = "normal"          # normal | crash | escalate | stray


class Installer:
    def __init__(self, args, style, mark_map, subset="full"):
        self.args, self.style, self.subset = args, style, subset
        self.observer = None

    def run(self):
        plan = ["Preflight checks", "Release channel", "Local clone", "Install plugin"]
        for n, title in enumerate(plan, 1):
            self.observer.step(n, len(plan), title)
            self.observer.line(f"working on {title.lower()}")

            if n == 2:
                # Answered from the decide screen.
                chan = ask("  Which channel shall I track for you (main/dev)?", "dev")
                self.observer.result("Channel", "ok", chan)
            if n == 3:
                if MODE == "escalate":
                    # NOT in ANSWER_MAP — must reach the modal.
                    keep = confirm("  Local changes found. Shall I stash them and carry on?", True)
                    self.observer.result("Stash", "ok" if keep else "skip", str(keep))
                if MODE == "escalate_ask":
                    cmd = ask("  What command launches Claude Code on this machine? (your own "
                              "alias/function is fine, e.g. 'cc')", "claude")
                    self.observer.result("Launch command", "ok", cmd)
                if MODE == "stray":
                    print("a stray print that would tear the frame")
                if MODE == "crash":
                    raise RuntimeError("engine exploded mid-step")
                if MODE == "crash_keyboard":
                    raise KeyboardInterrupt()
                if MODE == "crash_os":
                    raise OSError("no such device")
                if MODE == "crash_exit":
                    raise SystemExit(3)
            if n == 4:
                wanted = confirm("  Shall I install the optional dev requirements (pytest)?", False)
                self.observer.result("pip", "skip" if not wanted else "ok", "")
        return 0
