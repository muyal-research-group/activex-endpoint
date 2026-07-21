from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Union

import cloudpickle
import zmq

from axo_shared.functions.identity import compute_function_id
from axo_shared.protocol import Command, CommandResult
from axo_shared.wire import (
    ACTIVITY_LIST,
    BUCKET_REGISTER,
    DATA_CHUNK_PUT,
    DATA_INFO,
    DATA_REGISTER,
    DATA_STATUS,
    FUNCTION_DELETE,
    FUNCTION_REGISTER,
    FUNCTION_UPDATE,
    JOB_RESULT,
    JOB_SUBMIT,
    PING,
    decode_command_result,
    encode_command,
)

# Must stay in sync with axo_endpoint/dataio.py's own DEFAULT_CHUNK_BYTES --
# duplicated rather than imported so axo_shared doesn't pull in
# axo_endpoint.core.dataio/core.storage for one constant.
DEFAULT_CHUNK_BYTES = 262144


class AxoClientError(Exception):
    pass


class AxoClientTimeout(AxoClientError):
    pass


def _read_chunk(data: "Union[bytes, str]", chunk_index: int, chunk_bytes: int, total_size: int) -> bytes:
    """Reads one chunk's worth of bytes at the right offset -- straight out
    of ``data`` if it's already bytes, or from disk (never loading the whole
    file into memory) if it's a path."""
    start = chunk_index * chunk_bytes
    end = min(start + chunk_bytes, total_size)
    if isinstance(data, (bytes, bytearray)):
        return bytes(data[start:end])
    with open(data, "rb") as f:
        f.seek(start)
        return f.read(end - start)


class AxoEndpointClient:
    """ZMQ DEALER client for a single axo_endpoint node."""

    def __init__(self, address: str, timeout_ms: int = 5000) -> None:
        self._address = address
        self._timeout_ms = timeout_ms
        self._ctx = zmq.Context()
        self._sock = self._ctx.socket(zmq.DEALER)
        self._sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self._sock.connect(address)

    def close(self) -> None:
        self._sock.close()
        self._ctx.term()

    def __enter__(self) -> "AxoEndpointClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _send(self, command: Command) -> CommandResult:
        self._sock.send_multipart(encode_command(command))
        try:
            frames = self._sock.recv_multipart()
        except zmq.Again:
            raise AxoClientTimeout("no reply received within timeout")
        result = decode_command_result(frames)
        if result.is_err:
            raise AxoClientError(str(result.unwrap_err()))
        return result.unwrap()

    def ping(self) -> CommandResult:
        return self._send(Command(
            operation=PING,
            content_type="application/json",
            envelope={},
            payload=b"",
        ))

    def register_function(
        self,
        user_id: str,
        virtual_environment_id: str,
        name: str,
        fn: Any = None,
        code: Optional[bytes] = None,
        runtime_spec: Optional[Dict[str, Any]] = None,
        params_schema: Optional[List[Dict[str, Any]]] = None,
    ) -> CommandResult:
        """version is no longer caller-supplied -- the node assigns
        next_version = max(existing versions for this function_id) + 1
        internally, returned in the result's metadata["version"].
        function_id is derived from (user_id, virtual_environment_id, name)
        via compute_function_id, the same pure derivation
        axo_vem's register_function endpoint uses -- re-registering
        under the same triple continues that function's version lineage."""
        if fn is not None:
            code = cloudpickle.dumps(fn)
        if code is None:
            raise ValueError("fn or code must be provided")
        function_id = compute_function_id(user_id, virtual_environment_id, name)
        envelope: Dict[str, Any] = {"function_id": function_id, "name": name}
        if runtime_spec:
            envelope["runtime_spec"] = runtime_spec
        if params_schema:
            envelope["params_schema"] = params_schema
        return self._send(Command(
            operation=FUNCTION_REGISTER,
            content_type="application/octet-stream",
            envelope=envelope,
            payload=code,
        ))

    def update_function(
        self,
        user_id: str,
        virtual_environment_id: str,
        name: str,
        version: int,
        params_schema: Optional[List[Dict[str, Any]]] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """In-place metadata mutation -- new params_schema entries are merged
        additively, env_vars are merged into the existing dict. Takes effect
        lazily: a currently-running worker/container keeps its old config
        until it next naturally redeploys."""
        function_id = compute_function_id(user_id, virtual_environment_id, name)
        envelope: Dict[str, Any] = {"function_id": function_id, "version": version}
        if params_schema:
            envelope["params_schema"] = params_schema
        if env_vars:
            envelope["env_vars"] = env_vars
        return self._send(Command(
            operation=FUNCTION_UPDATE,
            content_type="application/json",
            envelope=envelope,
            payload=b"",
        ))

    def delete_function(self, user_id: str, virtual_environment_id: str, name: str, version: int) -> CommandResult:
        function_id = compute_function_id(user_id, virtual_environment_id, name)
        return self._send(Command(
            operation=FUNCTION_DELETE,
            content_type="application/json",
            envelope={"function_id": function_id, "version": version},
            payload=b"",
        ))

    def create_bucket(self, name: str, quota_bytes: int) -> CommandResult:
        """Declares a named, quota-enforced namespace to register data into --
        DATA_REGISTER with a "{bucket}/{key}" name rejects once the bucket
        would exceed quota_bytes. Leader-gated, like register_data."""
        return self._send(Command(
            operation=BUCKET_REGISTER,
            content_type="application/json",
            envelope={"name": name, "quota_bytes": quota_bytes},
        ))

    def register_data(
        self,
        name: str,
        version: int,
        total_size: int,
        chunk_bytes: int,
        format: str = "raw",
        kind: str = "fs",
        content_hash: Optional[str] = None,
        content_hash_algo: str = "sha256",
    ) -> CommandResult:
        """Declares a piece of data's metadata ahead of the actual bytes.
        The response's ``leader_rpc_uri`` is exactly where to send the
        following DATA_CHUNK_PUT/DATA_STATUS calls -- those two ops are
        never leader-proxied, unlike this one."""
        envelope: Dict[str, Any] = {
            "name": name, "version": version, "format": format, "kind": kind,
            "total_size": total_size, "chunk_bytes": chunk_bytes,
        }
        if content_hash is not None:
            envelope["content_hash"] = content_hash
            envelope["content_hash_algo"] = content_hash_algo
        return self._send(Command(operation=DATA_REGISTER, content_type="application/json", envelope=envelope))

    def put_data_chunk(self, name: str, version: int, chunk_index: int, chunk: bytes) -> CommandResult:
        return self._send(Command(
            operation=DATA_CHUNK_PUT,
            content_type="application/octet-stream",
            envelope={"name": name, "version": version, "chunk_index": chunk_index},
            payload=chunk,
        ))

    def data_status(self, name: str, version: int) -> CommandResult:
        return self._send(Command(
            operation=DATA_STATUS, content_type="application/json", envelope={"name": name, "version": version},
        ))

    def data_info(self, name: str, version: int) -> CommandResult:
        return self._send(Command(
            operation=DATA_INFO, content_type="application/json", envelope={"name": name, "version": version},
        ))

    def upload_data(
        self,
        name: str,
        version: int,
        data: Union[bytes, str],
        format: str = "raw",
        kind: str = "fs",
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
        resume: bool = True,
    ) -> CommandResult:
        """Registers then chunk-uploads data, reading a file path
        chunk-by-chunk if ``data`` is a path (never loading the whole file
        into memory) or slicing straight out of ``data`` if it's already
        bytes. Resumable: with resume=True, asks the leader what it already
        has via DATA_STATUS and only sends what's missing."""
        total_size = len(data) if isinstance(data, (bytes, bytearray)) else os.path.getsize(data)

        register_result = self.register_data(
            name, version, total_size=total_size, chunk_bytes=chunk_bytes, format=format, kind=kind,
        )
        if not register_result.ok:
            return register_result

        leader_rpc_uri = register_result.metadata.get("leader_rpc_uri")
        total_chunks = register_result.metadata["total_chunks"]
        leader = self if leader_rpc_uri in (None, self._address) else AxoEndpointClient(
            leader_rpc_uri, timeout_ms=self._timeout_ms,
        )
        try:
            present: List[int] = []
            if resume:
                status_result = leader.data_status(name, version)
                if status_result.ok:
                    present = status_result.metadata.get("present_chunk_indices", [])

            missing = [i for i in range(total_chunks) if i not in present]
            last_result = register_result
            for chunk_index in missing:
                chunk = _read_chunk(data, chunk_index, chunk_bytes, total_size)
                last_result = leader.put_data_chunk(name, version, chunk_index, chunk)
                if not last_result.ok:
                    return last_result

            if not missing:
                last_result = leader.data_status(name, version)
            return last_result
        finally:
            if leader is not self:
                leader.close()

    def submit_job(
        self,
        user_id: str,
        virtual_environment_id: str,
        function_name: str,
        version: int,
        params: Optional[Dict[str, Any]] = None,
    ) -> CommandResult:
        function_id = compute_function_id(user_id, virtual_environment_id, function_name)
        return self._send(Command(
            operation=JOB_SUBMIT,
            content_type="application/json",
            envelope={
                "function_id": function_id,
                "function_name": function_name,
                "function_version": version,
                "params": params or {},
            },
            payload=b"",
        ))

    def get_job_result(self, job_id: str) -> CommandResult:
        return self._send(Command(
            operation=JOB_RESULT,
            content_type="application/json",
            envelope={"job_id": job_id},
            payload=b"",
        ))

    def list_activity(self, function_id: Optional[str] = None, limit: int = 100) -> CommandResult:
        """Reads back recorded job/container activity from whichever node
        this client is connected to -- purely that node's own local view."""
        envelope: Dict[str, Any] = {"limit": limit}
        if function_id is not None:
            envelope["function_id"] = function_id
        return self._send(Command(operation=ACTIVITY_LIST, content_type="application/json", envelope=envelope))

    def run(
        self,
        user_id: str,
        virtual_environment_id: str,
        function_name: str,
        version: int,
        params: Optional[Dict[str, Any]] = None,
        poll_interval: float = 0.5,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Submit a job and block until it completes or times out."""
        submit = self.submit_job(user_id, virtual_environment_id, function_name, version, params)
        if not submit.ok:
            return submit
        job_id = submit.metadata["job_id"]
        deadline = time.monotonic() + timeout
        while True:
            poll = self.get_job_result(job_id)
            if poll.ok and poll.metadata.get("status") != "PENDING":
                return poll
            if time.monotonic() > deadline:
                raise AxoClientTimeout(
                    f"job {job_id} did not complete within {timeout}s"
                )
            time.sleep(poll_interval)
