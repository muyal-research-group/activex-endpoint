#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
COMPOSE_ENV_FILE="${SCRIPT_DIR}/deploy/env/compose.env"

usage() {
  echo "Usage: $0 <command> [options]"
  echo ""
  echo "Commands:"
  echo "  up [--build]   Start all services (add --build to rebuild compose"
  echo "                 images plus the axo-endpoint node image used for"
  echo "                 dynamically-launched endpoints, and pre-build the"
  echo "                 axo-runner image so it's already there on next use)"
  echo "  down           Stop and remove containers"
  echo "  restart        Restart all services"
  echo "  logs [service] Follow logs (all services or a specific one)"
  echo "  ps             Show running containers"
  echo "  pull           Pull latest images"
  echo ""
  echo "Env file: ${COMPOSE_ENV_FILE}"
}

CMD="${1:-up}"
shift || true

BASE_CMD=(docker compose
  --file "$COMPOSE_FILE"
  --env-file "$COMPOSE_ENV_FILE"
)

case "$CMD" in
  up)
    # --build rebuilds compose services (axo-vem, ...) via the flag passed
    # straight through in "$@" below, PLUS two images compose can never
    # reach on its own:
    #   - axo-endpoint:local: endpoint nodes aren't compose services --
    #     they're created dynamically from axo-ui via axo_vem's
    #     POST /endpoints (LaunchEndpointNodeUseCase -> ContainerSpawner.spawn,
    #     a plain `docker run` against AXO_VEM_NODE_IMAGE, default
    #     axo-endpoint:local). No compose service has a build: section for
    #     that tag, so `docker compose build`/`up --build` silently never
    #     touches it -- it goes stale across deploys unless built here
    #     directly.
    #   - axo-runner:pyX.Y: otherwise only ever built lazily by the running
    #     endpoint process itself (ContainerSummoner._ensure_image, the
    #     first time a container-runtime function needs it -- see
    #     axo_endpoint/service/container/spawner.py). Pre-building it here
    #     means that first-use build happens once, up front, instead of
    #     racing N concurrent cold-start pool members (e.g. a function
    #     registered with max_concurrency=5) into starting N redundant
    #     `docker build`s of the same image at once.
    for arg in "$@"; do
      if [ "$arg" == "--build" ]; then
        # Bring AXO_ENDPOINT_DOCKERFILE/AXO_ENDPOINT_IMAGE/runner vars into
        # the shell -- plain `docker build` below doesn't get compose's
        # --env-file substitution, so the env file needs sourcing directly.
        set -a
        # shellcheck disable=SC1090
        source "$COMPOSE_ENV_FILE"
        set +a
        docker build \
          --file "${SCRIPT_DIR}/${AXO_ENDPOINT_DOCKERFILE:-Dockerfile}" \
          --tag "${AXO_ENDPOINT_IMAGE:-axo-endpoint:local}" \
          "$SCRIPT_DIR"

        # Matches ContainerSummoner._runner_image()'s own tag convention
        # (AXO_ENDPOINT_CONTAINER_RUNNER_IMAGE:py<python_version>) -- keep
        # AXO_ENDPOINT_RUNNER_PYTHON_VERSION in sync with whatever
        # python_version your functions actually register with (default
        # "3.11") if you rely on this pre-build to cover them.
        docker build \
          --file "${SCRIPT_DIR}/axo_endpoint/runner/Dockerfile" \
          --tag "${AXO_ENDPOINT_RUNNER_IMAGE:-axo-runner}:py${AXO_ENDPOINT_RUNNER_PYTHON_VERSION:-3.11}" \
          --build-arg "PYTHON_VERSION=${AXO_ENDPOINT_RUNNER_PYTHON_VERSION:-3.11}" \
          "$SCRIPT_DIR"
        break
      fi
    done
    "${BASE_CMD[@]}" up -d "$@"
    ;;
  down)
    "${BASE_CMD[@]}" down "$@"
    ;;
  restart)
    "${BASE_CMD[@]}" restart "$@"
    ;;
  logs)
    "${BASE_CMD[@]}" logs -f "$@"
    ;;
  ps)
    "${BASE_CMD[@]}" ps
    ;;
  pull)
    "${BASE_CMD[@]}" pull
    ;;
  help|--help|-h)
    usage
    ;;
  *)
    echo "Unknown command: $CMD"
    usage
    exit 1
    ;;
esac
