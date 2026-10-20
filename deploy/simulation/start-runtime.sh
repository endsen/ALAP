#!/bin/sh
# Foreground, project-local rootless daemon. No global config or systemd changes.
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
umask 077
mkdir -p "$PROJECT_ROOT/.local-deploy/run" "$PROJECT_ROOT/.local-deploy/docker-data"
export PATH="$PROJECT_ROOT/.local-deploy/bin:$PATH"
export XDG_RUNTIME_DIR="$PROJECT_ROOT/.local-deploy/run"
export DOCKERD_ROOTLESS_ROOTLESSKIT_STATE_DIR="$XDG_RUNTIME_DIR/rootlesskit"
export HTTP_PROXY="${ALAP_DOCKER_PROXY:-${HTTP_PROXY:-}}"
export HTTPS_PROXY="${ALAP_DOCKER_PROXY:-${HTTPS_PROXY:-}}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1,.local,10.0.0.0/8,198.18.0.0/15}"
exec dockerd-rootless.sh \
  --data-root "$PROJECT_ROOT/.local-deploy/docker-data" \
  --exec-root "$XDG_RUNTIME_DIR/docker-exec" \
  --pidfile "$XDG_RUNTIME_DIR/docker.pid" \
  --host "unix://$XDG_RUNTIME_DIR/docker.sock"
