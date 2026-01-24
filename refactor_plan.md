# Refactoring Design: Extracting the Orchestrator

## Goal

Move business logic from `cli.py` to `orchestrator.py`.

## New Component: `SkillOrchestrator`

```python
class SkillOrchestrator:
    def __init__(self, root_path: Path):
        self.root_path = root_path
        self.registry = SkillRegistry(root_path)
        self.registry.load_all()
        # Initializes other components...

    def handle_request(
        self,
        query: str,
        user_context: UserContext,
        dry_run: bool = False,
        approval_status: str = None
    ) -> ExecutionResult:
        # 1. Route
        # 2. Budget Check
        # 3. Policy Check
        # 4. Approval Check
        # 5. Execute
        pass
```

## Migration Plan

1. **Create `skillos/orchestrator.py`**: Copy logic from `cli.py:run_query`.
2. **Refactor `cli.py:run_query`**: Instantiate `SkillOrchestrator` and call `handle_request`.
3. **Verify**: Run `poetry run skillos run ...` to ensure it still works.
