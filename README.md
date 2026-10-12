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
scripts/lint.sh               genvm-lint wrapper
scripts/test.sh               direct test runner (and integration with --all)
tests/conftest.py             pytest wiring shared by both suites
tests/direct/                 in-memory tests with mocked web + LLM
tests/integration/            consensus tests against a running network
gltest.config.yaml            integration network configuration
requirements.txt              runtime + tooling dependencies
requirements-test.txt         test dependencies
artifacts/                    build/deploy output (empty by default)
```

## Contract API

Deterministic vocabulary: statuses `pass | fail | unclear`, verdicts
`verified | rejected | inconclusive`, evidence types `issuer_registry`,
`certificate`, `transcript`, `issuer_letter`.

### Writes

| Method | Inputs | Result |
|---|---|---|
| `create_policy` | `claim_description: str`, `evidence_types: list[str]`, `criteria: list[str]`, `optional_criteria: list[str]`, `min_sources: int` | new `policy_id` (`pol-1`, `pol-2`, ...) |
| `update_policy` | `policy_id` + the same five inputs | owner-only, active policies only, replaces the definition in place |
| `retire_policy` | `policy_id` | owner-only, one-way (`active` -> `retired`) |
| `submit_evidence` | `policy_id: str`, `evidence_types: list[str]`, `evidence_urls: list[str]` | new `submission_id` (`sub-1`, ...) |
| `evaluate_submission` | `submission_id: str` | runs the non-deterministic block and records the verdict |

Every declared `evidence_type` must be present in a submission, `min_sources`
must be at least the number of declared types, and each submission may carry at
most 8 references. Evaluation is blocked once a submission is evaluated, so a
record is never silently overwritten.

### Views

| Method | Returns |
|---|---|
| `get_policy(policy_id)` | owner, claim, evidence types, criteria, optional criteria, `min_sources`, status, submission count |
| `get_submission(submission_id)` | policy id, submitter, evidence references (type + url), status |
| `get_record(submission_id)` | verdict, reason code, per-criterion results |
| `list_submissions(policy_id, offset, limit)` | paginated submission ids (`limit` 1..20) |

### Errors

Deterministic, prefixed, and never containing timestamps, urls or random ids:

| Prefix | Meaning | Examples |
|---|---|---|
| `EXPECTED` | normal user/logic error, rejected before any web or LLM work | `claim_description_empty`, `criteria_empty`, `criterion_duplicate`, `evidence_type_not_allowed`, `min_sources_out_of_range`, `policy_not_owner`, `policy_not_active`, `evidence_below_min_sources`, `evidence_url_duplicate`, `evidence_type_missing`, `submission_already_evaluated` |
| `EXTERNAL` | evidence could not be used | `evidence_source_rejected:<index>`, `evidence_source_empty:<index>` |
| `TRANSIENT` | retryable source failure | `evidence_source_unavailable:<index>` |
| `LLM_ERROR` | unusable model output | `unusable_model_output` |

A failed evaluation writes **no** record and leaves the submission `submitted`,
so it can be retried.

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
   consensus/appeal. Nothing is resolved locally.

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
```

Evidence:

```
evidence_types: ["issuer_registry"]
evidence_urls:  ["https://registry.example.edu/verify?id=abc123"]
```

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

## Network and deployment

| Network | Contract address |
|---|---|
| studionet | `0x189266Af75ff8105755b15273B68d0D19d027bd9` |
| localnet | not deployed: integration tests and deployment need a running node |

Deployed to **StudioNet** (gasless, so 0 GEN is expected). Deploy tx
`0xa98e3c9dfafafb1f01d8ac847f8e7652abf57f292c0183386361fa94f4beedfa`,
finalized with `SUCCESS` and consensus `Accepted` by a 5-validator set.

- Studio: <https://studio.genlayer.com/?import-contract=0x189266Af75ff8105755b15273B68d0D19d027bd9>
- Explorer: <https://explorer-studio.genlayer.com/address/0x189266Af75ff8105755b15273B68d0D19d027bd9>

The deployed bytecode was diffed against `contracts/verity_id.py` and is
identical, so the contract described here is the contract that is live:

```shell
genlayer network set studionet
genlayer schema 0x189266Af75ff8105755b15273B68d0D19d027bd9
genlayer code   0x189266Af75ff8105755b15273B68d0D19d027bd9
```

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
