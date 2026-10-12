"""Defensive handling of LLM output: malformed, aliased and out-of-range values."""

import json

import pytest

from tests.direct.conftest import deploy_with_submission, mock_registry

LLM_ERROR = "LLM_ERROR: unusable_model_output"


def _evaluate_expecting_error(direct_vm, contract, submission_id, message):
    with direct_vm.expect_revert(message):
        contract.evaluate_submission(submission_id)
    # no record is written and the submission stays retryable
    with direct_vm.expect_revert("EXPECTED: record_not_found"):
        contract.get_record(submission_id)
    assert contract.get_submission(submission_id)["status"] == "submitted"


@pytest.mark.parametrize(
    "raw",
    [
        "the model rambled instead of answering",
        "",
        json.dumps({"verdict": "verified"}),
        json.dumps({"criteria": "pass"}),
        json.dumps([{"id": "0", "status": "pass"}]),
        "```json\nnot json at all\n```",
    ],
)
def test_unusable_model_output_reverts(direct_vm, direct_deploy, raw):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm)
    direct_vm.mock_llm(r".*", raw)

    _evaluate_expecting_error(direct_vm, contract, submission_id, LLM_ERROR)


def test_code_fenced_json_is_salvaged(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm)
    direct_vm.mock_llm(
        r".*", '```json\n{"criteria": [{"id": "0", "status": "pass"}]}\n```'
    )

    contract.evaluate_submission(submission_id)

    assert contract.get_record(submission_id)["verdict"] == "verified"


def test_trailing_prose_around_json_is_salvaged(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm)
    direct_vm.mock_llm(
        r".*",
        'Here is the answer: {"criteria": [{"id": "0", "status": "fail"}]} hope it helps',
    )

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["verdict"] == "rejected"
    assert record["criteria_results"][0]["status"] == "fail"


@pytest.mark.parametrize(
    ("entries", "expected_status", "expected_verdict"),
    [
        ([{"id": "0", "status": "maybe"}], "unclear", "inconclusive"),
        ([{"id": "0", "status": 123}], "unclear", "inconclusive"),
        ([{"id": "0", "status": None}], "unclear", "inconclusive"),
        ([{"id": "0"}], "unclear", "inconclusive"),
        ([], "unclear", "inconclusive"),
        ([{"status": "pass"}], "unclear", "inconclusive"),
        ([{"id": "0", "status": "PASSED"}], "pass", "verified"),
        ([{"id": "0", "status": "Not Supported"}], "fail", "rejected"),
        ([{"id": "0", "status": True}], "pass", "verified"),
        ([{"id": "0", "status": False}], "fail", "rejected"),
        (
            [{"criterion_id": "0", "result": "satisfied"}],
            "pass",
            "verified",
        ),
        ([{"index": 0, "judgement": "unsatisfied"}], "fail", "rejected"),
        (
            [{"id": "0", "status": "fail"}, {"id": "99", "status": "pass"}],
            "fail",
            "rejected",
        ),
        (
            [{"id": "0", "status": "fail"}, {"id": "0", "status": "pass"}],
            "fail",
            "rejected",
        ),
        (
            [{"id": 0, "status": "pass", "verdict": "rejected"}],
            "pass",
            "verified",
        ),
    ],
)
def test_status_normalization(
    direct_vm, direct_deploy, entries, expected_status, expected_verdict
):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm)
    direct_vm.mock_llm(r".*", json.dumps({"criteria": entries}))

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["criteria_results"][0]["status"] == expected_status
    assert record["verdict"] == expected_verdict


def test_key_aliases_for_criteria_list(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm)
    direct_vm.mock_llm(
        r".*", json.dumps({"criterion_results": [{"criterion_id": "0", "result": "pass"}]})
    )

    contract.evaluate_submission(submission_id)

    assert contract.get_record(submission_id)["verdict"] == "verified"


def test_missing_criterion_becomes_unclear(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(
        direct_deploy, criteria=["criterion one", "criterion two"]
    )
    mock_registry(direct_vm)
    direct_vm.mock_llm(r".*", json.dumps({"criteria": [{"id": "0", "status": "pass"}]}))

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert [entry["status"] for entry in record["criteria_results"]] == ["pass", "unclear"]
    assert record["verdict"] == "inconclusive"
