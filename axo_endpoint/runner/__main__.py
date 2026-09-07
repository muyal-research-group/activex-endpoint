"""Container runner entrypoint.

Expected environment variables:
  AXO_ENDPOINT_ADDRESS   - ZMQ address of the endpoint ROUTER (e.g. tcp://axo-endpoint:5555)
  AXO_RESULT_ADDRESS     - ZMQ address of the endpoint PULL socket (e.g. tcp://axo-endpoint:5557)
  AXO_FUNCTION_ID        - Registered function's content-hash id
  AXO_FUNCTION_VERSION   - Function version (int)
  AXO_JOB_PORT           - Port for the ZMQ ROUTER that receives jobs (default: 5600)
  AXO_FASTAPI_PORT       - Port for the FastAPI HTTP server (default: 8000)
"""
from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("axo.runner")


def main() -> None:
    endpoint_address = os.environ.get("AXO_ENDPOINT_ADDRESS", "")
    result_address   = os.environ.get("AXO_RESULT_ADDRESS", "")
    function_id      = os.environ.get("AXO_FUNCTION_ID", "")
    version_str      = os.environ.get("AXO_FUNCTION_VERSION", "0")
    job_port         = int(os.environ.get("AXO_JOB_PORT", "5600"))
    fastapi_port     = int(os.environ.get("AXO_FASTAPI_PORT", "8000"))
    scratch_root     = os.environ.get("AXO_SCRATCH_ROOT", "/tmp/axo_runner/scratch")
    dataio_timeout   = float(os.environ.get("AXO_DATAIO_TIMEOUT_SECONDS", "30.0"))

    if not endpoint_address or not function_id:
        logger.error("AXO_ENDPOINT_ADDRESS and AXO_FUNCTION_ID are required")
        sys.exit(1)

    version = int(version_str)

    from axo_endpoint.runner.bootstrap import fetch_code, install_requirements, materialize_function
    from axo_endpoint.runner.job_store import JobStore
    from axo_endpoint.runner.server import RunnerServer

    logger.info("fetching function %s v%d from %s", function_id, version, endpoint_address)
    try:
        code_bytes, code_format, requirements, name = fetch_code(endpoint_address, function_id, version)
    except RuntimeError as exc:
        logger.error("bootstrap failed: %s", exc)
        sys.exit(1)

    try:
        install_requirements(requirements)
    except RuntimeError as exc:
        logger.error("dependency install failed: %s", exc)
        sys.exit(1)

    fn = materialize_function(code_bytes, code_format, name)

    logger.info("function loaded, starting servers")
    server = RunnerServer(
        fn=fn,
        job_store=JobStore(),
        job_port=job_port,
        fastapi_port=fastapi_port,
        result_address=result_address or None,
        scratch_root=scratch_root,
        function_id=function_id,
        dataio_timeout_seconds=dataio_timeout,
    )
    server.start()


if __name__ == "__main__":
    main()
