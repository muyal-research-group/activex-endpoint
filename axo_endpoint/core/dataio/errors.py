from __future__ import annotations

from axo_endpoint.core.errors import AxoError

# ── 7xxx: dataio (proxied read/write) ─────────────────────────────────────────


class DataIOError(AxoError):
    """Base class for all proxied dataio failure modes."""

    code = 7000
    name = "DATAIO_ERROR"


class UnknownIOOpError(DataIOError):
    code = 7001
    name = "UNKNOWN_IO_OP"


class UnknownIORefKindError(DataIOError):
    code = 7002
    name = "UNKNOWN_IO_REF_KIND"


class UnknownIOFormatError(DataIOError):
    code = 7003
    name = "UNKNOWN_IO_FORMAT"


class IOPathTraversalError(DataIOError):
    """A ref's location resolved outside its blob backend's root."""

    code = 7004
    name = "IO_PATH_TRAVERSAL"


class IONotFoundError(DataIOError):
    code = 7005
    name = "IO_NOT_FOUND"


class IOBackendError(DataIOError):
    code = 7006
    name = "IO_BACKEND_ERROR"


class DataIOTimeoutError(DataIOError):
    """No io_reply arrived within the configured dataio timeout."""

    code = 7007
    name = "DATAIO_TIMEOUT"


class MalformedIOFrameError(DataIOError):
    code = 7008
    name = "MALFORMED_IO_FRAME"


class DataIOUnavailableError(DataIOError):
    """dataio.read/write was called with no channel bound for this invocation
    (e.g. from the direct-HTTP-invoke path, which has no endpoint round trip)."""

    code = 7009
    name = "DATAIO_UNAVAILABLE"


class IOFormatUnavailableError(DataIOError):
    """A known format name was requested, but its optional dependency isn't
    installed (e.g. "csv" without the pandas extra) -- distinct from
    UnknownIOFormatError, which is for format names that don't exist at all."""

    code = 7010
    name = "IO_FORMAT_UNAVAILABLE"
