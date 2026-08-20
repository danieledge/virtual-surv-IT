"""virt-surv model-runtime POC (2026-08-20) - see docs/internal/poc-runtime-boundary.md.

Import surface kept tiny on purpose: a workflow needs the loop, the contract types and a
policy. Adapters are imported explicitly by whoever selects one, so no provider module is
ever pulled in just by importing the runtime.
"""

from .contract import (
    Message,
    ModelRuntime,
    Reply,
    RuntimeUnavailable,
    ToolCall,
    ToolSpec,
    Usage,
)
from .loop import RunResult, run
from .policy import Decision, Policy

__all__ = [
    "Decision",
    "Message",
    "ModelRuntime",
    "Policy",
    "Reply",
    "RunResult",
    "RuntimeUnavailable",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "run",
]
