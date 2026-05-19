"""
MSO Sovereign Runtime Kernel.

This module is the formal executable boundary of the MSO.

The core orchestrator remains the current implementation body of the MSO
runtime. External executable paths should enter through this module rather
than importing the orchestrator directly.

MSO owns the orchestrator.
The orchestrator is not an independent sovereign actor.
"""

from __future__ import annotations

from typing import Any


def handle_sovereign_request(request: Any, *, source: str | None = None, **kwargs: Any) -> Any:
    """
    Handle an executable sovereign request through the MSO runtime boundary.

    Delegates to core.orchestrator.handle_request, forwarding all kwargs
    (e.g. forced_operation) transparently. The `source` argument is reserved
    for future audit/readiness use and is never forwarded to the orchestrator.
    """
    from assistant_os.core.orchestrator import handle_request

    return handle_request(request, **kwargs)
