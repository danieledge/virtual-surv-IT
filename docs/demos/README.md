# 🎬 Demo transcripts

**See the team work without running anything.** These are *real* transcripts of the `/demo` skill -
Morgan (the PM) running a full engagement end-to-end on **safe synthetic data**, narrating every
decision. They reproduce the actual console: the 🎩 narration, the commands and their output, the
real agent findings, the guard hard-block, and the eval score.

> Honest by design: every agent output, guard block and eval score below is **genuine** - captured
> from a real run, just on synthetic data. Nothing is faked for effect. (Analyser availability and
> exact wording will vary run to run.)

### How to read a transcript (who's speaking)
| Style | Who | What it is |
|---|---|---|
| > 🎩 **Morgan** … (blockquote) | **Morgan, the AI PM** | Spoken **live in the session** - exactly what you'd see. *Morgan's words, not a human author's.* |
| Plain text | This page | Editorial framing / stage directions for the reader. |
| ` ```console ` / ` ```python ` blocks | The tools / agents | **Real** commands, their output, and verbatim specialist (agent) findings. |

So when Morgan says something clever or sceptical below, that's **the model running the team** -
generated at the moment, not scripted by the repo author.

| Demo | What it shows |
|---|---|
| [🔍 Review](review-demo.md) | The review pipeline - one agent (right-sized), evidence-basis discipline, and the eval harness *proving* the result (recall 1.0). |
| [🛡️ Data safety](data-safety-demo.md) | The §5 keystone - the raw-data guard **hard-blocking a read in real time**, and the masking validator *failing* a file that leaked PII. |
| [🏗️ Build](build-demo.md) | Orchestrator-workers - business-analyst → SME → rules-developer → reviewers, each output feeding the next via the blackboard. |

**To run a demo live:** open the repo in Claude Code and type **`/demo`**. To put the team to work
on your own code, type **`/engage`**.
