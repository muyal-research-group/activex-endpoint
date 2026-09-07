from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any, Callable, List

import cloudpickle
import zmq

from axo_shared.functions.source import materialize_function_from_source
from axo_shared.protocol import Command
from axo_shared.wire import (
    CONTAINER_BOOTSTRAP,
    decode_command_result,
    encode_command,
)

logger = logging.getLogger("axo.runner.bootstrap")


def fetch_code(
    endpoint_address: str,
    function_id: str,
    version: int,
    timeout_ms: int = 30_000,
) -> tuple[bytes, str, List[str], str]:
    """Connects to the endpoint, requests function code and requirements.

    Returns (code_bytes, code_format, requirements_list, name) -- does not
    turn the code into a callable; see materialize_function(). ``name`` is
    the function's registered display name, required (not function_id) to
    materialize "source"-format code, since the uploaded module defines a
    top-level function named after it, not after the content-hash id.
    """
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.connect(endpoint_address)

    logger.info("bootstrapping function_id=%s version=%d from %s", function_id, version, endpoint_address)

    cmd = Command(
        operation=CONTAINER_BOOTSTRAP,
        content_type="application/json",
        envelope={"function_id": function_id, "version": version},
        payload=b"",
    )
    sock.send_multipart(encode_command(cmd))

    try:
        frames = sock.recv_multipart()
    except zmq.Again:
        sock.close()
        raise RuntimeError(f"no bootstrap reply from {endpoint_address} within {timeout_ms}ms")

    sock.close()

    result = decode_command_result(frames)
    if result.is_err:
        raise RuntimeError(f"bootstrap decode error: {result.unwrap_err()}")

    cr = result.unwrap()
    if not cr.ok:
        raise RuntimeError(f"bootstrap failed: {cr.error}")

    requirements: List[str] = cr.metadata.get("requirements", [])
    code_format: str = cr.metadata.get("code_format", "cloudpickle")
    name: str = cr.metadata.get("name", function_id)
    return cr.payload, code_format, requirements, name


def materialize_function(code_bytes: bytes, code_format: str, function_name: str) -> Callable[..., Any]:
    """Turns fetched code into a callable -- for a source-format function,
    this must run after install_requirements(), since its module body may
    import them."""
    if code_format == "source":
        return materialize_function_from_source(code_bytes, function_name)
    return cloudpickle.loads(code_bytes)


def install_requirements(requirements: List[str]) -> None:
    """Installs pip packages into the running container's environment."""
    if not requirements:
        return
    logger.info("installing requirements: %s", requirements)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", *requirements],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip install failed:\n{result.stderr}")
    logger.info("requirements installed successfully")
