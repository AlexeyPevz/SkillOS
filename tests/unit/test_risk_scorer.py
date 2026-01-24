from skillos.risk_scorer import HIGH_RISK_THRESHOLD, RiskScorer


def test_risk_scorer_flags_delete_and_bulk_updates() -> None:
    scorer = RiskScorer()

    delete_assessment = scorer.assess("delete all invoices", "finance/delete")
    bulk_update_assessment = scorer.assess(
        "bulk update customer records", "crm/bulk_update_customers"
    )

    assert delete_assessment.score >= HIGH_RISK_THRESHOLD
    assert bulk_update_assessment.score >= HIGH_RISK_THRESHOLD
