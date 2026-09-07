import argparse
import os

_FLAG_ENV_MAP = [
    ("router-bind",           "AXO_VEM_ROUTER_BIND",           "ZMQ ingestion router bind address"),
    ("http-host",             "AXO_VEM_HTTP_HOST",             "HTTP host to bind FastAPI on"),
    ("http-port",             "AXO_VEM_HTTP_PORT",             "HTTP port to bind FastAPI on"),
    ("kurrent-uri",           "AXO_VEM_KURRENT_URI",           "Kurrent(DB) connection URI"),
    ("mongo-uri",             "AXO_VEM_MONGO_URI",             "MongoDB connection URI"),
    ("mongo-db-name",         "AXO_VEM_MONGO_DB_NAME",         "MongoDB database name"),
    ("log-level",             "AXO_VEM_LOG_LEVEL",             "Log level (DEBUG/INFO/WARNING/ERROR)"),
    ("log-disabled",          "AXO_VEM_LOG_DISABLED",          "Disable logging (true/false)"),
    ("log-to-file",           "AXO_VEM_LOG_TO_FILE",           "Write logs to file (true/false)"),
    ("log-path",              "AXO_VEM_LOG_PATH",              "Log directory"),
    ("log-filename",          "AXO_VEM_LOG_FILENAME",          "Log base filename"),
    ("log-output-path",       "AXO_VEM_LOG_OUTPUT_PATH",       "Override full log output path"),
    ("log-error-output-path", "AXO_VEM_LOG_ERROR_OUTPUT_PATH", "Override full error log path"),
    ("log-console-level",     "AXO_VEM_LOG_CONSOLE_LEVEL",     "Console handler log level"),
    ("log-file-level",        "AXO_VEM_LOG_FILE_LEVEL",        "File handler log level"),
    ("log-error-file",        "AXO_VEM_LOG_ERROR_FILE",        "Write separate error log (true/false)"),
    ("log-rotation-when",     "AXO_VEM_LOG_ROTATION_WHEN",     "Log rotation trigger (midnight/h/d)"),
    ("log-rotation-interval", "AXO_VEM_LOG_ROTATION_INTERVAL", "Log rotation interval"),
    ("log-json-indent",       "AXO_VEM_LOG_JSON_INDENT",       "JSON log indent (0=compact)"),
    ("log-use-rich",          "AXO_VEM_LOG_USE_RICH",          "Use rich console formatting (true/false)"),
    ("log-colorize",          "AXO_VEM_LOG_COLORIZE",          "Colorize console output (true/false)"),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="axo-vem",
        description=(
            "Launch the axo_vem cluster-management service.\n"
            "Priority: CLI flags > shell env vars > env file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="Path to .env file to load (default: $AXO_VEM_ENV_FILE or .env)",
    )
    for flag, _, help_text in _FLAG_ENV_MAP:
        parser.add_argument(f"--{flag}", default=None, metavar="VALUE", help=help_text)

    args = parser.parse_args()

    # Inject env vars before any axo_vem import -- axo_vem.main
    # loads the env file as its first action, so anything set here must land
    # in os.environ before that import happens.
    if args.env_file is not None:
        os.environ["AXO_VEM_ENV_FILE"] = args.env_file

    for flag, env_var, _ in _FLAG_ENV_MAP:
        value = getattr(args, flag.replace("-", "_"))
        if value is not None:
            os.environ[env_var] = value

    from axo_vem.main import main as _run
    _run()


if __name__ == "__main__":
    main()
