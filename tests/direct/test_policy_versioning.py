"""Policy versioning: a submission is judged by the rules in force when filed.

The decisive test is `test_pending_submission_is_judged_by_frozen_version`: the
owner rewrites the policy after evidence is submitted, and the verdict must
still be derived from the original checklist. v1 has two required criteria while
v2 has one, so a contract that (incorrectly) read the live policy would record a
single result and `verified`; the frozen version records two results and
`rejected`. The two outcomes cannot be confused.
"""

from tests.direct.conftest import (
    CLAIM,
    DEFAULT_DOMAINS,
    REGISTRY_URL,
    create_policy,
    deploy_with_submission,
    mock_judgement,
    mock_registry,
    submit,
)


def _update(contract, policy_id, criteria, claim="Revised claim", min_sources=1):
    contract.update_policy(
        policy_id,
        claim,
        ["issuer_registry"],
        criteria,
        [],
        min_sources,
        list(DEFAULT_DOMAINS),
    )


def test_policy_starts_at_version_one(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    policy_id = create_policy(contract)

    policy = contract.get_policy(policy_id)
    assert policy["version"] == 1
    assert policy["claim_description"] == CLAIM
    assert contract.get_policy_version(policy_id, 1) == {
        key: policy[key]
        for key in policy
        if key not in ("submission_count",)
    }


def test_update_publishes_a_new_version_and_leaves_the_old_one_intact(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract, criteria=["original criterion"])

    _update(contract, policy_id, ["replacement criterion"])

    assert contract.get_policy(policy_id)["version"] == 2
    assert contract.get_policy(policy_id)["criteria"] == ["replacement criterion"]

    frozen = contract.get_policy_version(policy_id, 1)
    assert frozen["version"] == 1
    assert frozen["criteria"] == ["original criterion"]
    assert frozen["claim_description"] == CLAIM


def test_pending_submission_is_judged_by_frozen_version(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    # v1: two required criteria
    policy_id = create_policy(contract, criteria=["criterion one", "criterion two"])
    submission_id = submit(contract, policy_id)

    # the owner then replaces them with a single, easier criterion
    _update(contract, policy_id, ["replacement criterion"])
    assert contract.get_policy(policy_id)["criteria"] == ["replacement criterion"]
    assert contract.get_policy(policy_id)["version"] == 2

    # the submission still points at v1
    assert contract.get_submission(submission_id)["policy_version"] == 1

    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass", "fail")

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["policy_version"] == 1
    # judged by v1's two criteria -> one fails -> rejected.
    # judged by v2's single criterion this would have been `verified`.
    assert len(record["criteria_results"]) == 2
    assert [entry["status"] for entry in record["criteria_results"]] == ["pass", "fail"]
    assert record["verdict"] == "rejected"
    assert record["reason_code"] == "REQUIRED_CRITERION_FAILED"


def test_evaluation_after_retirement_still_uses_the_frozen_version(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)
    submission_id = submit(contract, policy_id)

    contract.retire_policy(policy_id)

    # retirement blocks new evidence but does not strand what was already filed
    with direct_vm.expect_revert("EXPECTED: policy_not_active"):
        submit(contract, policy_id, urls=[REGISTRY_URL + "&second=1"])

    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass")
    contract.evaluate_submission(submission_id)

    assert contract.get_record(submission_id)["verdict"] == "verified"


def test_submission_after_update_uses_the_new_version(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract, criteria=["original criterion"])

    _update(contract, policy_id, ["replacement criterion"])

    submission_id = submit(contract, policy_id)

    assert contract.get_submission(submission_id)["policy_version"] == 2
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass")
    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["policy_version"] == 2
    assert len(record["criteria_results"]) == 1


def test_get_policy_version_bounds(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    _update(contract, policy_id, ["replacement criterion"])

    assert contract.get_policy_version(policy_id, 2)["criteria"] == [
        "replacement criterion"
    ]
    for bad_version in (0, 3, -1):
        with direct_vm.expect_revert("EXPECTED: policy_version_out_of_range"):
            contract.get_policy_version(policy_id, bad_version)
    with direct_vm.expect_revert("EXPECTED: policy_not_found"):
        contract.get_policy_version("pol-404", 1)


def test_versions_are_untouched_by_later_creates(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    first = create_policy(contract, criteria=["first policy criterion"])
    second = create_policy(contract, criteria=["second policy criterion"])

    _update(contract, second, ["second policy revised"])

    assert contract.get_policy_version(first, 1)["criteria"] == [
        "first policy criterion"
    ]
    assert contract.get_policy_version(second, 1)["criteria"] == [
        "second policy criterion"
    ]


def test_deploy_helper_exposes_the_frozen_version(direct_vm, direct_deploy):
    """A freshly deployed + submitted record already carries a version."""
    contract, _, submission_id = deploy_with_submission(direct_deploy)

    assert contract.get_submission(submission_id)["policy_version"] == 1
    assert contract.get_policy("pol-1")["version"] == 1
