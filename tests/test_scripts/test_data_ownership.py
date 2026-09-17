from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts.data_ownership import (
    DEFAULT_DOCUMENT,
    DEFAULT_MANIFEST,
    OwnershipError,
    load_contract,
    render_markdown,
    validate_contract,
)


def test_default_contract_is_valid_and_document_is_current() -> None:
    contract = load_contract()

    assert {item["id"] for item in contract["classes"]} >= {
        "raw",
        "derived",
        "artifact",
        "scratch",
        "quarantine",
        "logs",
    }
    assert render_markdown(contract) == DEFAULT_DOCUMENT.read_text()


def test_groups_can_be_reassigned_without_changing_workload_identities(tmp_path: Path) -> None:
    manifest = tmp_path / "ownership.toml"
    source = (
        DEFAULT_MANIFEST.read_text()
        .replace(
            'display_name = "Research data owners"',
            'display_name = "Systematic strategies data council"',
        )
        .replace(
            'contact = "team:research-data-owners"',
            'contact = "mailto:systematic-data@example.com"',
        )
    )
    manifest.write_text(source)

    contract = load_contract(manifest)

    assert contract["groups"]["research"]["display_name"] == "Systematic strategies data council"
    assert set(contract["actors"]) == {"control", "feed", "job", "notebook", "recovery"}


def test_unknown_group_and_actor_references_are_rejected() -> None:
    contract = deepcopy(load_contract())
    contract["classes"][0]["owner_group"] = "missing_group"
    with pytest.raises(OwnershipError, match="unknown group"):
        validate_contract(contract)

    contract = deepcopy(load_contract())
    contract["classes"][0]["writers"] = ["missing_actor"]
    with pytest.raises(OwnershipError, match="unknown actor"):
        validate_contract(contract)


def test_missing_required_class_is_rejected() -> None:
    contract = deepcopy(load_contract())
    contract["classes"] = [item for item in contract["classes"] if item["id"] != "quarantine"]

    with pytest.raises(OwnershipError, match="missing required data classes: quarantine"):
        validate_contract(contract)


def test_overlapping_prefixes_are_rejected() -> None:
    contract = deepcopy(load_contract())
    derived = next(item for item in contract["classes"] if item["id"] == "derived")
    derived["prefix"] = "raw/derived/"

    with pytest.raises(OwnershipError, match="overlap"):
        validate_contract(contract)


def test_retention_days_must_be_positive_whole_numbers() -> None:
    contract = deepcopy(load_contract())
    scratch = next(item for item in contract["classes"] if item["id"] == "scratch")
    scratch["retention"]["delete_after_days"] = 0

    with pytest.raises(OwnershipError, match="positive whole number"):
        validate_contract(contract)
