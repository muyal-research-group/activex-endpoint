from __future__ import annotations

import logging
import os


def _get_bool(name: str, default: bool) -> bool:
    """Reads a true/false setting from an environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    """Reads a whole-number setting from an environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_level(name: str, default: str) -> int:
    """Reads a logging level (like "DEBUG" or "INFO") from an environment variable."""
    return getattr(logging, os.environ.get(name, default).upper(), getattr(logging, default))


def _get_indent(name: str) -> int | None:
    """Reads how many spaces to indent JSON logs by, if any."""
    value = os.environ.get(name, "0")
    if not value.isdigit():
        return None
    indent = int(value)
    return indent if indent > 0 else None


LOG_LEVEL = _get_level("AXO_ENDPOINT_LOG_LEVEL", "DEBUG")
LOG_DISABLED = _get_bool("AXO_ENDPOINT_LOG_DISABLED", False)
LOG_TO_FILE = _get_bool("AXO_ENDPOINT_LOG_TO_FILE", False)
LOG_PATH = os.environ.get("AXO_ENDPOINT_LOG_PATH", ".axo_endpoint/log")
LOG_FILENAME = os.environ.get("AXO_ENDPOINT_LOG_FILENAME", "axo_endpoint")
LOG_OUTPUT_PATH = os.environ.get("AXO_ENDPOINT_LOG_OUTPUT_PATH")
LOG_ERROR_OUTPUT_PATH = os.environ.get("AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH")
LOG_CONSOLE_LEVEL = _get_level("AXO_ENDPOINT_LOG_CONSOLE_LEVEL", "DEBUG")
LOG_FILE_LEVEL = _get_level("AXO_ENDPOINT_LOG_FILE_LEVEL", "INFO")
LOG_ERROR_FILE = _get_bool("AXO_ENDPOINT_LOG_ERROR_FILE", False)
LOG_ROTATION_WHEN = os.environ.get("AXO_ENDPOINT_LOG_ROTATION_WHEN", "midnight")
LOG_ROTATION_INTERVAL = _get_int("AXO_ENDPOINT_LOG_ROTATION_INTERVAL", 1)
LOG_JSON_INDENT = _get_indent("AXO_ENDPOINT_LOG_JSON_INDENT")
LOG_USE_RICH = _get_bool("AXO_ENDPOINT_LOG_USE_RICH", False)
LOG_COLORIZE = _get_bool("AXO_ENDPOINT_LOG_COLORIZE", True)


def get_log_config() -> dict[str, object]:
    """Reads all logging settings from environment variables."""
    return {
        "log_level": _get_level("AXO_ENDPOINT_LOG_LEVEL", "DEBUG"),
        "disabled": _get_bool("AXO_ENDPOINT_LOG_DISABLED", False),
        "to_file": _get_bool("AXO_ENDPOINT_LOG_TO_FILE", False),
        "path": os.environ.get("AXO_ENDPOINT_LOG_PATH", ".axo_endpoint/log"),
        "filename": os.environ.get("AXO_ENDPOINT_LOG_FILENAME", "axo_endpoint"),
        "output_path": os.environ.get("AXO_ENDPOINT_LOG_OUTPUT_PATH"),
        "error_output_path": os.environ.get("AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH"),
        "console_handler_level": _get_level("AXO_ENDPOINT_LOG_CONSOLE_LEVEL", "DEBUG"),
        "file_handler_level": _get_level("AXO_ENDPOINT_LOG_FILE_LEVEL", "INFO"),
        "error_log": _get_bool("AXO_ENDPOINT_LOG_ERROR_FILE", False),
        "when": os.environ.get("AXO_ENDPOINT_LOG_ROTATION_WHEN", "midnight"),
        "interval": _get_int("AXO_ENDPOINT_LOG_ROTATION_INTERVAL", 1),
        "indent": _get_indent("AXO_ENDPOINT_LOG_JSON_INDENT"),
        "use_rich": _get_bool("AXO_ENDPOINT_LOG_USE_RICH", False),
        "colorize": _get_bool("AXO_ENDPOINT_LOG_COLORIZE", True),
    }
