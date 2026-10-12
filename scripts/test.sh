#!/usr/bin/env bash
# Gate 2 - direct tests (mocked web + LLM, no simulator required).
# Gate 3 - integration tests (needs a running GenLayer network/simulator).
#
#   ./scripts/test.sh          # direct only
#   ./scripts/test.sh --all    # direct + integration
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x .venv/bin/pytest ]; then
  PYTEST=.venv/bin/pytest
  GLTEST=.venv/bin/gltest
else
  PYTEST=pytest
  GLTEST=gltest
fi

echo "== direct tests =="
"$PYTEST" tests/direct/ -v

if [ "${1:-}" = "--all" ]; then
  echo "== integration tests =="
  "$GLTEST" tests/integration/ -v -s
fi
