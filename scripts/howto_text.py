#!/usr/bin/env python3
"""Morgan's day-to-day narrative: the words, with no idea how they will be drawn.

WHERE IT CAME FROM. This was menu item 5 of the installer (`run_howto`, added 2026-08-18),
printed straight to the console. The owner moved it on 2026-09-12: "move the working with
me day to day to virt-surv go, update the text, it still refers to artifacts/, make sure
this sits in textual not just showing in the terminal". It belongs beside the menu people
actually use every day, not behind an installer someone runs once.

WHY A MODULE OF ITS OWN. Three tiers draw this now - Textual, prompt_toolkit and the plain
console - and a narrative kept in the renderer is a narrative that exists three times. The
text lives here; each tier decides only how to paint it. The layout it describes is
vsit_paths' (VSIT/engagements, VSIT/config, VSIT/local), which is the other half of why the
old copy had gone stale: it still told people to look in a folder the team had moved out of.
"""

from __future__ import annotations

TITLE = "How to work with the team, day to day"


def sections() -> list[tuple[str, str]]:
    """(heading, body) pairs, in reading order.

    Bodies are single paragraphs with no hard line breaks: the pane widths differ by tier
    (26 columns beside a Textual list, a full console in the plain tier), so wrapping is
    the renderer's decision and baking it in here is how the phone-width screens ended up
    with a mangled second copy of themselves.
    """
    return [
        (
            "Morgan, your delivery lead",
            "I'm an AI agent with Virtual Surveillance IT. I run the team: I take the "
            "work, pick the specialists, and come back to you at every gate. Here is how "
            "a piece of work goes, start to finish.",
        ),
        (
            "Starting a session",
            "cd into your project folder and type virt-surv go. You see your project's "
            "team settings at a glance, then this menu: resume an open piece of work, "
            "start something new, or just launch. Pick with the arrow keys or the "
            "hotkeys, and Claude Code starts with your choice already typed in. If a "
            "project is not set up yet, go walks you through it first.",
        ),
        (
            "Working with me",
            "Describe whatever you have got in plain English - a problem to solve, code "
            "to review, something to build, data to analyse. I classify it, ask what I "
            "genuinely need to know (batched, one screen), tell you how many specialists "
            "I intend to use and roughly what it will cost, and wait for your go-ahead. "
            "Then I run the work in small stages and come back to you at each gate. You "
            "invoke the team once per piece of work; after that, just reply normally.",
        ),
        (
            "Where the work lands",
            "Everything for one piece of work lands in your project under "
            "VSIT/engagements/<slug>/ - the brief, the work itself, reviews with their "
            "evidence, and a closing summary email, each as .md and rendered .html. "
            "START-HERE.md in that folder is the index for the engagement, and "
            "VSIT/engagements/ENGAGEMENTS.md is the register of every piece of work in "
            "the project. Press v on this menu to open any of it.",
        ),
        (
            "The rest of the VSIT folder",
            "VSIT/config/ holds this project's settings - the preferences you change with "
            "c on this menu, and the workflow contract the team inherits. VSIT/shared/ "
            "holds what every engagement needs, the codebase map above all. VSIT/local/ "
            "is machine-only cache: it is derived from this checkout and is not worth "
            "committing. Older projects still carry the pre-VSIT layout and the team "
            "reads it exactly as it finds it, so nothing has to be moved before it works.",
        ),
        (
            "The standing safety rules",
            "I never read data/raw/ (hard-blocked, in every session, engaged or not), "
            "never run the code under review without your explicit consent (you create "
            "the marker; my asking is intent, not the grant), and treat all real-looking "
            "data as sensitive - synthetic or masked only. Outside an engagement the "
            "plugin is dormant: an ordinary session is ordinary Claude Code.",
        ),
        (
            "More detail",
            "README.md and docs/quick-start.pdf (one page) carry the reference; "
            "/meet-the-team inside a session introduces the 13 specialists.",
        ),
    ]
