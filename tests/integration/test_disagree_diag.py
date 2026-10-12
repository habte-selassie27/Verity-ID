"""Diagnostic: does a validator disagreement actually reach consensus?

Run:  gltest tests/integration/test_disagree_diag.py -v -s

Not part of the suite - it prints the raw consensus data so the disagreement
tests can be diagnosed. Delete once the cause is known.
"""

import json

from tests.integration.conftest import (
    create_policy,
    deploy_contract,
    mock_validators,
    statuses_payload,
    submit,
    try_evaluate,
)

SPLIT = [
    statuses_payload("pass", "pass"),
    statuses_payload("pass", "pass"),
    statuses_payload("pass", "fail"),
    statuses_payload("pass", "fail"),
]


def test_disagreement_diag():
    contract = deploy_contract()
    create_policy(contract, criteria=["criterion one", "criterion two"])
    submit(contract, "pol-1")

    context = mock_validators(SPLIT)
    print("\n=== VALIDATOR SET SENT ===")
    for i, v in enumerate(context["validators"]):
        mock = v["plugin_config"]["mock_response"]["response"]
        print(f"  validator {i}: {list(mock.values())[0]}")

    receipt = try_evaluate(contract, "sub-1", context, wait_retries=8)

    print("\n=== RECEIPT IS", "None (timed out / raised)" if receipt is None else "present", "===")
    if receipt is not None:
        print(json.dumps(receipt.get("consensus_data", {}), indent=2, default=str)[:4000])
        print("status_name:", receipt.get("status_name"))

    print("\n=== IS A RECORD WRITTEN? ===")
    try:
        record = contract.get_record(args=["sub-1"]).call()
        print("RECORD EXISTS:", json.dumps(record, indent=2, default=str))
    except Exception as e:
        print("NO RECORD (view reverted):", type(e).__name__)

    try:
        submission = contract.get_submission(args=["sub-1"]).call()
        print("submission status:", submission["status"])
    except Exception as e:
        print("submission read failed:", type(e).__name__)