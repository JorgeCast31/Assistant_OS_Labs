from pathlib import Path
from pprint import pprint
from uuid import uuid4

from assistant_os.sandbox.authorized_plan import AuthorizedPlan
from assistant_os.sandbox.audit_store import AuditStore
from assistant_os.sandbox.container_backend import ContainerBackend
from assistant_os.sandbox.runner_api import RunnerAPI

PLAYGROUND = Path(r"C:\Dev\assistant_OS_test-playground")
AUDIT_PATH = Path(r"C:\Dev\assistant_os\var\audit\background_test.jsonl")

def main():
    plan = AuthorizedPlan(
        execution_id=str(uuid4()),
        plan_id=str(uuid4()),
        authorized_plan_hash="sha256:bg-test-001",
        policy_id="default",
        runtime_profile="python3.11",
        capability_scope=["code.run"],
    )

    audit = AuditStore(AUDIT_PATH)
    backend = ContainerBackend()
    runner = RunnerAPI(backend=backend)

    code = '''
print("Background se refiere a procesos que se ejecutan en segundo plano sin bloquear la ejecución principal.")
print("ASSISTANT_OS WAS HERE")
'''

    result = runner.execute(
        code=code,
        workspace=str(PLAYGROUND),
        runtime="python3.11",
        entry_point="background_demo.py",
        authorized_plan=plan,
        secret_refs=[],
        audit_log=audit,
    )

    print("\n=== EXECUTION RESULT ===")
    pprint(result.to_dict())

if __name__ == "__main__":
    main()