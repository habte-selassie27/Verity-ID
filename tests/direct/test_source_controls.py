"""Evidence source controls: HTTPS only, sane hosts, policy allowlist.

URL syntax never makes a source trustworthy - these tests cover the cheaply
detectable traps the contract removes before any validator fetches anything, and
the per-policy allowlist that defines *which* sources a verifier accepts.
"""

import pytest

from tests.direct.conftest import (
    REGISTRY_URL,
    create_policy,
    deploy_with_submission,
    mock_judgement,
    mock_registry,
    submit,
)


def _submit_expecting(direct_vm, contract, policy_id, url, expected_error):
    with direct_vm.expect_revert(expected_error):
        submit(contract, policy_id, urls=[url])


@pytest.mark.parametrize(
    ("url", "expected_error"),
    [
        # fix #2: http is no longer accepted at all
        ("http://registry.example.edu/verify", "EXPECTED: evidence_url_scheme"),
        ("ftp://registry.example.edu/verify", "EXPECTED: evidence_url_scheme"),
        ("registry.example.edu/verify", "EXPECTED: evidence_url_scheme"),
        # credentials in the authority would leak into logs and mocks
        (
            "https://user:pass@registry.example.edu/verify",
            "EXPECTED: evidence_url_userinfo",
        ),
        ("https://admin@registry.example.edu/verify", "EXPECTED: evidence_url_userinfo"),
        # non-default ports and raw addresses are never an issuer registry
        (
            "https://registry.example.edu:8443/verify",
            "EXPECTED: evidence_url_port",
        ),
        ("https://192.168.0.1/verify", "EXPECTED: evidence_url_host"),
        ("https://127.0.0.1/verify", "EXPECTED: evidence_url_host"),
        # host shape
        ("https://localhost/verify", "EXPECTED: evidence_url_host"),
        ("https://bad_host.example.edu/verify", "EXPECTED: evidence_url_host"),
        ("https://-leading.example.edu/verify", "EXPECTED: evidence_url_host"),
        ("https:///verify", "EXPECTED: evidence_url_host"),
    ],
)
def test_url_hardening(direct_vm, direct_deploy, direct_alice, url, expected_error):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract)

    _submit_expecting(direct_vm, contract, policy_id, url, expected_error)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.org/verify",
        "https://registry.example.edu.evil.com/verify",
        "https://notexample.edu/verify",
        "https://example.edu.evil.com/verify",
    ],
)
def test_host_outside_the_allowlist_is_rejected(
    direct_vm, direct_deploy, direct_alice, url
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract, domains=["example.edu"])

    _submit_expecting(
        direct_vm, contract, policy_id, url, "EXPECTED: evidence_url_domain_not_allowed"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://registry.example.edu/verify",  # exact allowlisted domain
        "https://verify.registry.example.edu/verify",  # subdomain of it
        "https://sub.registry.example.edu/path?q=1",  # nested subdomain
    ],
)
def test_host_inside_the_allowlist_is_accepted(
    direct_vm, direct_deploy, direct_alice, url
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract, domains=["example.edu"])

    submission_id = submit(contract, policy_id, urls=[url])
    assert contract.get_submission(submission_id)["evidence"][0]["url"] == url


def test_empty_allowlist_accepts_any_https_host(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract, domains=[])

    submission_id = submit(contract, policy_id, urls=["https://anywhere.example.org/x"])
    assert contract.get_submission(submission_id)["status"] == "submitted"


def test_allowlist_is_visible_on_the_policy(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    policy_id = create_policy(contract, domains=["registry.example.edu", "example.edu"])

    assert contract.get_policy(policy_id)["allowed_domains"] == [
        "registry.example.edu",
        "example.edu",
    ]
    assert contract.get_policy_version(policy_id, 1)["allowed_domains"] == [
        "registry.example.edu",
        "example.edu",
    ]


def test_narrowing_the_allowlist_applies_to_new_submissions_only(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice
    policy_id = create_policy(contract, domains=["example.edu"])
    existing = submit(contract, policy_id)

    # owner restricts sources to a different domain
    contract.update_policy(
        policy_id,
        "Revised claim",
        ["issuer_registry"],
        ["criterion"],
        [],
        1,
        ["letters.example.edu"],
    )

    # the already-filed submission keeps its URL and its rules
    assert contract.get_submission(existing)["evidence"][0]["url"] == REGISTRY_URL
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass")
    contract.evaluate_submission(existing)
    assert contract.get_record(existing)["verdict"] == "verified"

    # but new evidence must now come from the narrowed domain
    _submit_expecting(
        direct_vm,
        contract,
        policy_id,
        REGISTRY_URL,
        "EXPECTED: evidence_url_domain_not_allowed",
    )
    submit(contract, policy_id, urls=["https://mail.letters.example.edu/letter"])


@pytest.mark.parametrize(
    ("domains", "expected_error"),
    [
        (["example.edu"] * 9, "EXPECTED: allowed_domains_too_many"),
        ([""], "EXPECTED: allowed_domain_empty"),
        (["   "], "EXPECTED: allowed_domain_empty"),
        (["x" * 101], "EXPECTED: allowed_domain_too_long"),
        (["example .edu"], "EXPECTED: allowed_domain_whitespace"),
        (["https://example.edu"], "EXPECTED: allowed_domain_format"),
        (["example.edu/path"], "EXPECTED: allowed_domain_format"),
        (["example.edu:443"], "EXPECTED: allowed_domain_format"),
        (["example.edu@evil.com"], "EXPECTED: allowed_domain_format"),
        (["localhost"], "EXPECTED: allowed_domain_format"),
        (["192.168.0.1"], "EXPECTED: allowed_domain_format"),
        (["example.edu", "example.edu"], "EXPECTED: allowed_domain_duplicate"),
    ],
)
def test_allowed_domain_validation(
    direct_vm, direct_deploy, direct_alice, domains, expected_error
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert(expected_error):
        create_policy(contract, domains=domains)


def test_invalid_domains_do_not_create_a_policy(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy("contracts/verity_id.py")
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("EXPECTED: allowed_domain_whitespace"):
        create_policy(contract, domains=["not a domain"])

    with direct_vm.expect_revert("EXPECTED: allowed_domain_format"):
        create_policy(contract, domains=["nodots"])

    with direct_vm.expect_revert("EXPECTED: policy_not_found"):
        contract.get_policy("pol-1")


def test_source_controls_do_not_block_a_normal_evaluation(direct_vm, direct_deploy):
    """The happy path still works end to end with the allowlist in force."""
    contract, _, submission_id = deploy_with_submission(
        direct_deploy, domains=["example.edu"]
    )
    mock_registry(direct_vm)
    mock_judgement(direct_vm, "pass")

    contract.evaluate_submission(submission_id)

    record = contract.get_record(submission_id)
    assert record["verdict"] == "verified"
    assert record["policy_version"] == 1
