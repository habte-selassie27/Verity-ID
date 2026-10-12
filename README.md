# VerityID

VerityID is a standalone, reusable GenLayer Intelligent Contract that decides
whether submitted evidence supports a credential claim. A **verifier** publishes
a *CredentialPolicy* (the claim, the accepted evidence types, a bounded
checklist of criteria and a minimum number of sources); a **submitter** provides
evidence references (URLs plus a declared type each); validators fetch that
evidence, judge every criterion, and the contract records one of `verified`,
`rejected` or `inconclusive` together with a deterministic reason code. No
frontend or backend is part of this project: the deliverable is the contract,
its tests and its documentation.

## Authenticity is not truth

A `verified` result means **the submitted evidence supports the claim under this
policy at this time**. It is not a legal attestation and it does not prove that a
source document is genuine.

Validators can fetch and interpret evidence; they cannot detect a well-made
forgery. Policies should therefore require authoritative issuer sources
(registries, issuer letters) rather than user-uploaded documents, and consumers
of a record should treat `verified` as one input among others.

## Repository layout

```
contracts/verity_id.py        the Intelligent Contract
contracts/__init__.py
docs/equivalence.md           consensus design in full (the four answers)
docs/api-audit.md             every GenLayer API used, verified against the pinned runner
docs/boilerplate-deviation.md what this project omits from the official boilerplate, and why
scripts/lint.sh               genvm-lint wrapper
scripts/test.sh               direct test runner (and integration with --all)
tests/conftest.py             pytest wiring shared by both suites
tests/direct/                 in-memory tests with mocked web + LLM
tests/integration/            consensus tests against a live node
gltest.config.yaml            integration network configuration
requirements.txt              runtime + tooling dependencies
requirements-test.txt         test dependencies
artifacts/                    gltest build/deploy output (cleared on every run)
```

## Contract API

Deterministic vocabulary: statuses `pass | fail | unclear`, verdicts
`verified | rejected | inconclusive`, evidence types `issuer_registry`,
`certificate`, `transcript`, `issuer_letter`.

### Writes

| Method | Inputs | Result |
|---|---|---|
| `create_policy` | `claim_description: str`, `evidence_types: list[str]`, `criteria: list[str]`, `optional_criteria: list[str]`, `min_sources: int`, `allowed_domains: list[str]` | new `policy_id` (`pol-1`, `pol-2`, ...) stored as version 1 |
| `update_policy` | `policy_id` + the same six inputs | owner-only, active policies only, publishes version `n+1`; version `n` is never rewritten |
| `retire_policy` | `policy_id` | owner-only, one-way (`active` -> `retired`) |
| `submit_evidence` | `policy_id: str`, `evidence_types: list[str]`, `evidence_urls: list[str]` | new `submission_id` (`sub-1`, ...), pinned to the policy version in force at that moment |
| `evaluate_submission` | `submission_id: str` | runs the non-deterministic block against the **pinned** version and records the verdict |

Every declared `evidence_type` must be present in a submission, `min_sources`
must be at least the number of declared types, and each submission may carry at
most 8 references. Evaluation is blocked once a submission is evaluated, so a
record is never silently overwritten.

### Views

| Method | Returns |
|---|---|
| `get_policy(policy_id)` | current `version`, owner, claim, evidence types, `allowed_domains`, criteria, optional criteria, `min_sources`, status, submission count |
| `get_policy_version(policy_id, version)` | any stored version's rules — this is exactly what a pending submission is judged by |
| `get_submission(submission_id)` | policy id, pinned `policy_version`, submitter, evidence references (type + url), status |
| `get_record(submission_id)` | verdict, reason code, the `policy_version` used, per-criterion results |
| `list_submissions(policy_id, offset, limit)` | paginated submission ids (`limit` 1..20) |

### Errors

Deterministic, prefixed, and never containing timestamps, urls or random ids:

| Prefix | Meaning | Examples |
|---|---|---|
| `EXPECTED` | normal user/logic error, rejected before any web or LLM work | `claim_description_empty`, `criteria_empty`, `criterion_duplicate`, `evidence_type_not_allowed`, `min_sources_out_of_range`, `allowed_domain_format`, `allowed_domain_duplicate`, `policy_not_owner`, `policy_not_active`, `policy_version_out_of_range`, `evidence_below_min_sources`, `evidence_url_duplicate`, `evidence_url_scheme`, `evidence_url_userinfo`, `evidence_url_port`, `evidence_url_host`, `evidence_url_domain_not_allowed`, `evidence_type_missing`, `submission_already_evaluated` |
| `EXTERNAL` | evidence could not be used | `evidence_source_rejected:<index>`, `evidence_source_empty:<index>` |
| `TRANSIENT` | retryable source failure | `evidence_source_unavailable:<index>` |
| `LLM_ERROR` | unusable model output | `unusable_model_output` |

A failed evaluation writes **no** record and leaves the submission `submitted`,
so it can be retried.

## Policy versions: rules cannot change retroactively

A submission records `policy_version` when it is filed, and `evaluate_submission`
reads that version's claim and checklist rather than the live policy. An owner
can `update_policy` as often as they like; already-pending evidence keeps the
rules it was filed under, and the record states which version produced it.

`update_policy` **publishes a new version instead of editing the current one**, so
every historical version stays readable through `get_policy_version` — an auditor
can reconstruct exactly what was assessed.

Retirement only stops *new* submissions. Evidence filed before a retirement is
still evaluable against its frozen version, so a retire can never strand a
pending credential.

## Evidence source controls

URL syntax never makes a source trustworthy, so the contract removes the cheaply
detectable traps before any validator fetches anything:

* `https` only — `http` is rejected outright
* no credentials in the authority (`user:pass@`)
* no explicit port (this also rules out IPv6 literals)
* the host must be a DNS hostname, never an IP literal or `localhost`
* when a policy declares `allowed_domains`, the host must match one exactly or as
  a subdomain (`registry.example.edu` matches `example.edu`, and
  `registry.example.edu.evil.com` does not)

An empty `allowed_domains` means *any* https host — that is a deliberate choice
the verifier makes, not a default. Declaring domains is strongly recommended;
see the authenticity note below for why issuer-authoritative sources matter.

Validation errors are rejected **before** any web or LLM work:
`evidence_url_scheme`, `evidence_url_userinfo`, `evidence_url_port`,
`evidence_url_host`, `evidence_url_domain_not_allowed`, `allowed_domain_format`
and friends.

**Not done, deliberately: content hashing of fetched pages.** Storing a digest
of the retrieved body would let a reader compare a later fetch against what the
validators saw, but it would also have to be part of the agreed leader output —
which means a page that legitimately changes between the leader's fetch and the
validators' re-fetch becomes a *consensus disagreement* rather than an ordinary
update. Since verdicts are explicitly "at this time" and evidence content is
never persisted (see Privacy), the honest position is to record the URL, the
policy version and the verdict, and to state that re-fetching may yield
different content. This is documented rather than silently omitted.

## Equivalence design (summary)

Full text: [`docs/equivalence.md`](docs/equivalence.md).

1. **Leader output** — normalized structure only: one `{id, status}` per policy
   criterion, statuses restricted to the enum. No prose, no model-supplied
   verdict; `verdict`/`reason_code` are derived deterministically by the
   contract from the required criteria.
2. **Validator check** — independently re-fetches the same evidence, re-judges
   the same policy and compares its own normalized result with the leader's.
3. **Equivalent iff** — same criterion ids, identical derived verdict/reason, identical
   status for every *required* criterion, and for *optional* criteria identical
   status except `unclear` versus a definite status (an optional criterion can
   never change the verdict). Anything else is a disagreement.
4. **Disagreement/failure** — source or model failures raise deterministic
   `EXTERNAL`/`TRANSIENT`/`LLM_ERROR` errors, write no record and stay
   retryable; validator disagreement produces no record and is left to GenLayer
   consensus/appeal. Nothing is resolved locally. Measured on StudioNet: a 2-vs-2
   split settles at `status_name: UNDETERMINED`, `get_record` reverts and the
   submission stays `submitted` — note the leader's `execution_result` is still
   `SUCCESS`, so a receipt-based "did it fail?" check is the wrong assertion here.

Prompt-injection stance: fetched evidence is untrusted data. The prompt says so,
the schema has no `verdict` field, injected criterion ids are ignored, and any
unrecognised status degrades to `unclear`, which can never yield `verified` on a
required criterion (`tests/direct/test_injection.py`).

## Privacy

* Only references and normalized results are stored: evidence URLs, declared
  types, criterion texts, per-criterion statuses. Never fetched document bodies.
* No personal data is required by the contract; policies should reference
  issuer-hosted identifiers (a registry entry, a letter id) instead of names,
  dates of birth or document images.
* Evidence text is used transiently, whitespace-normalized and truncated
  (`MAX_SOURCE_CHARS`) before it reaches the model; it is never persisted.

## Example

Policy (issuer registry required, one required criterion, one optional check):

```
claim_description:   "The holder was awarded the BSc Computer Science degree of
                      Example University."
evidence_types:      ["issuer_registry"]
criteria:            ["The issuer registry lists a completed BSc Computer
                      Science degree for the holder."]
optional_criteria:   ["The registry entry names the same holder identity."]
min_sources:         1
allowed_domains:     ["example.edu"]
```

Evidence:

```
evidence_types: ["issuer_registry"]
evidence_urls:  ["https://registry.example.edu/verify?id=abc123"]
```

The evidence host is a subdomain of the policy's approved `example.edu`, so it
passes. The same URL under a policy that approved only `other.org` would be
rejected with `EXPECTED: evidence_url_domain_not_allowed` before any validator
fetched anything.

A `verified` record means the registry page (a source the policy accepts) shows
the criterion holds. It does not prove the registry page itself is authentic.

## Running it

```shell
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # runtime + tooling
pip install -r requirements-test.txt     # test extras
```

### 1. Lint (must be clean)

```shell
genvm-lint check contracts/verity_id.py
# or: bash scripts/lint.sh
```

### 2. Direct tests (no network, no simulator, ~ms per test)

```shell
pytest tests/direct/ -v
# or: bash scripts/test.sh
```

### 3. Integration tests (real consensus; needs a reachable node)

```shell
gltest tests/integration/ -v -s
```

`gltest.config.yaml` defaults to **studionet** (`https://studio.genlayer.com/api`,
`leader_only: false`), so no local Docker or simulator is needed — StudioNet is
gasless. To run against a local simulator instead:

```shell
genlayer up                                  # localnet at 127.0.0.1:4000
gltest --network localnet tests/integration/ -v -s
```

These tests drive the genuine leader/validator split. Web and LLM are mocked
**per validator** via `transaction_context`, so agreement and disagreement are
deterministic without a real model. Note the gltest API: `contract.method(...)`
returns a `ContractFunction` — writes need `.transact()`, views need `.call()`,
and `transaction_context` is an argument to `.transact()`, not to the method.

Each test deploys its own contract instance, so a full run leaves a handful of
VerityID contracts on the selected network.

### 4. Deploy

```shell
genlayer network set localnet     # or studionet / bradbury
genlayer deploy
genlayer schema <address>         # verify the deployed surface
```

### Toolchain note

The contract header pins the SDK runner (the `Depends` header is part of the
contract, not a build file):

```
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

This runner ships the SDK layout (`genlayer.gl`, `genlayer.py`) that the
current direct-mode test runner (`genlayer-test` v0.29, used by the official
boilerplate) supports, and it is the runner the latest GenVM release
(`v0.3.0-rc7`) publishes.

`genvm-lint` resolves runner bundles from whichever repository it is pointed
at. Newer linter builds default to `genlayerlabs/genvm-manager`, whose bundles
use a different runner format (`.zip`) and a different SDK layout, and this
directory also caches prereleases from that repository - so the resolution is
pinned explicitly:

```shell
GENVM_REPO=genlayerlabs/genvm GENVM_VERSION=v0.3.0-rc7 genvm-lint check contracts/verity_id.py
```

`scripts/lint.sh` sets both variables for you.

Note: calling bare `genvm-lint check ...` without those two variables makes the
linter try to resolve the default `genlayerlabs/genvm-manager` repository and can
hang indefinitely with no output. Always lint through `scripts/lint.sh`.

## Test coverage

Direct suite (`pytest tests/direct/`, no network) — 153 tests:

| Area | File | What it proves |
|---|---|---|
| Policy lifecycle + owner-only access | `test_policy.py` | non-owner cannot update or retire; rejected input stores nothing |
| **Policy versioning (the freeze)** | `test_policy_versioning.py` | owner edits after submission **cannot** change the verdict; v1 rules stay readable; retirement does not strand a pending submission |
| Submission validation | `test_submission.py` | bounds, duplicates, type coverage, pagination |
| **Source controls** | `test_source_controls.py` | `http` rejected, no credentials/ports/IPs, allowlist enforcement incl. subdomain matching and `…example.edu.evil.com` spoofing |
| Verdict mapping | `test_evaluation.py` | all-pass → `verified`, required fail → `rejected`, unclear → `inconclusive`, re-evaluation blocked |
| LLM output parsing | `test_llm_parsing.py` | malformed JSON, code fences, trailing prose, key aliases, missing criteria, unknown/out-of-range statuses |
| Equivalence rule | `test_equivalence.py` | required disagreement rejected, optional `unclear` tolerated, malformed/errored leader rejected, **evidence changed between fetches** detected |
| Prompt injection | `test_injection.py` | injected `verdict`/criterion ids ignored; injected text never stored |
| Web failure paths | `test_web_failures.py` | 429/5xx → `TRANSIENT`, other non-2xx/empty → `EXTERNAL`, no record written, submission stays retryable |

Integration suite (`gltest tests/integration/`, real consensus on StudioNet)
drives the actual leader/validator split with per-validator mocked web + LLM:
agreement on clear/ambiguous evidence, disagreement → no record written.

## Network and deployment

Network: **studionet** (`https://studio.genlayer.com/api`, chain id `61999`,
gasless — 0 GEN is expected).

| Contract address | How | Status |
|---|---|---|
| `0xD554c70d32ff6395754cAbf000751393F9dAbB57` | Studio web UI | **current** — byte-identical to this tree, 10 methods |
| `0x189266Af75ff8105755b15273B68d0D19d027bd9` | Studio web UI | superseded — 9-method version, no policy versioning or source controls |
| `0x5ED035932EefD7e213458E866A5399D89E8EAe96` | `genlayer deploy` | superseded — same 9-method version (tx `0x72e1949f…d4b0`, votes `[IDLE, AGREE, AGREE, AGREE, IDLE]`) |

Current deployment:

- Studio: <https://studio.genlayer.com/?import-contract=0xD554c70d32ff6395754cAbf000751393F9dAbB57>
- Explorer: <https://explorer-studio.genlayer.com/address/0xD554c70d32ff6395754cAbf000751393F9dAbB57>

That address was verified against the working tree rather than assumed: the
fetched code is 920 lines and `diff`s clean against `contracts/verity_id.py`, the
pinned `Depends` header matches, and the schema lists all 10 methods including
`get_policy_version` and the `allowed_domains` parameter on
`create_policy`/`update_policy`. Reproduce it with:

```shell
genlayer network set studionet
genlayer schema 0xD554c70d32ff6395754cAbf000751393F9dAbB57

genlayer code 0xD554c70d32ff6395754cAbf000751393F9dAbB57 > /tmp/deployed.py
tail -n +5 /tmp/deployed.py | head -n -3 | diff - contracts/verity_id.py
# no output means identical (the 4 leading / 3 trailing lines are CLI log lines)
```

To deploy fresh from the CLI instead (gasless on StudioNet):

```shell
genlayer network set studionet
genlayer deploy --contract contracts/verity_id.py
```

Do not cite the two superseded addresses: they predate frozen policy versions
and evidence source controls, so `get_policy_version` is absent and
`create_policy` takes five arguments, not six.

## Limits

| Bound | Value |
|---|---|
| criteria per policy (required + optional) | 8 |
| claim length | 600 chars |
| criterion length | 300 chars |
| evidence references per submission | 8 |
| evidence URL length | 500 chars |
| evidence text per source fed to the model | 4000 chars |
| pagination page size | 1..20 |
