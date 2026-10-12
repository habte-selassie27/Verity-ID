"""Shared helpers for VerityID integration tests.

Integration tests run against a live GenLayer node (StudioNet by default) with
real consensus. Web and LLM are still mocked, but at the *validator* level
rather than inside a single VM: `transaction_context` installs virtual
validators, each with its own web and LLM responses. That is what makes
leader/validator agreement testable without a real model.

Run with:  gltest tests/integration/ -v -s

Note on the API: in gltest, `contract.method(args=[...])` returns a
`ContractFunction`. Writes need `.transact()` and views need `.call()`.
"""

import json

from gltest import get_contract_factory, get_validator_factory

CONTRACT_PATH = "verity_id.py"

CLAIM = "The holder was awarded the BSc Computer Science degree."
REQUIRED_CRITERION = "The issuer registry lists a completed BSc Computer Science degree."
OPTIONAL_CRITERION = "The registry entry names the same holder identity."

REGISTRY_URL = "https://registry.example.edu/verify?id=abc123"

REGISTRY_BODY = (
    "Example University - Degree Registry. Holder: A. Example. "
    "Award: BSc Computer Science, conferred 2024. Status: awarded."
)

# Web responses shared by every mock validator in a test.
REGISTRY_WEB = {
    "nondet_web_request": {
        REGISTRY_URL: {"method": "GET", "status": 200, "body": REGISTRY_BODY}
    }
}

# Fixed clock, so nothing in a test depends on wall time.
GENVM_DATETIME = "2026-10-12T12:00:00Z"


def llm_response(payload: dict) -> str:
    """Serialize a mocked LLM answer. Keys may use any of the contract's aliases."""
    return payload if isinstance(payload, str) else json.dumps(payload)


def statuses_payload(*statuses, **extra) -> dict:
    """Canonical shape the contract expects: {"criteria": [{"id", "status"}]}."""
    payload = {
        "criteria": [
            {"id": str(position), "status": status}
            for position, status in enumerate(statuses)
        ]
    }
    payload.update(extra)
    return payload


def deploy_contract():
    """Deploy a fresh VerityID instance."""
    return get_contract_factory(contract_file_path=CONTRACT_PATH).deploy()


def mock_validators(llm_payloads, web=None):
    """Build `transaction_context` validators, one per distinct LLM answer.

    `llm_payloads` is a dict (or raw JSON string) or a list of them. Each entry
    becomes a virtual validator that answers every prompt with that payload, so
    a test can make validators disagree with each other.

    Returns a dict suitable for `transaction_context=...`.
    """
    if isinstance(llm_payloads, (dict, str)):
        llm_payloads = [llm_payloads]

    factory = get_validator_factory()
    validators = []
    for payload in llm_payloads:
        validator = factory.create_mock_validator(
            mock_llm_response={"nondet_exec_prompt": {".*": llm_response(payload)}},
            mock_web_response=web if web is not None else REGISTRY_WEB,
        )
        validators.append(validator.to_dict())

    return {"validators": validators, "genvm_datetime": GENVM_DATETIME}


def create_policy(
    contract, criteria=None, optional=None, types=None, min_sources=None, domains=None
):
    """Create the standard single-source degree policy."""
    resolved_types = ["issuer_registry"] if types is None else types
    resolved_criteria = [REQUIRED_CRITERION] if criteria is None else criteria
    resolved_optional = [OPTIONAL_CRITERION] if optional is None else optional
    resolved_min = len(resolved_types) if min_sources is None else min_sources
    resolved_domains = ["example.edu"] if domains is None else domains
    return contract.create_policy(
        args=[
            CLAIM,
            resolved_types,
            resolved_criteria,
            resolved_optional,
            resolved_min,
            resolved_domains,
        ]
    ).transact()


def submit(contract, policy_id, context=None):
    """Submit one issuer registry page as evidence."""
    return contract.submit_evidence(
        args=[policy_id, ["issuer_registry"], [REGISTRY_URL]]
    ).transact(transaction_context=context)


def evaluate(contract, submission_id, context, **kwargs):
    """Evaluate through real consensus with an explicit validator set."""
    kwargs.setdefault("wait_interval", 10000)
    kwargs.setdefault("wait_retries", 30)
    return contract.evaluate_submission(args=[submission_id]).transact(
        transaction_context=context, **kwargs
    )


def try_evaluate(contract, submission_id, context, **kwargs):
    """Evaluate, tolerating either a failed receipt or a consensus timeout.

    Validators that never agree means the transaction is never accepted. The
    client surfaces that either as a receipt whose execution did not succeed or
    as an exception while polling, so both outcomes are handled here.
    """
    try:
        return evaluate(contract, submission_id, context, **kwargs)
    except Exception:
        return None


def assert_no_record(contract, submission_id):
    """Assert no verdict was committed.

    `get_record` reverts with `EXPECTED: record_not_found` when nothing was
    written - it does not return None - and the submission stays retryable.
    """
    try:
        contract.get_record(args=[submission_id]).call()
    except Exception:
        pass
    else:
        raise AssertionError(f"expected no record for {submission_id}")

    submission = contract.get_submission(args=[submission_id]).call()
    assert submission["status"] == "submitted", submission


__all__ = [
    "CLAIM",
    "CONTRACT_PATH",
    "GENVM_DATETIME",
    "OPTIONAL_CRITERION",
    "REGISTRY_BODY",
    "REGISTRY_URL",
    "REGISTRY_WEB",
    "REQUIRED_CRITERION",
    "assert_no_record",
    "create_policy",
    "deploy_contract",
    "evaluate",
    "llm_response",
    "mock_validators",
    "statuses_payload",
    "submit",
    "try_evaluate",
]