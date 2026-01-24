from datetime import datetime, timezone
from pathlib import Path

from skillos.budget import BudgetConfig, BudgetManager, BudgetUsageStore


def test_budget_blocks_expensive_request(tmp_path: Path) -> None:
    store = BudgetUsageStore(tmp_path / "usage.json")
    config = BudgetConfig(
        per_request_limit=0.5,
        daily_limit=10.0,
        monthly_limit=10.0,
        low_remaining_threshold=0.0,
        standard_cost=1.0,
        cheap_cost=0.5,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manager = BudgetManager(store, config, now_provider=lambda: now)

    result = manager.authorize()

    assert result.allowed is False
    assert result.reason == "per_request_limit_exceeded"


def test_low_remaining_budget_selects_cheaper_model(tmp_path: Path) -> None:
    store = BudgetUsageStore(tmp_path / "usage.json")
    config = BudgetConfig(
        per_request_limit=5.0,
        daily_limit=1.0,
        monthly_limit=10.0,
        low_remaining_threshold=1.5,
        standard_cost=1.0,
        cheap_cost=0.4,
    )
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    manager = BudgetManager(store, config, now_provider=lambda: now)

    result = manager.authorize()

    assert result.allowed is True
    assert result.model == config.cheap_model
    assert result.estimated_cost == config.cheap_cost
