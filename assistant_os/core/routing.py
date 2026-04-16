"""
Kernel — Domain Registry

A static dispatch table mapping system domain identifiers to their pipeline
execution functions.

This module contains no business logic. It is a pure routing artifact:
given an action string, derive the system domain and return the callable
that handles execution for that domain.

Key distinction
---------------
plan["domain"] is the *user's task domain* assigned by the classifier
(e.g. "ENERGY", "CODE", "CONSULTORIA").
The *system pipeline domain* ("WORK", "FIN") is derived from the action
string prefix (WORK_* → "WORK", FIN_* → "FIN").

Adding a new domain pipeline means:
  1. Add it to DOMAIN_PIPELINES.
  2. Update action_domain() if needed.
No other kernel module needs to change.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..pipelines.work_pipeline import execute as _work_execute
from ..pipelines.fin_pipeline import execute as _fin_execute
from ..pipelines.code_pipeline import execute as _code_execute
from ..pipelines.host_pipeline import execute as _host_execute

# ---------------------------------------------------------------------------
# Domain Registry
#
# Maps system domain → pipeline execute(plan, context_id) -> DomainResult
# ---------------------------------------------------------------------------
DOMAIN_PIPELINES: dict[str, Callable] = {
    "WORK": _work_execute,
    "FIN":  _fin_execute,
    "CODE": _code_execute,
    "HOST": _host_execute,
}


def action_domain(action: str) -> str:
    """
    Derive the system pipeline domain from a plan action string.

    Action strings are prefixed by system domain (WORK_*, FIN_*), which is
    distinct from the classifier-assigned task domain in plan["domain"].

    Args:
        action: Action constant string (e.g. "WORK_QUERY", "FIN_EXPENSE").

    Returns:
        System domain string ("WORK", "FIN", …) or "UNKNOWN".
    """
    if action.startswith("WORK_"):
        return "WORK"
    if action.startswith("FIN_"):
        return "FIN"
    if action.startswith("CODE_"):
        return "CODE"
    if action.startswith("HOST_"):
        return "HOST"
    if action == "BASIC_COGNITIVE_EXECUTION":
        return "COGNITIVE"
    return "UNKNOWN"


def get_pipeline(domain: str) -> Optional[Callable]:
    """
    Return the pipeline executor for the given system domain, or None.

    Uses hybrid late-binding: if DOMAIN_PIPELINES holds the original module-level
    reference (unchanged), re-reads the attribute from the pipeline module so that
    unittest.mock @patch decorators are respected. If the entry has been replaced
    (e.g. by a test via DOMAIN_PIPELINES["WORK"] = mock), the override is used as-is.

    Args:
        domain: System domain string (e.g. "WORK", "FIN").

    Returns:
        Callable(plan, context_id) -> DomainResult, or None if unregistered.
    """
    stored = DOMAIN_PIPELINES.get(domain)
    if stored is None:
        return None
    if domain == "WORK" and stored is _work_execute:
        from ..pipelines import work_pipeline
        return work_pipeline.execute
    if domain == "FIN" and stored is _fin_execute:
        from ..pipelines import fin_pipeline
        return fin_pipeline.execute
    if domain == "CODE" and stored is _code_execute:
        from ..pipelines import code_pipeline
        return code_pipeline.execute
    if domain == "HOST" and stored is _host_execute:
        from ..pipelines import host_pipeline
        return host_pipeline.execute
    return stored
