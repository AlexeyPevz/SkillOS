from datetime import datetime, timezone
from pathlib import Path

from skillos.budget import BudgetConfig, BudgetManager, BudgetUsageStore


def test_budget_usage_caps_enforced(tmp_path: Path) -> None:
    now = datetime(2026, 1, 5, tzinfo=timezone.utc)

    daily_store = BudgetUsageStore(tmp_path / "daily.json")
    daily_config = BudgetConfig(
        per_request_limit=5.0,
        daily_limit=2.0,
        monthly_limit=100.0,
        low_remaining_threshold=0.0,
        standard_cost=1.0,
        cheap_cost=1.0,
    )
    daily_manager = BudgetManager(daily_store, daily_config, now_provider=lambda: now)

    assert daily_manager.authorize().allowed is True
    assert daily_manager.authorize().allowed is True
    blocked_daily = daily_manager.authorize()
    assert blocked_daily.allowed is False
    assert blocked_daily.reason == "daily_limit_exceeded"

    monthly_store = BudgetUsageStore(tmp_path / "monthly.json")
    monthly_config = BudgetConfig(
        per_request_limit=5.0,
        daily_limit=100.0,
        monthly_limit=2.0,
        low_remaining_threshold=0.0,
        standard_cost=1.0,
        cheap_cost=1.0,
    )
    monthly_manager = BudgetManager(
        monthly_store, monthly_config, now_provider=lambda: now
    )

    assert monthly_manager.authorize().allowed is True
    assert monthly_manager.authorize().allowed is True
    blocked_monthly = monthly_manager.authorize()
    assert blocked_monthly.allowed is False
    assert blocked_monthly.reason == "monthly_limit_exceeded"
