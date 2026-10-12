"""Evidence fetch failures: deterministic error prefixes, no record, retryable."""

import pytest

from tests.direct.conftest import (
    REGISTRY_BODY,
    REGISTRY_PATTERN,
    deploy_with_submission,
    mock_judgement,
    mock_registry,
    submit,
)


def _evaluate_expecting_error(direct_vm, contract, submission_id, message):
    with direct_vm.expect_revert(message):
        contract.evaluate_submission(submission_id)
    with direct_vm.expect_revert("EXPECTED: record_not_found"):
        contract.get_record(submission_id)
    assert contract.get_submission(submission_id)["status"] == "submitted"


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (429, "TRANSIENT: evidence_source_unavailable:0"),
        (500, "TRANSIENT: evidence_source_unavailable:0"),
        (503, "TRANSIENT: evidence_source_unavailable:0"),
        (403, "EXTERNAL: evidence_source_rejected:0"),
        (404, "EXTERNAL: evidence_source_rejected:0"),
    ],
)
def test_http_status_maps_to_error_prefix(
    direct_vm, direct_deploy, status_code, expected_error
):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm, status=status_code)

    _evaluate_expecting_error(direct_vm, contract, submission_id, expected_error)


def test_missing_body_is_external_error(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    direct_vm.mock_web(
        REGISTRY_PATTERN,
        {
            "response": {"status": 200, "headers": {}, "body": None},
            "method": "GET",
        },
    )

    _evaluate_expecting_error(
        direct_vm, contract, submission_id, "EXTERNAL: evidence_source_empty:0"
    )


def test_whitespace_only_body_is_external_error(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm, body="   \n\t  ")

    _evaluate_expecting_error(
        direct_vm, contract, submission_id, "EXTERNAL: evidence_source_empty:0"
    )


def test_unmocked_source_does_not_write_a_record(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_judgement(direct_vm, "pass")

    _evaluate_expecting_error(direct_vm, contract, submission_id, "No web mock")


def test_failure_index_identifies_the_source(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/verity_id.py")
    policy_id = contract.create_policy(
        "Two source claim",
        ["issuer_registry", "issuer_letter"],
        ["criterion"],
        [],
        2,
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
    mock_registry(direct_vm, pattern=r"registry\.example\.edu/verify")
    mock_registry(direct_vm, pattern=r"registry\.example\.edu/letter", status=500)

    _evaluate_expecting_error(
        direct_vm, contract, submission_id, "TRANSIENT: evidence_source_unavailable:1"
    )


def test_failed_submission_can_be_retried(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm, status=500)
    _evaluate_expecting_error(
        direct_vm, contract, submission_id, "TRANSIENT: evidence_source_unavailable:0"
    )

    direct_vm.clear_mocks()
    mock_registry(direct_vm, body=REGISTRY_BODY)
    mock_judgement(direct_vm, "pass")

    contract.evaluate_submission(submission_id)

    assert contract.get_record(submission_id)["verdict"] == "verified"
    assert contract.get_submission(submission_id)["status"] == "evaluated"
