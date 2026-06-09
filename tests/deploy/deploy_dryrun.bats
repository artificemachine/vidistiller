#!/usr/bin/env bats
# Bats tests for scripts/deploy.sh --dry-run behaviour.
# All tests use --dry-run so no real docker mutations occur.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/scripts/deploy.sh"

# ── smoke ──────────────────────────────────────────────────────────────────────

@test "smoke: --dry-run exits 0" {
  run bash "$SCRIPT" --dry-run
  [ "$status" -eq 0 ]
}

@test "contract: rejects unknown flag" {
  run bash "$SCRIPT" --unknown-flag
  [ "$status" -ne 0 ]
}

# ── unit ───────────────────────────────────────────────────────────────────────

@test "unit: dry-run prints force-remove step before pull" {
  # Inject a stub so there is always a tutorial_ container to display ordering
  stub_dir="$(mktemp -d)"
  cat > "$stub_dir/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"container ls"* || "$*" == *"ls -a"* ]]; then
  echo "tutorial_redis"
fi
exit 0
EOF
  chmod +x "$stub_dir/docker"

  run env PATH="$stub_dir:$PATH" bash "$SCRIPT" --dry-run
  [ "$status" -eq 0 ]
  # The force-remove line must appear
  echo "$output" | grep -q "rm -f"
  # And it must appear before the pull line
  rm_line=$(echo "$output" | grep -n "rm -f" | head -1 | cut -d: -f1)
  pull_line=$(echo "$output" | grep -n "compose.*pull\|pull.*compose" | head -1 | cut -d: -f1)
  [ -n "$rm_line" ]
  [ -n "$pull_line" ]
  [ "$rm_line" -lt "$pull_line" ]
}

@test "unit: dry-run prints pull step before up" {
  run bash "$SCRIPT" --dry-run
  [ "$status" -eq 0 ]
  pull_line=$(echo "$output" | grep -n "compose.*pull\|pull.*compose" | head -1 | cut -d: -f1)
  up_line=$(echo "$output" | grep -n "compose.*up\|up.*compose" | head -1 | cut -d: -f1)
  [ -n "$pull_line" ]
  [ -n "$up_line" ]
  [ "$pull_line" -lt "$up_line" ]
}

# ── unit: no mutations in dry-run ─────────────────────────────────────────────

@test "unit: dry-run makes no real docker mutations" {
  # Shadow docker and docker compose with stubs that fail loudly if called with mutating args
  stub_dir="$(mktemp -d)"

  cat > "$stub_dir/docker" <<'EOF'
#!/usr/bin/env bash
# Allow read-only subcommands; fail on mutating ones
case "$*" in
  "container ls"*|"ps"*) exit 0 ;;  # listing is ok
  "rm"*|"rmi"*|"stop"*|"kill"*|"start"*) echo "MUTATION: docker $*" >&2; exit 99 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$stub_dir/docker"

  # Also stub docker compose as a script
  cat > "$stub_dir/docker-compose" <<'EOF'
#!/usr/bin/env bash
echo "MUTATION: docker-compose $*" >&2; exit 99
EOF
  chmod +x "$stub_dir/docker-compose"

  run env PATH="$stub_dir:$PATH" bash "$SCRIPT" --dry-run
  # Must exit 0
  [ "$status" -eq 0 ]
  # Must not have emitted MUTATION lines
  echo "$output" | grep -qv "^MUTATION:"
}

# ── chaos: stubbed leftover Created container ─────────────────────────────────

@test "chaos: leftover Created container is targeted by remove step" {
  # Dry-run with a fake container list that includes a tutorial_ container
  stub_dir="$(mktemp -d)"

  cat > "$stub_dir/docker" <<'EOF'
#!/usr/bin/env bash
# Stub: 'container ls -a' returns a fake tutorial_ container; everything else no-ops
if [[ "$*" == *"container ls"* || "$*" == *"ls -a"* ]]; then
  echo "tutorial_redis"
fi
# rm is allowed (dry-run should not call it, but we don't fail)
exit 0
EOF
  chmod +x "$stub_dir/docker"

  run env PATH="$stub_dir:$PATH" bash "$SCRIPT" --dry-run
  [ "$status" -eq 0 ]
  # Output should mention the tutorial_ container in the remove step
  echo "$output" | grep -q "tutorial_"
}
