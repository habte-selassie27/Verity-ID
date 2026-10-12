# GenLayer API audit

Every GenLayer API used by `contracts/verity_id.py`, checked against the SDK
that the contract's pinned runner actually ships.

**Method.** Documentation on `sdk.genlayer.com/main` is written for
**v0.3.0-rc9**. The contract pins runner `py-genlayer:1jb45aa8...`, which the
direct-mode test runner resolves to **v0.3.0-rc7**. Those differ, so docs alone
are not authoritative here. Each row below was checked against the extracted
rc7 standard library at
`~/.cache/gltest-direct/extracted/v0.3.0-rc7/py-lib-genlayer-std/*/genlayer/`,
and then confirmed by 153 passing direct tests plus two live StudioNet
deployments.

`genlayer/__init__.py` (rc7) re-exports explicitly:

```python
from .types import *
from .storage import DynArray, Array, TreeMap, allow
from ._internal.annotations import public, private
```

## Results

| API | Used as | Verdict |
|---|---|---|
| `gl.contract.Contract` | base class | ok — confirmed in rc7 |
| `gl.allow` | dataclass storage decorator | ok — re-exported from `.storage` |
| `gl.TreeMap` | storage container | ok — re-exported from `.storage` |
| `gl.u32(...)` | sized integer | ok — `u32 = Annotated[int, ...]`, but **callable in rc7** (verified `gl.u32(5) == 5`) |
| `gl.public.write` / `gl.public.view` | method decorators | ok |
| `gl.message.sender_address` | caller identity | ok |
| `gl.nondet.web.get(url)` | evidence fetch | ok — `Response.status`, `.body` |
| `gl.nondet.exec_prompt(p, response_format="json")` | LLM call | ok — exact signature match in rc9 docs |
| `gl.vm.Return.calldata` | validator input | ok |
| `gl.vm.UserError(str)` | raised in `judge()` | ok |

## Documentation drift — do not "fix" these

The v0.3 migration guide renames several things the contract uses. Those
renames target **rc9** and do **not** apply to the pinned rc7 runner. Applying
them would break working, deployed code:

| rc9 docs say | Contract uses | rc7 reality |
|---|---|---|
| `gl.storage.TreeMap` | `gl.TreeMap` | re-exported, works |
| `gl.storage.allow` | `gl.allow` | re-exported, works |
| `u32(x)` "no longer callable" | `gl.u32(x)` | still callable in rc7 |

## One genuine finding: `run_nondet` is the *unsafe* variant

`contracts/verity_id.py` calls:

```python
outcome = gl.vm.run_nondet(judge, validator_fn)
```

The v0.3 migration guide renames the two non-determinism entry points:

- the old `run_nondet_unsafe` (no validator sandbox) is now **`run_nondet`**
- the old safe `run_nondet` is now **`run_nondet_default`**

So this contract is calling the unsafe variant.

**What still works.** `run_nondet` still takes and enforces `validator_fn`:

```
run_nondet(leader_fn: Callable[[], T], validator_fn: Callable[[Result], bool], ...)
    "The leader function runs as is, and each validator checks the result."
    "Returns: The result from the leader (iff validation passes, otherwise VM
     will be terminated)"
```

Equivalence is therefore enforced — the contract's core design is intact, and
the live integration tests confirm it.

**What differs.** From the rc9 docs on `run_nondet`:

> "This function does not use extra sandbox for catching validator errors.
> Validator error will result in a 'Disagree' error in executor (same as if this
> function returned 'False'). Use `run_nondet_default()` instead if you want to
> catch and inspect `validator_fn` errors, or use sandbox inside of it."

That maps directly onto VerityID. Inside `validator_fn`, the re-run of `judge()`
can raise `TRANSIENT: evidence_source_unavailable` or `EXTERNAL: ...`. Under
`run_nondet` an evidence source that is down for *every* validator is recorded
as **Disagree**, which is semantically wrong — everyone agreeing that the source
is unreachable is not a disagreement about the claim.

`run_nondet_default` exposes `compare_user_errors` for exactly this:

```
run_nondet_default(leader_fn, validator_fn, /, *,
    compare_user_errors: Callable[[UserError, UserError], bool] = <lambda>,
    compare_vm_errors:  Callable[[VMError, VMError], bool] = <lambda>, ...)
```

Treating two identical `UserError`s as agreement would make the
transient-failure path behave correctly.

**Recommendation, not applied.** Switch to `gl.vm.run_nondet_default` with a
`compare_user_errors` that accepts identical error payloads, then re-deploy and
re-run gate 3. Not changed here because the contract is live on two addresses
and currently passing; that is the user's call. The error-precedence table in
`equivalence.md` should note which variant it describes.

## Not verifiable here

`gl.vm.run_nondet_default`'s `compare_user_errors` behaviour, and the
rc7-vs-rc9 delta inside GenVM itself, can only be confirmed by deploying a
variant and exercising it. That needs a node round-trip per change.

## Provenance

- SDK reference: <https://sdk.genlayer.com/main/_static/ai/api.txt> (rc9 docs)
- rc7 ground truth: extracted `py-lib-genlayer-std` from the direct-mode cache
- Empirical: 153 direct tests, 15 integration tests, 3 StudioNet deployments
  (the current one, `0xD554c7…BB57`, was `diff`-verified byte-identical to
  `contracts/verity_id.py` with all 10 methods in its schema)

No GenLayer API was added or changed by the policy-versioning and source-control
work: those changes are pure Python plus the already-audited `TreeMap`,
`u32`, `@allow_storage`, `gl.public.view` and `gl.public.write`.
- The `write-contract` skill is **not installed** on this machine and no GenLayer
  MCP server is configured, so the skill itself could not be consulted. The
  official SDK reference was used in its place.