This repo is Assistant_OS_Labs.

External agents are bounded collaborators, not MSO, not Police, not sovereign authority.

Do not index the full repository at startup.

Read README.md first.

Explain source-of-truth hierarchy:
1. current code in assistant_os/ and ui/
2. README.md, docs/RUNTIME_TOPOLOGY.md, docs/CHAT.md
3. docs/security/, docs/operability/, docs/observability/
4. docs/brains/ and contracts/line-f/ as historical/conceptual specs
5. archive/ as historical reference only

Paths to avoid by default:
archive/
docs/brains/
contracts/line-f/
tests/
tests_generated/
var/
logs/
.claude/
node_modules/
.next/

Heavy files must not be read fully without permission:
assistant_os/webhook_server.py
assistant_os/chat_core.py
assistant_os/mso/machine_operator_adapter.py
assistant_os/agents/host_agent.py
assistant_os/classifier.py
assistant_os/integrations/notion.py
ui/components/views/chat-view.tsx
large tests

Commands forbidden without permission:
pytest
npm install
npm run build
npm run dev
python -m assistant_os --server
python run_code_api.py
scripts/*

If context is too large, ask for scope instead of going silent.

Expected response format:
files read
files modified
summary
risks
validation
recommended next files
