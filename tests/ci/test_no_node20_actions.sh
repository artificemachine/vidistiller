#!/usr/bin/env bash
# Asserts that no known Node-20-only action SHAs remain in any workflow file.
# RED when old SHAs are present, GREEN after the Node-24 bump.

set -euo pipefail

WORKFLOWS_DIR="$(cd "$(dirname "$0")/../../.github/workflows" && pwd)"

# SHAs that correspond to Node-20-only action versions (pre-bump)
FORBIDDEN_SHAS=(
  "692973e3d937129bcbf40652eb9f2f61becf3332"  # actions/checkout v4
  "a26af69be951a213d495a4c3e4e4022e16d87065"  # actions/setup-python v5 (old)
  "49933ea5288caeca8642d1e84afbd3f7d6820020"  # actions/setup-node v4
  "c94ce9fb468520275223c153574b00df6fe4bcc9"  # docker/login-action v3
  "8d2750c68a42422c14e847fe6c8ac0403b4cbd6f"  # docker/setup-buildx-action v3
  "c299e40c65443455700f0fdfc63efafe5b349051"  # docker/metadata-action v5 (old)
  "ca052bb54ab0790a636c9b5f226502c73d547a25"  # docker/build-push-action v5
)

failures=0

for sha in "${FORBIDDEN_SHAS[@]}"; do
  matches=$(grep -rn "$sha" "$WORKFLOWS_DIR" 2>/dev/null || true)
  if [[ -n "$matches" ]]; then
    echo "FAIL: Node-20-only SHA still present: $sha"
    echo "$matches"
    failures=$((failures + 1))
  fi
done

if [[ $failures -gt 0 ]]; then
  echo ""
  echo "FAIL: $failures Node-20-only SHA(s) found in $WORKFLOWS_DIR"
  exit 1
fi

echo "PASS: no Node-20-only SHAs found in workflow files"
