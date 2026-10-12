#!/usr/bin/env bash
# Lint the VerityID contract.
#
# The contract header pins a py-genlayer runner hash that ships the current SDK
# layout. genvm-lint resolves runner bundles from the GenVM repository the
# bundle was published in, so the source repo/version are pinned here too:
# environments that also cache prerelease bundles from genlayerlabs/genvm-manager
# would otherwise resolve a bundle that does not contain this runner.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONTRACT_PATH="${1:-contracts/verity_id.py}"

GENVM_REPO="${GENVM_REPO:-genlayerlabs/genvm}" \
GENVM_VERSION="${GENVM_VERSION:-v0.3.0-rc7}" \
    genvm-lint check "$CONTRACT_PATH"
