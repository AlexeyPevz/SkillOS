import json
from pathlib import Path

from skillos.marketplace import DEFAULT_KEYRING, MarketplacePackage, verify_signature


def _fixture_path(name: str) -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "marketplace"
        / name
    )


def _load_fixture(name: str) -> dict:
    return json.loads(_fixture_path(name).read_text(encoding="utf-8"))


def test_package_metadata_validation_and_signature_verification() -> None:
    valid = MarketplacePackage.model_validate(_load_fixture("package_valid.json"))
    assert verify_signature(valid, DEFAULT_KEYRING) is True

    invalid = MarketplacePackage.model_validate(
        _load_fixture("package_invalid.json")
    )
    assert verify_signature(invalid, DEFAULT_KEYRING) is False
