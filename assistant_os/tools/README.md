# Tool Architecture — Assistant OS

## What is a Tool?

A Tool is a **stateless technical capability** that executes one
external operation and returns a `ToolResult`.

Tools are the interface between domain pipelines and external providers
(Notion, Google Sheets, LLMs, databases, etc.). They contain no domain
semantics and perform no interpretation.

```
Pipeline → Tool.execute(input) → ToolResult → Pipeline interprets → DomainResult
```

## Contracts

### `Tool` (base class)

```python
class Tool(ABC):
    def execute(self, input: dict) -> ToolResult:
        ...
```

Every Tool implements `execute()`. Input and output are dictionaries or
typed containers. No domain objects pass through this layer.

### `ToolResult`

```python
@dataclass
class ToolResult:
    ok: bool
    data: dict | None
    error: ToolError | None
    metadata: dict
```

- `ok=True` → `error` is `None`, `data` contains the provider response.
- `ok=False` → `error` is a `ToolError`, `data` is `None`.

### `ToolError`

```python
@dataclass
class ToolError:
    code: str       # Machine-readable identifier
    message: str    # Human-readable description
    provider: str   # "notion", "google", "llm", etc.
```

## Provider directories

| Directory      | Provider            |
|----------------|---------------------|
| `notion/`      | Notion API          |
| `google/`      | Google Sheets/Drive |
| `llm/`         | LLM providers       |

## Notion tools

| Tool                  | Wraps                | Used by                          |
|-----------------------|----------------------|----------------------------------|
| `QueryDatabaseTool`   | `query_work_db`      | `work_pipeline._work_query_execute` |
| `UpdatePageTool`      | `update_work_item`   | `work_pipeline._work_update_bulk_execute`, `webhook_server._execute_work_update` |
| `CreatePageTool`      | `create_work_item`   | `webhook_server._execute_work_create` |

## Google tools

| Tool                    | Wraps                  | Used by                          |
|-------------------------|------------------------|----------------------------------|
| `AppendExpenseRowTool`  | `append_expense_row`   | `webhook_server._handle_fin_commit_impl`, `_handle_fin_expense`, `_handle_fin_expense_batch`, `_handle_fin_expense_confirm` |

**Important:** `AppendExpenseRowTool` is a pure technical append. It accepts already-canonicalized fields.
Canonicalization (responsable/categoria/metodo_pago lookup) is the responsibility of the caller
via `pipelines/fin_normalization.py` — it must NOT be moved into the tool.

## How pipelines use tools

1. Import the tool inside the execution function (lazy import for patchability).
2. Instantiate and call `execute()`.
3. Check `tool_result.ok`.
4. Convert to `DomainResult` — never return `ToolResult` to the kernel.

```python
from ..tools.notion.query_database_tool import QueryDatabaseTool

tool_result = QueryDatabaseTool().execute({"filters": filters, "limit": 20})

if not tool_result.ok:
    return make_domain_result(ok=False, error={...})

items = tool_result.data["items"]
```

## What tools must never do

- Return `DomainResult` — tools know nothing about domains.
- Import from `core/` (orchestrator, policy, semantic, planning, routing, context).
- Call other tools (tools are not composable at this layer).
- Store state between calls (tools are stateless).
- Perform semantic interpretation (that belongs in the pipeline).
- Raise unhandled exceptions — always return `ToolResult(ok=False, ...)`.

## Test patchability

Tools lazy-import integration functions from `webhook_server` (not
directly from `integrations.*`) so that existing test patches applied
to `assistant_os.webhook_server.*` remain effective.
