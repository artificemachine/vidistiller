#!/usr/bin/env bash
# Asserts that a valid e2e job is wired in .github/workflows/test.yml.
# RED when no e2e job exists, GREEN after iteration 5 adds it.

set -euo pipefail

TEST_YML="$(cd "$(dirname "$0")/../.." && pwd)/.github/workflows/test.yml"

if [[ ! -f "$TEST_YML" ]]; then
  echo "FAIL: $TEST_YML not found"
  exit 1
fi

failures=0

# 1. An e2e job must be declared
if ! grep -q "e2e" "$TEST_YML"; then
  echo "FAIL: no e2e job found in $TEST_YML"
  failures=$((failures + 1))
fi

# 2. The job must reference the e2e compose file
if ! grep -q "docker-compose.e2e.yml" "$TEST_YML"; then
  echo "FAIL: docker-compose.e2e.yml not referenced in e2e job"
  failures=$((failures + 1))
fi

# 3. Playwright must be invoked
if ! grep -q "playwright" "$TEST_YML"; then
  echo "FAIL: playwright not invoked in CI"
  failures=$((failures + 1))
fi

if [[ $failures -gt 0 ]]; then
  echo "FAIL: $failures check(s) failed in $TEST_YML"
  exit 1
fi

echo "PASS: e2e job present and references docker-compose.e2e.yml + playwright"
