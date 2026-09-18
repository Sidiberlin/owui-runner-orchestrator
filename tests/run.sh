#!/usr/bin/env bash
# Lane E entry point. Builds what is missing, runs the suite, tears down.
#
#   ./run.sh              unit + integration (skips the slow ones)
#   ./run.sh --all        everything, including idle/cache-grace timing tests
#   ./run.sh --unit       unit only, no Docker needed
#   ./run.sh -k pattern   pass anything else straight through to pytest
#
# NO_BUILD=1 reuses existing images. The runner image is ~840MB and exporting
# it through BuildKit is memory-hungry; on a small host that export can be
# OOM-killed before any test runs.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
PY=./.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "==> creating test venv"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q pytest pytest-timeout -r ../orchestrator/requirements.txt
fi

MODE="default"
case "${1:-}" in
  --unit) MODE=unit; shift ;;
  --all)  MODE=all;  shift ;;
esac

if [ "$MODE" = "unit" ]; then
  exec $PY -m pytest unit "$@"
fi

# On this LXC host AppArmor profiles cannot be loaded, so `docker build` needs
# a BuildKit daemon running unconfined. See the project README.
if ! docker buildx inspect owui-bk >/dev/null 2>&1; then
  echo "==> creating unconfined buildkit builder (LXC AppArmor workaround)"
  docker rm -f owui-buildkitd >/dev/null 2>&1 || true
  docker run -d --name owui-buildkitd --privileged \
    --security-opt apparmor=unconfined moby/buildkit:latest >/dev/null
  sleep 5
  docker buildx create --name owui-bk --driver remote \
    docker-container://owui-buildkitd >/dev/null
else
  docker start owui-buildkitd >/dev/null 2>&1 || true
  sleep 3
fi

build_if_stale() {  # image, context, newest-source-file
  local img=$1 ctx=$2
  if [ "${NO_BUILD:-0}" = "1" ] && docker image inspect "$img" >/dev/null 2>&1; then
    echo "==> reusing $img (NO_BUILD=1)"; return
  fi
  echo "==> building $img"
  docker buildx build --builder owui-bk --load -t "$img" "$ctx" >/dev/null
}
build_if_stale owui-agent-runner:dev "$ROOT/runner"
build_if_stale owui-orchestrator:dev "$ROOT/orchestrator"

DESELECT=(-m "not slow")
[ "$MODE" = "all" ] && DESELECT=()

set +e
$PY -m pytest "${DESELECT[@]}" "$@"
RC=$?
set -e

echo "==> tearing down"
docker compose --env-file env.test -p owui-runner-test down -v >/dev/null 2>&1 || true
docker rm -f stub-owui-test >/dev/null 2>&1 || true
docker network rm owui-runner-test-owui >/dev/null 2>&1 || true
docker stop owui-buildkitd >/dev/null 2>&1 || true
exit $RC
