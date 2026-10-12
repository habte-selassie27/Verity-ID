# VerityID consensus design

The evaluation path is non-deterministic: it fetches pages from the web and asks
a model to judge a claim. Every non-deterministic operation therefore lives
inside one explicit leader/validator block (`gl.vm.run_nondet`), and the block's
output is a normalized structure, never prose.

Implementation: `contracts/verity_id.py`, `evaluate_submission` (`judge` is the
leader function, `validator_fn` the validator) plus the module-level helpers
`_normalize_criteria`, `_status_map`, `_equivalent` and `_classify`.

## 1. What does the leader produce?

A normalized structured result only:

```
{"criteria": [{"id": "0", "status": "pass"}, {"id": "1", "status": "unclear"}]}
```

* one entry per policy criterion, ids exactly as published by the policy
* `status` restricted to the enum `pass | fail | unclear` — unknown, missing,
  numeric or otherwise out-of-range values are normalized to `unclear`
* no free-form text, no model-supplied verdict, no URLs, no scores
* the `verdict` and `reason_code` are **not** part of the block output: the
  contract derives them deterministically from the required criteria
  (`_classify`), so a model cannot talk its way to `verified`

## 2. What does a validator check?

It ignores the leader's reasoning and independently re-runs the same leader
function: it re-fetches the same evidence references, re-builds the same prompt
from the same policy, asks for its own judgement, normalizes its own result the
same way, and compares the two structured results with `_equivalent`.

## 3. What counts as equivalent?

`_equivalent(leader, validator)` returns true only when all of the following
hold:

1. both payloads normalize to the same set of criterion ids;
2. the derived verdict and reason code match exactly (`_classify` equality);
3. every **required** criterion has an identical status on both sides;
4. for **optional** criteria a status difference is tolerated only when exactly
   one side is `unclear` (an optional criterion cannot change the verdict, so
   `unclear` vs a definite status is not a material disagreement);
   a definite-vs-definite disagreement on an optional criterion is rejected.

Anything else — a different required status, a missing criterion, a malformed
leader payload, a leader error (`UserError`/`VMError` instead of `Return`) —
is a disagreement.

Borderline case: if validators split between `verified` and `rejected` the
statuses differ on a required criterion, so the block does not reach equivalence
and no verdict is recorded. GenLayer's consensus/appeal machinery handles that
outcome; the contract never resolves it locally and never records a coin flip.
`safe outcome is inconclusive` applies when the *evidence itself* is unsettled
(the model answers `unclear` on a required criterion) — that is a recorded
`inconclusive` result, not a disputed one.

## 4. What happens on disagreement or failure?

| Situation | Behavior | Prefix |
|---|---|---|
| Evidence source returns 5xx/429 | block raises, no record, submission stays `submitted` and retryable | `TRANSIENT` |
| Evidence source returns other non-2xx | block raises, no record, retryable | `EXTERNAL` |
| Evidence source has no/empty body | block raises, no record, retryable | `EXTERNAL` |
| Model output unusable (unparseable, wrong shape) | block raises, no record, retryable | `LLM_ERROR` |
| Validators disagree | no record; GenLayer consensus/appeal decides | — |
| Cheap-to-detect bad input | rejected before any web/LLM work | `EXPECTED` |

Error messages are deterministic, enum-like and free of timestamps, urls and
random ids (`EXTERNAL: evidence_source_rejected:<index>`), so leader and
validator raise byte-identical errors and agree on failure too.

## Prompt injection stance

Fetched evidence is untrusted data. The prompt says so explicitly, and the
output schema makes injection unable to change the recorded outcome:

* the model's own `verdict` field is not part of the schema and is ignored;
* injected criterion ids are ignored (only the policy's ids are kept);
* missing or unknown statuses become `unclear`, which can never produce
  `verified` on a required criterion;
* the verdict is computed by the contract from validated statuses.

Covered by `tests/direct/test_injection.py`.
