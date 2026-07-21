import argparse
import os
import sys

_FLAG_ENV_MAP = [
    ("id",                          "AXO_ENDPOINT_ID",                           "Node identity name"),
    ("router-bind",                 "AXO_ENDPOINT_ROUTER_BIND",                  "ZMQ router bind address"),
    ("pub-bind",                    "AXO_ENDPOINT_PUB_BIND",                     "ZMQ pub bind address"),
    ("sub-connect",                 "AXO_ENDPOINT_SUB_CONNECT",                  "Comma-separated pub addresses to subscribe to"),
    ("local-mode",                  "AXO_ENDPOINT_LOCAL_MODE",                   "Use localhost for peer addresses (true/false)"),
    ("consensus-replication-idle-seconds", "AXO_ENDPOINT_CONSENSUS_REPLICATION_IDLE_SECONDS", "Idle seconds before flushing replicated state"),
    ("consensus-replication-max-dirty",    "AXO_ENDPOINT_CONSENSUS_REPLICATION_MAX_DIRTY",    "Max dirty entries before flushing replicated state"),
    ("consensus-forward-timeout-seconds",  "AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS",  "Seconds a follower waits when forwarding to the leader"),
    ("heartbeat-interval-seconds",  "AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS",   "Heartbeat interval (s)"),
    ("heartbeat-ttl-seconds",       "AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS",        "Peer stale threshold (s)"),
    ("queue-max-depth",             "AXO_ENDPOINT_QUEUE_MAX_DEPTH",              "Max queue depth"),
    ("queue-workers",               "AXO_ENDPOINT_QUEUE_WORKERS",                "Concurrent worker count"),
    ("worker-idle-ttl-seconds",     "AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS",      "Idle worker recycle TTL (s)"),
    ("worker-gc-interval-seconds",  "AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS",   "Worker GC interval (s)"),
    ("worker-max-invocations",      "AXO_ENDPOINT_WORKER_MAX_INVOCATIONS",       "Max invocations before recycle (0=unlimited)"),
    ("worker-rlimit-memory",        "AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES",       "Virtual memory limit per worker (bytes)"),
    ("worker-rlimit-cpu-seconds",   "AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS",    "CPU time limit per worker (s)"),
    ("scratch-root",                "AXO_ENDPOINT_SCRATCH_ROOT",                 "Scratch directory root"),
    ("scratch-gc-interval-seconds", "AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS",  "Scratch GC interval (s)"),
    ("dataio-fs-root",              "AXO_ENDPOINT_DATAIO_FS_ROOT",               "Root directory for the filesystem dataio backend"),
    ("dataio-timeout-seconds",      "AXO_ENDPOINT_DATAIO_TIMEOUT_SECONDS",       "Seconds to wait for an in-job dataio round trip before failing"),
    ("log-level",                   "AXO_ENDPOINT_LOG_LEVEL",                    "Log level (DEBUG/INFO/WARNING/ERROR)"),
    ("log-disabled",                "AXO_ENDPOINT_LOG_DISABLED",                 "Disable logging (true/false)"),
    ("log-to-file",                 "AXO_ENDPOINT_LOG_TO_FILE",                  "Write logs to file (true/false)"),
    ("log-path",                    "AXO_ENDPOINT_LOG_PATH",                     "Log directory"),
    ("log-filename",                "AXO_ENDPOINT_LOG_FILENAME",                 "Log base filename"),
    ("log-output-path",             "AXO_ENDPOINT_LOG_OUTPUT_PATH",              "Override full log output path"),
    ("log-error-output-path",       "AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH",        "Override full error log path"),
    ("log-console-level",           "AXO_ENDPOINT_LOG_CONSOLE_LEVEL",            "Console handler log level"),
    ("log-file-level",              "AXO_ENDPOINT_LOG_FILE_LEVEL",               "File handler log level"),
    ("log-error-file",              "AXO_ENDPOINT_LOG_ERROR_FILE",               "Write separate error log (true/false)"),
    ("log-rotation-when",           "AXO_ENDPOINT_LOG_ROTATION_WHEN",            "Log rotation trigger (midnight/h/d)"),
    ("log-rotation-interval",       "AXO_ENDPOINT_LOG_ROTATION_INTERVAL",        "Log rotation interval"),
    ("log-json-indent",             "AXO_ENDPOINT_LOG_JSON_INDENT",              "JSON log indent (0=compact)"),
    ("log-use-rich",                "AXO_ENDPOINT_LOG_USE_RICH",                 "Use rich console formatting (true/false)"),
    ("log-colorize",                "AXO_ENDPOINT_LOG_COLORIZE",                 "Colorize console output (true/false)"),
    # Container runtime
    ("container-backend",           "AXO_ENDPOINT_CONTAINER_BACKEND",            "Container backend: docker or swarm"),
    ("container-network",           "AXO_ENDPOINT_CONTAINER_NETWORK",            "Docker network for function containers"),
    ("container-result-bind",       "AXO_ENDPOINT_CONTAINER_RESULT_BIND",        "ZMQ PULL address for container results"),
    ("container-job-port",          "AXO_ENDPOINT_CONTAINER_JOB_PORT",           "Port containers bind for ZMQ job dispatch"),
    ("container-fastapi-port",      "AXO_ENDPOINT_CONTAINER_FASTAPI_PORT",       "Port containers bind for FastAPI"),
    ("container-readiness-timeout", "AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS", "Seconds to wait for container readiness"),
    ("container-pip-cache-volume",  "AXO_ENDPOINT_CONTAINER_PIP_CACHE_VOLUME",   "Docker volume name for pip cache"),
    ("container-runner-image",      "AXO_ENDPOINT_CONTAINER_RUNNER_IMAGE",       "Base runner image name"),
    ("container-auto-build-image",  "AXO_ENDPOINT_CONTAINER_AUTO_BUILD_IMAGE",   "Auto-build runner image if missing (true/false)"),
]


def _ensure_malloc_arena_cap() -> None:
    """Re-execs with MALLOC_ARENA_MAX set, if it isn't already.

    glibc reads this var once, at first malloc — before our own code ever runs —
    so setting os.environ here has no effect on the *current* process. Only a
    fresh process (via re-exec) picks it up. Without this cap, glibc gives each
    thread its own ~64MB arena reservation, bloating the service's virtual
    memory footprint; forked worker processes inherit that bloat and can hit
    their RLIMIT_AS before doing any real work.
    """
    if "MALLOC_ARENA_MAX" in os.environ:
        return
    os.environ["MALLOC_ARENA_MAX"] = "2"
    os.execve(sys.executable, [sys.executable] + sys.argv, os.environ)


def main() -> None:
    _ensure_malloc_arena_cap()

    parser = argparse.ArgumentParser(
        prog="axo-endpoint",
        description=(
            "Launch an axo endpoint node.\n"
            "Priority: CLI flags > shell env vars > env file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="Path to .env file to load (default: $AXO_ENDPOINT_ENV_FILE or .env.dev)",
    )
    for flag, _, help_text in _FLAG_ENV_MAP:
        parser.add_argument(f"--{flag}", default=None, metavar="VALUE", help=help_text)

    args = parser.parse_args()

    # Inject env vars before any axo_endpoint import — imports trigger dotenv loading
    # (shared/envs/__init__.py calls load_dotenv with override=False, so values set
    # here will win over whatever the file contains)
    if args.env_file is not None:
        os.environ["AXO_ENDPOINT_ENV_FILE"] = args.env_file

    for flag, env_var, _ in _FLAG_ENV_MAP:
        value = getattr(args, flag.replace("-", "_"))
        if value is not None:
            os.environ[env_var] = value

    from axo_endpoint.main import main as _run
    _run()


if __name__ == "__main__":
    main()
