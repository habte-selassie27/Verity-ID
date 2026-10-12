"""The equivalence rule: what a validator accepts from a leader.

`direct_vm.run_validator()` re-runs the validator captured by the contract's
`gl.vm.run_nondet` call, optionally with a different leader result.
"""

import warnings

from tests.direct.conftest import (
    deploy_with_submission,
    mock_judgement,
    mock_registry,
)


def _evaluate_and_get_validator(direct_vm, direct_deploy, **policy):
    contract, _, submission_id = deploy_with_submission(direct_deploy, **policy)
    required_count = len(policy.get("criteria") or ["default criterion"])
    optional_count = len(policy.get("optional") or [])
    mock_registry(direct_vm)
    mock_judgement(direct_vm, *(["pass"] * (required_count + optional_count)))
    contract.evaluate_submission(submission_id)
    return contract, submission_id


def test_validator_agrees_when_it_recomputes_the_same_result(direct_vm, direct_deploy):
    contract, _ = _evaluate_and_get_validator(
        direct_vm, direct_deploy, criteria=["criterion one", "criterion two"]
    )

    assert direct_vm.run_validator() is True


def test_validator_rejects_required_criterion_disagreement(direct_vm, direct_deploy):
    contract, _ = _evaluate_and_get_validator(
        direct_vm, direct_deploy, criteria=["criterion one", "criterion two"]
    )

    leader_claims_failure = {
        "criteria": [
            {"id": "0", "status": "fail"},
            {"id": "1", "status": "pass"},
        ]
    }

    assert direct_vm.run_validator(leader_result=leader_claims_failure) is False


def test_validator_rejects_missing_criterion(direct_vm, direct_deploy):
    contract, _ = _evaluate_and_get_validator(
        direct_vm, direct_deploy, criteria=["criterion one", "criterion two"]
    )

    assert (
        direct_vm.run_validator(leader_result={"criteria": [{"id": "0", "status": "pass"}]})
        is False
    )


def test_validator_rejects_malformed_leader_payload(direct_vm, direct_deploy):
    contract, _ = _evaluate_and_get_validator(direct_vm, direct_deploy)

    assert direct_vm.run_validator(leader_result={"criteria": "pass"}) is False
    assert direct_vm.run_validator(leader_result="pass") is False
    assert direct_vm.run_validator(leader_result={"criteria": []}) is False


def test_validator_rejects_leader_error(direct_vm, direct_deploy):
    contract, _ = _evaluate_and_get_validator(direct_vm, direct_deploy)

    assert (
        direct_vm.run_validator(
            leader_error=Exception("TRANSIENT: evidence_source_unavailable:0")
        )
        is False
    )


def test_validator_tolerates_optional_unclear_versus_definite(
    direct_vm, direct_deploy
):
    contract, _ = _evaluate_and_get_validator(
        direct_vm, direct_deploy, optional=["optional criterion"]
    )

    leader_uncertain_on_optional = {
        "criteria": [
            {"id": "0", "status": "pass"},
            {"id": "1", "status": "unclear"},
        ]
    }

    assert direct_vm.run_validator(leader_result=leader_uncertain_on_optional) is True


def test_validator_rejects_optional_definite_disagreement(direct_vm, direct_deploy):
    contract, _ = _evaluate_and_get_validator(
        direct_vm, direct_deploy, optional=["optional criterion"]
    )

    leader_disagrees_on_optional = {
        "criteria": [
            {"id": "0", "status": "pass"},
            {"id": "1", "status": "fail"},
        ]
    }

    assert direct_vm.run_validator(leader_result=leader_disagrees_on_optional) is False


def test_validator_normalizes_unknown_status_from_leader(direct_vm, direct_deploy):
    contract, _ = _evaluate_and_get_validator(
        direct_vm, direct_deploy, optional=["optional criterion"]
    )

    leader_sends_junk_status = {
        "criteria": [
            {"id": "0", "status": "pass"},
            {"id": "1", "status": "banana"},
        ]
    }

    # "banana" normalizes to unclear, which is tolerated on a non-required criterion
    assert direct_vm.run_validator(leader_result=leader_sends_junk_status) is True


def test_validator_rejects_required_status_flip_even_when_verdict_matches(
    direct_vm, direct_deploy
):
    # required 0 pass + required 1 fail -> rejected; leader says 0 fail + 1 pass
    # also rejected, but the required criterion statuses differ.
    contract, _ = _evaluate_and_get_validator(
        direct_vm, direct_deploy, criteria=["criterion one", "criterion two"]
    )
    direct_vm.clear_mocks()
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass", "fail")

    leader_mirrored = {
        "criteria": [
            {"id": "0", "status": "fail"},
            {"id": "1", "status": "pass"},
        ]
    }

    assert direct_vm.run_validator(leader_result=leader_mirrored) is False


def test_nondet_closures_are_cloudpickle_serializable(direct_vm, direct_deploy):
    """Production ships the leader/validator through cloudpickle.

    Direct mode normally skips pickling; with `check_pickling` enabled the runner
    pickles both closures exactly like a node does, and warns if that fails.
    """
    contract, _, submission_id = deploy_with_submission(
        direct_deploy, optional=["optional criterion"]
    )
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass", "pass")
    direct_vm.check_pickling = True

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        contract.evaluate_submission(submission_id)

    pickling_warnings = [str(w.message) for w in caught if "picklable" in str(w.message)]
    assert pickling_warnings == []
    assert contract.get_record(submission_id)["verdict"] == "verified"
