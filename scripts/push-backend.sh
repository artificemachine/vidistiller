#!/usr/bin/env bash
# Push the current running backend container to Docker Hub from the VM.
# Requires interactive Docker Hub login on first run.
set -euo pipefail

# SSH target. Defaults to the `vidistiller` host alias — define it in ~/.ssh/config
# so deployment topology stays out of the repo. Override with VIDISTILLER_SSH.
VM="${VIDISTILLER_SSH:-vidistiller}"
IMAGE="${VIDISTILLER_BACKEND_IMAGE:-newblacc/vidistiller-backend:latest}"
CONTAINER="${VIDISTILLER_API_CONTAINER:-tutorial_api}"

echo "==> Committing $CONTAINER → $IMAGE on VM..."
ssh "$VM" "docker commit $CONTAINER $IMAGE"

echo "==> Pushing $IMAGE from VM (login required if not cached)..."
ssh -t "$VM" "docker push $IMAGE || (docker login && docker push $IMAGE)"

echo "==> Done: $IMAGE pushed from VM."
