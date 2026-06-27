from __future__ import annotations

import logging
import json
import sys
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

try:
    from rich.console import Console as RichConsole
    from rich.highlighter import JSONHighlighter
    from rich.logging import RichHandler
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

from axo_endpoint.shared.envs.log import get_log_config

SUMMARY_RECORD_KEY = "lolypos_summary"


class DumbLogger(object):
    """No-op logger that silently discards all log calls.

    Drop-in replacement for Log when logging is disabled — calling any
    method on this object is a no-op with zero I/O or CPU overhead.
    """

    def debug(self, *args, **kargs):
        return

    def info(self, *args, **kargs):
        return

    def warning(self, *args, **kargs):
        return

    def error(self, *args, **kargs):
        return

    def debug_event(self, *args, **kargs):
        return

    def info_event(self, *args, **kargs):
        return

    def warning_event(self, *args, **kargs):
        return

    def error_event(self, *args, **kargs):
        return


class _DictToJsonFormatter(logging.Formatter):
    """Converts dict log messages to indented JSON strings for RichHandler."""

    def __init__(self, indent: int | None = None):
        """Creates the formatter with an optional indent width for JSON output."""
        super().__init__()
        self.indent = indent

    def format(self, record):
        """Turns a dict log message into a JSON string."""
        if isinstance(record.msg, dict):
            record.msg = json.dumps(record.msg, indent=self.indent, default=str)
            record.args = ()
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """Logging formatter that serialises log records as JSON objects.

    Pass ``indent=4`` (or any int) for human-readable indented output.
    Leave ``indent=None`` (default) for compact single-line NDJSON suitable
    for log files and tools like ``jq``.
    """

    def __init__(self, indent: int | None = None):
        """Creates the formatter with an optional indent width for JSON output."""
        super().__init__()
        self.indent = indent

    def format(self, record):
        """Turns a log record into a JSON string."""
        log_data: dict = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "src_module": record.module,
            "src_fn": record.funcName,
            "src_line": record.lineno,
        }
        endpoint_id = getattr(record, "endpoint_id", None)
        if endpoint_id is not None:
            log_data["endpoint_id"] = endpoint_id
        # Verbose process/thread fields only on DEBUG to keep INFO lines compact.
        if record.levelno == logging.DEBUG:
            log_data["logger_name"] = record.name
            log_data["process_id"] = record.process
            log_data["thread_name"] = threading.current_thread().name
        if isinstance(record.msg, dict):
            log_data.update(record.msg)
        else:
            log_data["message"] = record.getMessage()
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, default=str, indent=self.indent)


class _SummaryInfoFilter(logging.Filter):
    """Only lets through info-level records that were marked as a final summary."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Checks whether a record is a final summary info log."""
        return record.levelno == logging.INFO and getattr(record, SUMMARY_RECORD_KEY, False)


class _ErrorFilter(logging.Filter):
    """Only lets through error-level (and above) records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Checks whether a record is an error or worse."""
        return record.levelno >= logging.ERROR


if _RICH_AVAILABLE:
    class _LevelStyledRichHandler(RichHandler):
        LEVEL_STYLES = {
            logging.DEBUG: "cyan",
            logging.INFO: "green",
            logging.WARNING: "yellow",
            logging.ERROR: "red",
            logging.CRITICAL: "bold red",
        }

        def __init__(self, *args: Any, colorize: bool = True, **kwargs: Any) -> None:
            """Creates the handler, with colored output turned on or off."""
            super().__init__(*args, **kwargs)
            self._colorize = colorize

        def render_message(self, record: logging.LogRecord, message: str) -> "Text":
            """Colors a log message according to its level."""
            rendered = super().render_message(record, message)
            if self._colorize:
                style = self.LEVEL_STYLES.get(record.levelno)
                if style:
                    rendered.stylize(style)
            return rendered


class _EndpointContextFilter(logging.Filter):
    """Injects fixed key/value pairs into every LogRecord emitted by the logger."""

    def __init__(self, **fields: Any) -> None:
        super().__init__()
        self._fields = fields

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self._fields.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class Log(logging.Logger):
    """Structured JSON logger with rotating file and console handlers.

    Extends ``logging.Logger`` to add JSON-formatted output, optional
    timed-rotating file handlers, and a dedicated error log file.  When
    ``disabled=True`` no handlers are attached and no filesystem paths
    are created, making it safe to instantiate in environments where
    disk I/O is unavailable or unwanted.

    When ``use_rich=True`` the console handler uses ``RichHandler`` with
    ``JSONHighlighter`` for syntax-coloured JSON output. Rich remains an
    optional dependency and can be installed with ``poetry install --extras rich``.
    """

    def __init__(self,
                 formatter: logging.Formatter | None = None,
                 console_formatter: logging.Formatter | None = None,
                 name: str = "lolypos",
                 log_level: int | None = None,
                 path: str | None = None,
                 disabled: bool | None = None,
                 console_handler_level: int | None = None,
                 file_handler_level: int | None = None,
                 error_log: bool | None = None,
                 filename: str | None = None,
                 output_path: str | None = None,
                 error_output_path: str | None = None,
                 to_file: bool | None = None,
                 when: str | None = None,
                 interval: int | None = None,
                 use_rich: bool | None = None,
                 endpoint_id: str | None = None,
    ):
        """Creates a logger, filling in any unset options from the environment."""
        config = get_log_config()
        self._endpoint_id = endpoint_id
        if path is None:
            path = str(config["path"])
        if disabled is None:
            disabled = bool(config["disabled"])
        if log_level is None:
            log_level = int(config["log_level"])
        if to_file is None:
            to_file = bool(config["to_file"])
        if when is None:
            when = str(config["when"])
        if interval is None:
            interval = int(config["interval"])
        if use_rich is None:
            use_rich = bool(config["use_rich"])
        colorize = bool(config["colorize"])
        if error_log is None:
            error_log = bool(config["error_log"])
        if console_handler_level is None:
            console_handler_level = int(config["console_handler_level"])
        if file_handler_level is None:
            file_handler_level = int(config["file_handler_level"])

        indent = config["indent"]

        super().__init__(name, log_level)
        self.propagate = False

        if disabled:
            self.addHandler(logging.NullHandler())
            return

        if console_formatter is None:
            console_formatter = JsonFormatter(indent=indent)
        if formatter is None:
            formatter = JsonFormatter()

        if use_rich:
            if not _RICH_AVAILABLE:
                raise ImportError(
                    "rich is not installed. Install it with: poetry install --extras rich"
                )
            console_handler = _LevelStyledRichHandler(
                rich_tracebacks=True,
                markup=False,
                show_path=False,
                highlighter=JSONHighlighter(),
                console=RichConsole(file=sys.stdout),
                colorize=colorize,
            )
            console_handler.setFormatter(_DictToJsonFormatter(indent=indent))
        else:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(console_formatter)

        console_handler.setLevel(console_handler_level)
        self.addHandler(console_handler)

        if endpoint_id is not None:
            self.addFilter(_EndpointContextFilter(endpoint_id=endpoint_id))

        needs_directory = to_file or error_log
        if needs_directory:
            Path(path).mkdir(parents=True, exist_ok=True)

        if to_file:
            filehandler = TimedRotatingFileHandler(
                filename=output_path or str(config["output_path"] or "") or "{}/{}.log".format(path, filename or str(config["filename"]) or name),
                when=when,
                interval=interval,
            )
            filehandler.setFormatter(formatter)
            filehandler.setLevel(file_handler_level)
            filehandler.addFilter(_SummaryInfoFilter())
            self.addHandler(filehandler)

        if error_log:
            errorFilehandler = TimedRotatingFileHandler(
                filename=error_output_path or str(config["error_output_path"] or "") or "{}/{}.error.log".format(path, filename or str(config["filename"]) or name),
                when=when,
                interval=interval,
            )
            errorFilehandler.setFormatter(formatter)
            errorFilehandler.setLevel(logging.ERROR)
            errorFilehandler.addFilter(_ErrorFilter())
            self.addHandler(errorFilehandler)

    def log_event(
        self,
        level: int,
        event: str,
        message: str | None = None,
        final: bool = False,
        stacklevel: int = 2,
        **context: Any,
    ) -> None:
        """Logs a structured event with a message and any extra fields."""
        payload: dict[str, Any] = {"event": event}
        if message is not None:
            payload["message"] = message
        payload.update({key: value for key, value in context.items() if value is not None})
        self.log(
            level,
            payload,
            extra={SUMMARY_RECORD_KEY: final},
            stacklevel=stacklevel,
        )

    def debug_event(
        self,
        event: str,
        message: str | None = None,
        stacklevel: int = 3,
        **context: Any,
    ) -> None:
        """Logs a debug-level event."""
        self.log_event(
            logging.DEBUG,
            event,
            message=message,
            stacklevel=stacklevel,
            **context,
        )

    def info_event(
        self,
        event: str,
        message: str | None = None,
        stacklevel: int = 3,
        **context: Any,
    ) -> None:
        """Logs an informational event."""
        self.log_event(
            logging.INFO,
            event,
            message=message,
            stacklevel=stacklevel,
            **context,
        )

    def warning_event(
        self,
        event: str,
        message: str | None = None,
        stacklevel: int = 3,
        **context: Any,
    ) -> None:
        """Logs a warning-level event."""
        self.log_event(
            logging.WARNING,
            event,
            message=message,
            stacklevel=stacklevel,
            **context,
        )

    def error_event(
        self,
        event: str,
        message: str | None = None,
        stacklevel: int = 3,
        **context: Any,
    ) -> None:
        """Logs an error-level event."""
        self.log_event(
            logging.ERROR,
            event,
            message=message,
            stacklevel=stacklevel,
            **context,
        )

    def final_info(
        self,
        event: str,
        message: str | None = None,
        stacklevel: int = 3,
        **context: Any,
    ) -> None:
        """Logs an informational event marked as the final summary for this operation."""
        self.log_event(
            logging.INFO,
            event,
            message=message,
            final=True,
            stacklevel=stacklevel,
            **context,
        )
