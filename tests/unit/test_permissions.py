from skillos.authorization import (
    ABAC_DENIED_POLICY_ID,
    PERMISSION_DENIED_POLICY_ID,
    PERMISSION_NOT_REQUIRED_POLICY_ID,
    AbacPolicy,
    PermissionChecker,
    PermissionPolicy,
)


def test_permission_checker_rejects_missing_permissions() -> None:
    policies = [
        PermissionPolicy(
            skill_id="finance/close_books",
            required_permissions=["finance:write"],
        )
    ]
    roles = {"analyst": ["finance:read"]}
    checker = PermissionChecker(policies=policies, role_permissions=roles)

    decision = checker.authorize("finance/close_books", "analyst")

    assert decision.allowed is False
    assert decision.policy_id == PERMISSION_DENIED_POLICY_ID
    assert decision.missing_permissions == ["finance:write"]


def test_abac_policy_denies_matching_role() -> None:
    abac_policies = [
        AbacPolicy(
            skill_id="finance/*",
            effect="deny",
            conditions={"role": ["analyst"]},
            policy_id="finance_abac",
        )
    ]
    checker = PermissionChecker(
        policies=[],
        role_permissions={},
        abac_policies=abac_policies,
    )

    decision = checker.authorize("finance/close_books", "analyst")

    assert decision.allowed is False
    assert decision.policy_id == "finance_abac"


def test_abac_policy_denies_matching_tags() -> None:
    abac_policies = [
        AbacPolicy(
            skill_id="finance/*",
            effect="deny",
            conditions={"tags": ["sensitive"]},
        )
    ]
    checker = PermissionChecker(
        policies=[],
        role_permissions={},
        abac_policies=abac_policies,
    )

    decision = checker.authorize(
        "finance/close_books",
        "admin",
        skill_tags=["sensitive"],
    )

    assert decision.allowed is False
    assert decision.policy_id == ABAC_DENIED_POLICY_ID


def test_abac_allows_when_no_match() -> None:
    abac_policies = [
        AbacPolicy(
            skill_id="finance/*",
            effect="deny",
            conditions={"role": ["analyst"]},
        )
    ]
    checker = PermissionChecker(
        policies=[],
        role_permissions={},
        abac_policies=abac_policies,
    )

    decision = checker.authorize("finance/close_books", "admin")

    assert decision.allowed is True
    assert decision.policy_id == PERMISSION_NOT_REQUIRED_POLICY_ID
