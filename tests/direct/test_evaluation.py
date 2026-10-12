"""Evaluation flow: state transition, verdict mapping and record contents."""

from tests.direct.conftest import (
    deploy_with_submission,
    mock_judgement,
    mock_registry,
    submit,
)


def test_all_criteria_pass_is_verified(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass")

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["verdict"] == "verified"
    assert record["reason_code"] == "ALL_REQUIRED_CRITERIA_SATISFIED"
    assert record["criteria_results"] == [
        {"criterion_id": "0", "required": True, "status": "pass"}
    ]
    assert contract.get_submission(submission_id)["status"] == "evaluated"


def test_required_criterion_failure_is_rejected(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(
        direct_deploy, criteria=["criterion one", "criterion two"]
    )
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass", "fail")

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["verdict"] == "rejected"
    assert record["reason_code"] == "REQUIRED_CRITERION_FAILED"
    assert [entry["status"] for entry in record["criteria_results"]] == ["pass", "fail"]


def test_required_criterion_unclear_is_inconclusive(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(
        direct_deploy, criteria=["criterion one", "criterion two"]
    )
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass", "unclear")

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["verdict"] == "inconclusive"
    assert record["reason_code"] == "REQUIRED_CRITERION_UNCLEAR"


def test_optional_criterion_failure_keeps_verdict(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(
        direct_deploy, optional=["optional criterion"]
    )
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass", "fail")

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["verdict"] == "verified"
    assert record["criteria_results"][1] == {
        "criterion_id": "1",
        "required": False,
        "status": "fail",
    }


def test_required_unclear_with_optional_pass_is_inconclusive(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(
        direct_deploy, optional=["optional criterion"]
    )
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "unclear", "pass")

    contract.evaluate_submission(submission_id)

    assert contract.get_record(submission_id)["verdict"] == "inconclusive"


def test_multi_source_evaluation_is_verified(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/verity_id.py")
    policy_id = contract.create_policy(
        "Two document claim",
        ["issuer_registry", "issuer_letter"],
        ["registry agrees", "issuer letter agrees"],
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
    mock_registry(direct_vm, pattern=r"registry\.example\.edu/")
    mock_judgement(direct_vm, "pass", "pass")

    contract.evaluate_submission(submission_id)

    assert contract.get_record(submission_id)["verdict"] == "verified"


def test_reevaluation_is_blocked(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass")
    contract.evaluate_submission(submission_id)

    with direct_vm.expect_revert("EXPECTED: submission_already_evaluated"):
        contract.evaluate_submission(submission_id)


def test_record_is_absent_before_evaluation(direct_vm, direct_deploy):
    contract, _, submission_id = deploy_with_submission(direct_deploy)

    with direct_vm.expect_revert("EXPECTED: record_not_found"):
        contract.get_record(submission_id)


def test_unknown_submission_reverts(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/verity_id.py")

    with direct_vm.expect_revert("EXPECTED: submission_not_found"):
        contract.evaluate_submission("sub-404")
