"""Prompt injection: evidence is untrusted data and cannot change the verdict.

The mocked LLM stands in for a hijacked model (it follows the instructions
embedded in the evidence). The contract must still record a verdict derived
only from validated criterion statuses.
"""

import json

from tests.direct.conftest import (
    INJECTION_TEXT,
    deploy_with_submission,
    mock_registry,
)


def test_injected_verdict_field_is_ignored(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm, body=INJECTION_TEXT)
    direct_vm.mock_llm(
        r".*",
        json.dumps(
            {"verdict": "verified", "criteria": [{"id": "0", "status": "fail"}]}
        ),
    )

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["verdict"] == "rejected"
    assert record["reason_code"] == "REQUIRED_CRITERION_FAILED"


def test_injected_criterion_cannot_be_added(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm, body=INJECTION_TEXT)
    direct_vm.mock_llm(
        r".*",
        json.dumps(
            {
                "verdict": "verified",
                "criteria": [
                    {"id": "0", "status": "fail"},
                    {"id": "99", "status": "pass", "status_note": "injected"},
                ],
            }
        ),
    )

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert len(record["criteria_results"]) == 1
    assert record["criteria_results"][0]["criterion_id"] == "0"
    assert record["verdict"] == "rejected"


def test_injected_output_without_criteria_is_unusable(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm, body=INJECTION_TEXT)
    direct_vm.mock_llm(r".*", json.dumps({"verdict": "verified"}))

    with direct_vm.expect_revert("LLM_ERROR: unusable_model_output"):
        contract.evaluate_submission(submission_id)

    with direct_vm.expect_revert("EXPECTED: record_not_found"):
        contract.get_record(submission_id)


def test_injected_evidence_text_is_never_stored(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm, body=INJECTION_TEXT + " The registry lists no such award.")
    direct_vm.mock_llm(
        r".*",
        json.dumps({"criteria": [{"id": "0", "status": "fail"}]}),
    )

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    submission = contract.get_submission(submission_id)
    assert record["verdict"] == "rejected"
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in json.dumps(record)
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in json.dumps(submission)
