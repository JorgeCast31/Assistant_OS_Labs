"""
sandbox — controlled code execution subsystem for AssistantOS.

Public surface
--------------
    from assistant_os.sandbox.runner_api import RunnerAPI, ALLOWED_RUNTIMES
    from assistant_os.sandbox.execution_result import ExecutionResult
    from assistant_os.sandbox.container_backend import ContainerBackend
    from assistant_os.sandbox.workspace_model import WorkspaceModel
    from assistant_os.sandbox.authorized_plan import AuthorizedPlan
    from assistant_os.sandbox.artifact_policy import ArtifactPolicy

Package layout
--------------
    execution_result.py   — ExecutionResult, ExecutionMetadata dataclasses
    execution_backend.py  — Abstract ExecutionBackend interface
    workspace_model.py    — Three-directory workspace model (input/output/out)
    container_backend.py  — Docker-based ContainerBackend (hardened)
    runner_api.py         — RunnerAPI facade (single entry point)
    authorized_plan.py    — AuthorizedPlan execution authorization binding
    artifact_policy.py    — ArtifactPolicy, ArtifactRecord, ArtifactManifest

Design constraints (v0 MVP)
----------------------------
- No network inside the container (--network none)
- No pip install / apt install inside the container
- Fixed base image: python:3.11-slim
- Only runtime "python3.11" is allowed
- Memory and CPU capped per execution
- PID limit enforced (--pids-limit)
- Non-root execution (--user 65534)
- Read-only root filesystem (--read-only + --tmpfs /tmp)
- Timeout enforced; container killed on expiry
- Workspace sub-dirs cleaned after every execution (always)

Secret injection
----------------
- Secrets are resolved via assistant_os.secrets.SecretInjector
- RunnerAPI accepts secret_refs + injector for ephemeral injection
- Secrets are provisioned as --env-file (not --env) to avoid process leaks
- Env file is deleted unconditionally in the finally block
- No secret value persisted to workspace, artifacts, logs, or metadata
"""
