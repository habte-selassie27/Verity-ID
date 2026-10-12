"""Evidence submission: state transitions, validation and pagination."""

import pytest

from tests.direct.conftest import (
    REGISTRY_URL,
    create_policy,
    submit,
    to_hex,
)


def test_submit_evidence_records_reference_only(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    submission_id = submit(contract, policy_id)

    assert submission_id == "sub-1"
    submission = contract.get_submission(submission_id)
    assert submission["policy_id"] == policy_id
    assert submission["submitter"] == to_hex(direct_alice)
    assert submission["status"] == "submitted"
    assert submission["evidence"] == [
        {"ref_type": "issuer_registry", "url": REGISTRY_URL}
    ]
    # document bodies are never stored on-chain
    assert "body" not in submission
    assert contract.get_policy(policy_id)["submission_count"] == 1


def test_submissions_from_different_senders_are_listed(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)
    submit(contract, policy_id)

    direct_vm.sender = direct_bob
    second = submit(contract, policy_id, urls=["https://registry.example.edu/verify?id=bob"])

    assert contract.list_submissions(policy_id, 0, 20) == ["sub-1", second]
    assert contract.get_submission(second)["submitter"] == to_hex(direct_bob)
    assert contract.get_policy(policy_id)["submission_count"] == 2


def test_submission_requires_active_policy(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)
    contract.retire_policy(policy_id)

    with direct_vm.expect_revert("EXPECTED: policy_not_active"):
        submit(contract, policy_id)


def test_unknown_policy_reverts(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("EXPECTED: policy_not_found"):
        submit(contract, "pol-404")


def test_unknown_submission_reverts(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/verity_id.py")

    with direct_vm.expect_revert("EXPECTED: submission_not_found"):
        contract.get_submission("sub-404")


SECOND_URL = "https://registry.example.edu/verify?id=2"


@pytest.mark.parametrize(
    ("urls", "types", "expected_error"),
    [
        ([REGISTRY_URL], [], "EXPECTED: evidence_length_mismatch"),
        ([REGISTRY_URL, SECOND_URL], ["issuer_registry"], "EXPECTED: evidence_length_mismatch"),
        ([], [], "EXPECTED: evidence_count_out_of_range"),
        (
            ["https://registry.example.edu/verify?id=" + str(index) for index in range(9)],
            ["issuer_registry"] * 9,
            "EXPECTED: evidence_count_out_of_range",
        ),
        (
            [REGISTRY_URL, SECOND_URL],
            ["issuer_registry", "diploma"],
            "EXPECTED: evidence_type_not_in_policy",
        ),
        (
            [REGISTRY_URL, SECOND_URL],
            ["issuer_registry", "issuer_registry"],
            "EXPECTED: evidence_type_missing",
        ),
        (
            [REGISTRY_URL, REGISTRY_URL],
            ["issuer_registry", "issuer_registry"],
            "EXPECTED: evidence_url_duplicate",
        ),
    ],
)
def test_submit_structure_validation(
    direct_vm, direct_deploy, direct_alice, urls, types, expected_error
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(
        contract, types=["issuer_registry", "certificate"], min_sources=2
    )

    with direct_vm.expect_revert(expected_error):
        submit(contract, policy_id, urls=urls, types=types)


def test_submit_below_min_sources(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(
        contract, types=["issuer_registry", "certificate"], min_sources=3
    )

    with direct_vm.expect_revert("EXPECTED: evidence_below_min_sources"):
        submit(
            contract,
            policy_id,
            urls=[REGISTRY_URL, SECOND_URL],
            types=["issuer_registry", "certificate"],
        )


@pytest.mark.parametrize(
    ("urls", "expected_error"),
    [
        (["ftp://registry.example.edu/verify"], "EXPECTED: evidence_url_scheme"),
        (["registry.example.edu/verify"], "EXPECTED: evidence_url_scheme"),
        ([""], "EXPECTED: evidence_url_empty"),
        (
            ["https://registry.example.edu/verify me"],
            "EXPECTED: evidence_url_whitespace",
        ),
        (
            ["https://registry.example.edu/" + "x" * 500],
            "EXPECTED: evidence_url_too_long",
        ),
    ],
)
def test_submit_url_validation(
    direct_vm, direct_deploy, direct_alice, urls, expected_error
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    with direct_vm.expect_revert(expected_error):
        submit(contract, policy_id, urls=urls)


def test_rejected_submission_is_not_stored(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    with direct_vm.expect_revert("EXPECTED: evidence_url_scheme"):
        submit(contract, policy_id, urls=["ftp://registry.example.edu/verify"])

    assert contract.list_submissions(policy_id, 0, 20) == []
    with direct_vm.expect_revert("EXPECTED: submission_not_found"):
        contract.get_submission("sub-1")


def test_all_declared_evidence_types_must_be_present(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(
        contract, types=["issuer_registry", "issuer_letter"], min_sources=2
    )

    submission_id = submit(
        contract,
        policy_id,
        urls=[
            "https://registry.example.edu/verify?id=abc123",
            "https://registry.example.edu/letter?id=abc123",
        ],
        types=["issuer_registry", "issuer_letter"],
    )

    assert len(contract.get_submission(submission_id)["evidence"]) == 2


def test_list_submissions_paginates(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)
    for index in range(3):
        submit(
            contract,
            policy_id,
            urls=["https://registry.example.edu/verify?id=" + str(index)],
        )

    assert contract.list_submissions(policy_id, 0, 2) == ["sub-1", "sub-2"]
    assert contract.list_submissions(policy_id, 1, 1) == ["sub-2"]
    assert contract.list_submissions(policy_id, 2, 20) == ["sub-3"]
    assert contract.list_submissions(policy_id, 3, 20) == []
    assert contract.list_submissions("pol-404", 0, 20) == []


@pytest.mark.parametrize(
    ("offset", "limit", "expected_error"),
    [
        (-1, 10, "EXPECTED: offset_out_of_range"),
        (0, 0, "EXPECTED: limit_out_of_range"),
        (0, 21, "EXPECTED: limit_out_of_range"),
    ],
)
def test_list_submissions_bounds(direct_vm, direct_deploy, offset, limit, expected_error):
    contract = direct_deploy("contracts/verity_id.py")

    with direct_vm.expect_revert(expected_error):
        contract.list_submissions("pol-1", offset, limit)
