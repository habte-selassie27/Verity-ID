# Deviation from genlayer-project-boilerplate

AGENTS.md §4 says to start from
[genlayer-project-boilerplate](https://github.com/genlayerlabs/genlayer-project-boilerplate).
This project does not. It was already laid out differently before any of this
work began, so rather than silently diverge, here is the difference and why
each part is or isn't needed.

## What was adopted

| Boilerplate | VerityID | Note |
|---|---|---|
| `gltest.config.yaml` | kept | extended with explicit `url` and `leader_only: false` per network |
| `tests/direct/` + `tests/integration/` split | kept | same shape, different suites |
| `pytest` marker `integration` | kept | via `pyproject.toml` and `tests/conftest.py` |
| `.gitignore` | kept | differs: `artifacts/` is ignored wholesale |

`artifacts/` is ignored wholesale because `gltest` **clears** that directory on
every run, so nothing inside it can be tracked. A `.gitkeep` placed there is
deleted on the first `gltest` invocation — this was observed, not assumed.

## What was skipped, and why

| Boilerplate | Why not needed |
|---|---|
| `frontend/` (Next.js, ~40 files) | AGENTS.md §1 classifies this task **contract only**. A frontend is out of scope unless explicitly requested. |
| `package.json`, `tsconfig.json`, `package-lock.json` | Only exist to build the frontend. |
| `config/genlayer_config.py` | Reads `RPCPROTOCOL`/`RPCHOST`/`RPCPORT` for the JS deploy script. This project deploys with `genlayer deploy`, which resolves the network from `genlayer network set`. |
| `deploy/deployScript.ts` | Same reason — JS-side deployment. |
| `__init__.py` at repo root, `contracts/__init__.py` | Present where needed (`contracts/`, `tests/`, `tests/direct/`, `tests/integration/`); the repo-root one is for JS resolution. |
| `support/ci/ACTIVE_DEV_BRANCH`, `.github/workflows/*` | Branch-policy CI for the GenLayer org. Not a deliverable for a standalone contract. |

## What this means

The contract itself is unaffected: same `contracts/` layout, same `gltest`
invocation, same dependency pins. What is lost is the frontend scaffolding and
the JS deploy tooling, both of which AGENTS.md explicitly places out of scope for
a contract-only deliverable.

If a frontend or JS deployment is ever wanted, add
`/plugin marketplace add genlayerlabs/skills` style boilerplate from the repo
directly rather than retro-fitting it here.

## Caveat

This is a rationalisation of an existing layout, not a claim that the
boilerplate was consulted and rejected on the merits. The layout predates this
work. See `api-audit.md` for the verification that did happen.