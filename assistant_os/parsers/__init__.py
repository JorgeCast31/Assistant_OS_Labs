"""
Parsers module for Assistant OS.

Contains specialized parsers for different input formats.
"""
from .work_create_parser import (
    WorkCreateFields,
    WorkCreateParseResult,
    parse_work_create_fields,
    parse_work_create_test_fields,
    validate_work_create_fields,
)
from .work_delete_parser import (
    DeleteQuery,
    DeleteParseResult,
    parse_work_delete_intent,
    has_delete_intent,
    generate_delete_preview,
)
from .work_update_parser import (
    TaskReference,
    ProposedChange,
    UpdateParseResult,
    parse_work_update_intent,
    has_update_intent,
    generate_update_preview,
)

__all__ = [
    # Work Create
    "WorkCreateFields",
    "WorkCreateParseResult",
    "parse_work_create_fields",
    "parse_work_create_test_fields",
    "validate_work_create_fields",
    # Work Delete
    "DeleteQuery",
    "DeleteParseResult",
    "parse_work_delete_intent",
    "has_delete_intent",
    "generate_delete_preview",
    # Work Update
    "TaskReference",
    "ProposedChange",
    "UpdateParseResult",
    "parse_work_update_intent",
    "has_update_intent",
    "generate_update_preview",
]
