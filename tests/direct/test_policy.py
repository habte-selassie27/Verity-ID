"""Policy lifecycle and input validation, including owner-only access control."""

import pytest

from tests.direct.conftest import (
    CLAIM,
    OPTIONAL_CRITERIA,
    create_policy,
    to_hex,
)


def test_create_policy_records_policy(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    policy_id = create_policy(contract)

    assert policy_id == "pol-1"
    policy = contract.get_policy(policy_id)
    assert policy["owner"] == to_hex(direct_alice)
    assert policy["claim_description"] == CLAIM
    assert policy["evidence_types"] == ["issuer_registry"]
    assert policy["criteria"] == [
        "The issuer registry lists a completed BSc Computer Science degree."
    ]
    assert policy["optional_criteria"] == []
    assert policy["min_sources"] == 1
    assert policy["status"] == "active"
    assert policy["submission_count"] == 0


def test_policy_ids_are_sequential(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    assert create_policy(contract, claim="first claim") == "pol-1"
    assert create_policy(contract, claim="second claim") == "pol-2"
    assert contract.get_policy("pol-2")["claim_description"] == "second claim"


def test_optional_criteria_are_stored_separately(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    policy_id = create_policy(contract, optional=list(OPTIONAL_CRITERIA))

    policy = contract.get_policy(policy_id)
    assert policy["criteria"] == [
        "The issuer registry lists a completed BSc Computer Science degree."
    ]
    assert policy["optional_criteria"] == list(OPTIONAL_CRITERIA)


def test_owner_can_update_policy(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    contract.update_policy(
        policy_id,
        "Updated claim",
        ["issuer_registry", "issuer_letter"],
        ["Updated criterion"],
        [],
        2,
    )

    policy = contract.get_policy(policy_id)
    assert policy["claim_description"] == "Updated claim"
    assert policy["evidence_types"] == ["issuer_registry", "issuer_letter"]
    assert policy["criteria"] == ["Updated criterion"]
    assert policy["optional_criteria"] == []
    assert policy["min_sources"] == 2


def test_non_owner_cannot_update_policy(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("EXPECTED: policy_not_owner"):
        contract.update_policy(policy_id, "hijacked", ["issuer_registry"], ["c"], [], 1)

    direct_vm.sender = direct_alice
    assert contract.get_policy(policy_id)["claim_description"] == CLAIM


def test_non_owner_cannot_retire_policy(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("EXPECTED: policy_not_owner"):
        contract.retire_policy(policy_id)

    assert contract.get_policy(policy_id)["status"] == "active"


def test_retire_policy_is_final(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    contract.retire_policy(policy_id)
    assert contract.get_policy(policy_id)["status"] == "retired"

    with direct_vm.expect_revert("EXPECTED: policy_not_active"):
        contract.retire_policy(policy_id)
    with direct_vm.expect_revert("EXPECTED: policy_not_active"):
        contract.update_policy(policy_id, "late edit", ["issuer_registry"], ["c"], [], 1)


def test_unknown_policy_reverts(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("EXPECTED: policy_not_found"):
        contract.get_policy("pol-404")
    with direct_vm.expect_revert("EXPECTED: policy_not_found"):
        contract.retire_policy("pol-404")
    with direct_vm.expect_revert("EXPECTED: policy_not_found"):
        contract.update_policy("pol-404", "claim", ["issuer_registry"], ["c"], [], 1)


def test_eight_criteria_are_accepted(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    policy_id = create_policy(
        contract, criteria=["criterion " + str(index) for index in range(8)]
    )

    assert len(contract.get_policy(policy_id)["criteria"]) == 8


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"claim": ""}, "EXPECTED: claim_description_empty"),
        ({"claim": "   "}, "EXPECTED: claim_description_empty"),
        ({"claim": "x" * 601}, "EXPECTED: claim_description_too_long"),
        ({"criteria": []}, "EXPECTED: criteria_empty"),
        (
            {"criteria": ["criterion " + str(index) for index in range(9)]},
            "EXPECTED: criteria_too_many",
        ),
        ({"criteria": ["same", "same"]}, "EXPECTED: criterion_duplicate"),
        ({"criteria": ["x" * 301]}, "EXPECTED: criterion_too_long"),
        ({"criteria": ["ok"], "optional": ["ok"]}, "EXPECTED: criterion_duplicate"),
        ({"types": []}, "EXPECTED: evidence_types_empty"),
        ({"types": ["diploma"]}, "EXPECTED: evidence_type_not_allowed"),
        (
            {"types": ["issuer_registry", "issuer_registry"]},
            "EXPECTED: evidence_type_duplicate",
        ),
        ({"min_sources": 0}, "EXPECTED: min_sources_out_of_range"),
        ({"min_sources": 9}, "EXPECTED: min_sources_out_of_range"),
        (
            {"types": ["issuer_registry", "certificate"], "min_sources": 1},
            "EXPECTED: min_sources_below_required_evidence_types",
        ),
    ],
)
def test_create_policy_validation(
    direct_vm, direct_deploy, direct_alice, overrides, expected_error
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert(expected_error):
        create_policy(contract, **overrides)


def test_rejected_policy_is_not_stored(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("EXPECTED: criteria_empty"):
        create_policy(contract, criteria=[])

    with direct_vm.expect_revert("EXPECTED: policy_not_found"):
        contract.get_policy("pol-1")
    assert contract.list_submissions("pol-1", 0, 20) == []
