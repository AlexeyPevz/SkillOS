# Ralph Loop (Codex)

Source of truth:
- PRD_RALPH.json
- .ralph/prompt.md
- .ralph/progress.md
- .ralph/constitution.md

Run (PowerShell):
```
.\.ralph\ralph-loop.ps1 -MaxIterations 20
```

Run (bash):
```
bash .ralph/ralph-loop.sh
```

Defaults:
- Agent: `codex`
- Args: `exec - --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -C <repo> --output-last-message .ralph/last_message.txt`
- Termination: progress or last message contains "Promise Complete" or "<promise>DONE</promise>"

Override:
- `AGENT_CMD` and `AGENT_ARGS` env vars
- `MAX_ITERATIONS` env var (bash) or `-MaxIterations` (PowerShell)
