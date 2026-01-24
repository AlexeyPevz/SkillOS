import asyncio
import concurrent.futures
import pytest
from pathlib import Path
from skillos.orchestrator import Orchestrator
from skillos.budget import BudgetManager, BudgetUsageStore, BudgetConfig, BudgetUsage
from skillos.storage import file_lock
from datetime import datetime, timezone

def test_budget_lock_stress(tmp_path):
    budget_file = tmp_path / "budget.json"
    store = BudgetUsageStore(budget_file)
    day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Initial state
    store.save(BudgetUsage(daily={day_key: 0.0}, monthly={}))
    
    def update_budget(amount):
        from skillos.storage import file_lock
        for _ in range(10):
            with file_lock(budget_file):
                usage = store.load()
                current = usage.daily.get(day_key, 0.0)
                usage.daily[day_key] = current + amount
                store.save(usage)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(update_budget, 1.0) for _ in range(10)]
        concurrent.futures.wait(futures)
    
    final_data = store.load()
    # 10 threads * 10 updates * 1.0 = 100.0
    assert final_data.daily[day_key] == 100.0

def test_orchestrator_recursion_guard(tmp_path):
    # Setup skills that call each other
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    (skills_root / "metadata").mkdir()
    (skills_root / "implementations").mkdir()
    
    orch = Orchestrator(skills_root)
    
    from skillos.orchestrator import _CALL_STACK
    
    token = _CALL_STACK.set(["skill_a", "skill_b"])
    try:
        from skillos.execution_planner import ExecutionPlan
        plan = ExecutionPlan(
            skill_id="skill_a",
            internal_skill_id="skill_a",
            payload="test"
        )
        with pytest.raises(RecursionError, match="Circular dependency"):
            orch._execute_skill(plan, logger=None, debug_trace=None, request_start=0)
    finally:
        _CALL_STACK.reset(token)

def test_max_depth_guard(tmp_path):
    orch = Orchestrator(tmp_path)
    from skillos.orchestrator import _CALL_STACK, MAX_CALL_DEPTH
    
    token = _CALL_STACK.set(["s"] * MAX_CALL_DEPTH)
    try:
        with pytest.raises(RecursionError, match="Max call depth exceeded"):
            orch.run_query("test")
    finally:
        _CALL_STACK.reset(token)
