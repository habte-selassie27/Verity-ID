"""End-to-end VerityID flows against a live GenLayer node.

Run with: gltest tests/integration/ -v -s

`gltest.config.yaml` selects StudioNet by default (gasless, no local Docker
needed). Use `gltest --network localnet` to run against a local simulator.

These tests exercise the real leader/validator split through consensus. Web and
LLM are mocked per-validator via `transaction_context`, which is what lets us
drive agreement and disagreement deterministically without a real model.
"""

import json

import pytest
from gltest.assertions import tx_execution_failed, tx_execution_succeeded

from tests.integration.conftest import (
    REGISTRY_URL,
    assert_no_record,
    create_policy,
    deploy_contract,
    evaluate,
    mock_validators,
    statuses_payload,
    submit,
    try_evaluate,
)

pytestmark = pytest.mark.integration

# Enough validators for a majority while keeping runs short.
AGREEING_VALIDATORS = 3


# --------------------------------------------------------------------------
# Full flow: deploy -> create policy -> submit -> evaluate -> read record
# --------------------------------------------------------------------------
def test_full_flow_reaches_verified():
    contract = deploy_contract()

    assert tx_execution_succeeded(create_policy(contract))

    policy = contract.get_policy(args=["pol-1"]).call()
    assert policy["claim_description"].startswith("The holder was awarded")
    assert policy["evidence_types"] == ["issuer_registry"]
    assert policy["status"] == "active"
    assert policy["submission_count"] == 0

    assert tx_execution_succeeded(submit(contract, "pol-1"))

    assert contract.get_submission(args=["sub-1"]).call()["status"] == "submitted"
    assert contract.get_policy(args=["pol-1"]).call()["submission_count"] == 1

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators([statuses_payload("pass", "pass")] * AGREEING_VALIDATORS),
    )
    assert tx_execution_succeeded(receipt)

    record = contract.get_record(args=["sub-1"]).call()
    assert record["verdict"] == "verified"
    assert record["reason_code"] == "ALL_REQUIRED_CRITERIA_SATISFIED"
    # The default policy has one required and one optional criterion.
    assert record["criteria_results"] == [
        {"criterion_id": "0", "required": True, "status": "pass"},
        {"criterion_id": "1", "required": False, "status": "pass"},
    ]
    assert contract.get_submission(args=["sub-1"]).call()["status"] == "evaluated"


# --------------------------------------------------------------------------
# Verdict mapping on realistic evidence
# --------------------------------------------------------------------------
def test_evidence_contradicting_criterion_is_rejected():
    contract = deploy_contract()
    create_policy(contract, criteria=["criterion one", "criterion two"])
    submit(contract, "pol-1")

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators([statuses_payload("pass", "fail")] * AGREEING_VALIDATORS),
    )
    assert tx_execution_succeeded(receipt)

    record = contract.get_record(args=["sub-1"]).call()
    assert record["verdict"] == "rejected"
    assert record["reason_code"] == "REQUIRED_CRITERION_FAILED"


def test_ambiguous_evidence_is_inconclusive():
    contract = deploy_contract()
    create_policy(contract, criteria=["criterion one", "criterion two"])
    submit(contract, "pol-1")

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators([statuses_payload("pass", "unclear")] * AGREEING_VALIDATORS),
    )
    assert tx_execution_succeeded(receipt)

    record = contract.get_record(args=["sub-1"]).call()
    assert record["verdict"] == "inconclusive"
    assert record["reason_code"] == "REQUIRED_CRITERION_UNCLEAR"


def test_optional_criterion_failure_does_not_change_verdict():
    contract = deploy_contract()
    create_policy(contract)
    submit(contract, "pol-1")

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators([statuses_payload("pass", "fail")] * AGREEING_VALIDATORS),
    )
    assert tx_execution_succeeded(receipt)

    record = contract.get_record(args=["sub-1"]).call()
    assert record["verdict"] == "verified"
    assert record["criteria_results"][1] == {
        "criterion_id": "1",
        "required": False,
        "status": "fail",
    }


# --------------------------------------------------------------------------
# Equivalence: different wording, same meaning -> still equivalent
# --------------------------------------------------------------------------
def test_validators_agree_despite_different_key_names_and_order():
    """Key aliases and array ordering must not break equivalence."""
    contract = deploy_contract()
    create_policy(contract, criteria=["criterion one", "criterion two"])
    submit(contract, "pol-1")

    canonical = statuses_payload("pass", "pass")

    # Same statuses, different key names, reversed order, alias for "pass".
    reordered = {
        "criterion_results": [
            {"criterion_id": "1", "result": "supported"},
            {"criterion_id": "0", "judgement": "satisfied"},
        ]
    }

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators([canonical, reordered, canonical, reordered]),
    )
    assert tx_execution_succeeded(receipt)
    assert contract.get_record(args=["sub-1"]).call()["verdict"] == "verified"


def test_validators_agree_when_some_are_unclear_on_optional_criterion():
    contract = deploy_contract()
    create_policy(contract)
    submit(contract, "pol-1")

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators(
            [
                statuses_payload("pass", "pass"),
                statuses_payload("pass", "unclear"),
                statuses_payload("pass", "pass"),
                statuses_payload("pass", "unclear"),
            ]
        ),
    )
    assert tx_execution_succeeded(receipt)
    assert contract.get_record(args=["sub-1"]).call()["verdict"] == "verified"


def test_validators_agree_when_one_sends_unknown_status():
    """An out-of-enum status normalizes to unclear, tolerated on an optional criterion."""
    contract = deploy_contract()
    create_policy(contract)
    submit(contract, "pol-1")

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators(
            [
                statuses_payload("pass", "pass"),
                statuses_payload("pass", "banana"),
                statuses_payload("pass", "pass"),
                statuses_payload("pass", "banana"),
            ]
        ),
    )
    assert tx_execution_succeeded(receipt)
    assert contract.get_record(args=["sub-1"]).call()["verdict"] == "verified"


# --------------------------------------------------------------------------
# Disagreement -> no record
# --------------------------------------------------------------------------
def test_required_criterion_disagreement_writes_no_record():
    """A required criterion that validators judge differently is not equivalent.

    Two validators say `pass`, two say `fail` on the required criterion. No
    majority can form, so the transaction is never accepted.
    """
    contract = deploy_contract()
    create_policy(contract, criteria=["criterion one", "criterion two"])
    submit(contract, "pol-1")

    receipt = try_evaluate(
        contract,
        "sub-1",
        mock_validators(
            [
                statuses_payload("pass", "pass"),
                statuses_payload("pass", "pass"),
                statuses_payload("pass", "fail"),
                statuses_payload("pass", "fail"),
            ]
        ),
        wait_retries=5,
    )

    if receipt is not None:
        assert tx_execution_failed(receipt)
    assert_no_record(contract, "sub-1")


def test_verdict_flip_disagreement_writes_no_record():
    """Both sides derive `rejected`, but from mirrored statuses -> not equivalent.

    This is the case a verdict-only comparison would wrongly accept.
    """
    contract = deploy_contract()
    create_policy(contract, criteria=["criterion one", "criterion two"])
    submit(contract, "pol-1")

    receipt = try_evaluate(
        contract,
        "sub-1",
        mock_validators(
            [
                statuses_payload("pass", "fail"),
                statuses_payload("pass", "fail"),
                statuses_payload("fail", "pass"),
                statuses_payload("fail", "pass"),
            ]
        ),
        wait_retries=5,
    )

    if receipt is not None:
        assert tx_execution_failed(receipt)
    assert_no_record(contract, "sub-1")


# --------------------------------------------------------------------------
# Failure paths leave no record
# --------------------------------------------------------------------------
def test_unreachable_evidence_writes_no_record():
    contract = deploy_contract()
    create_policy(contract)
    submit(contract, "pol-1")

    broken_web = {
        "nondet_web_request": {
            REGISTRY_URL: {"method": "GET", "status": 503, "body": ""}
        }
    }

    receipt = try_evaluate(
        contract,
        "sub-1",
        mock_validators(
            [statuses_payload("pass")] * AGREEING_VALIDATORS, web=broken_web
        ),
        wait_retries=5,
    )

    if receipt is not None:
        assert tx_execution_failed(receipt, match_std_err="TRANSIENT")
    assert_no_record(contract, "sub-1")


def test_unusable_model_output_writes_no_record():
    contract = deploy_contract()
    create_policy(contract)
    submit(contract, "pol-1")

    receipt = try_evaluate(
        contract,
        "sub-1",
        mock_validators(["this is not json at all"] * AGREEING_VALIDATORS),
        wait_retries=5,
    )

    if receipt is not None:
        assert tx_execution_failed(receipt, match_std_err="LLM_ERROR")
    assert_no_record(contract, "sub-1")


# --------------------------------------------------------------------------
# Deterministic behaviour on-chain (no non-determinism involved)
# --------------------------------------------------------------------------
def test_retired_policy_rejects_new_submissions():
    contract = deploy_contract()
    create_policy(contract)
    create_policy(contract)

    assert tx_execution_succeeded(contract.retire_policy(args=["pol-1"]).transact())
    assert contract.get_policy(args=["pol-1"]).call()["status"] == "retired"

    rejected = submit(contract, "pol-1")
    assert tx_execution_failed(rejected, match_std_err="EXPECTED: policy_not_active")


def test_reevaluation_is_blocked():
    contract = deploy_contract()
    create_policy(contract)
    submit(contract, "sub-1")

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators([statuses_payload("pass")] * AGREEING_VALIDATORS),
    )
    assert tx_execution_succeeded(receipt)

    rejected = evaluate(
        contract, "sub-1", mock_validators([statuses_payload("pass")]), wait_retries=5
    )
    assert tx_execution_failed(
        rejected, match_std_err="EXPECTED: submission_already_evaluated"
    )


def test_pagination_lists_submissions():
    contract = deploy_contract()
    create_policy(contract)

    for _ in range(3):
        submit(contract, "pol-1")

    assert contract.get_policy(args=["pol-1"]).call()["submission_count"] == 3
    assert contract.list_submissions(args=["pol-1", 0, 2]).call() == ["sub-1", "sub-2"]
    assert contract.list_submissions(args=["pol-1", 2, 5]).call() == ["sub-3"]


def test_evidence_body_is_never_stored_on_chain():
    """Privacy guarantee: only the URL and normalized statuses are persisted."""
    contract = deploy_contract()
    create_policy(contract)
    submit(contract, "pol-1")

    receipt = evaluate(
        contract,
        "sub-1",
        mock_validators([statuses_payload("pass", "pass")] * AGREEING_VALIDATORS),
    )
    assert tx_execution_succeeded(receipt)

    stored = json.dumps(
        {
            "submission": contract.get_submission(args=["sub-1"]).call(),
            "record": contract.get_record(args=["sub-1"]).call(),
        }
    )

    # The reference is stored...
    assert REGISTRY_URL in stored
    # ...but not the fetched body, and nothing beyond normalized statuses.
    assert "Holder: A. Example" not in stored
    assert "conferred 2024" not in stored
    assert "Status: awarded" not in stored
    assert "Example University" not in stored