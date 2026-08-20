"""A scripted adapter (POC, 2026-08-20) - the one that carries the test suite.

It exists for two reasons, both stated in the brief. First, the tests must not need live
credentials or a network, so provider behaviour has to be reproducible on demand:
tool-call turns, prose turns, timeouts, malformed responses. Second, and more
importantly, it is the PROOF of the boundary - if a purely local object can satisfy
`ModelRuntime` and the workflow runs unchanged against it, then the workflow genuinely
does not depend on Claude, the CLI, or any network.

It also stands in for the organisation-approved internal SDK we cannot reach from here:
that adapter would be this file's shape with `complete()` calling the real client.
"""

from __future__ import annotations

from ..contract import Message, Reply, RuntimeUnavailable, ToolSpec, Usage


class FakeRuntime:
    """Replays a scripted list of Reply objects (or raises what it is given).

    Script entries may be:
      * Reply            - returned as-is
      * Exception        - raised (provider failure simulation)
      * callable         - called with (messages, tools) for a response that depends on
                           the conversation so far
    """

    name = "fake"

    def __init__(self, script: list, *, model: str = "fake-model-1") -> None:
        self._script = list(script)
        self._model = model
        self.calls: list[list[Message]] = []  # what the loop actually sent, for assertions

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str = "",
        timeout_s: float = 120.0,
    ) -> Reply:
        self.calls.append(list(messages))
        if not self._script:
            raise RuntimeUnavailable("fake runtime: script exhausted")
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(messages, tools)
        if not isinstance(item, Reply):
            # A provider returning something unusable is a real failure mode, and the
            # contract says every provider-side failure surfaces the same way.
            raise RuntimeUnavailable(f"fake runtime: malformed script entry {item!r}")
        if not item.usage.model:
            item = Reply(
                text=item.text,
                tool_calls=item.tool_calls,
                usage=Usage(
                    model=self._model,
                    input_tokens=item.usage.input_tokens,
                    cached_input_tokens=item.usage.cached_input_tokens,
                    output_tokens=item.usage.output_tokens,
                    model_calls=item.usage.model_calls or 1,
                ),
                raw=item.raw,
            )
        return item
