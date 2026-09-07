from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pymongo.collection import Collection
from xolo.client.models import UserDTO

from axo_shared import wire
from axo_shared.client import DEFAULT_CHUNK_BYTES
from axo_shared.protocol import Command

from axo_vem.domain.data.repository import BucketOwnerRepository, BucketRepository, DataItemRepository
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


class _BucketCreateRequest(BaseModel):
    name: str
    quota_bytes: int


def _endpoint_rpc_uri(endpoints: Collection, endpoint_id: str) -> str:
    doc = endpoints.find_one({"_id": endpoint_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    router_bind = doc.get("router_bind")
    if not router_bind:
        raise HTTPException(status_code=409, detail="endpoint has no known router_bind")
    return resolve_rpc_uri(router_bind, endpoint_id)


def _leader_rpc_uri(endpoints: Collection, consensus: Collection, fallback: str) -> str:
    """DATA_CHUNK_PUT is never leader-proxied (unlike DATA_REGISTER), so it
    must land on the actual current leader. The DATA_REGISTER response's own
    leader_rpc_uri is unusable here -- it's the leader's own bind string
    (e.g. tcp://0.0.0.0:5555), not a connectable address, and every node
    shares that same string. Resolve the real leader via the consensus
    collection instead (see controllers/consensus.py's identical
    "highest term = current leader" query), falling back to the
    originally-targeted endpoint if no consensus view has been reported yet
    (single-node dev)."""
    doc = consensus.find_one(sort=[("_id", -1)])
    if doc is None or not doc.get("leader_ids"):
        return fallback
    leader_id = doc["leader_ids"][0]
    leader_doc = endpoints.find_one({"_id": leader_id})
    if leader_doc is None or not leader_doc.get("router_bind"):
        return fallback
    return resolve_rpc_uri(leader_doc["router_bind"], leader_id)


def build_router(
    bucket_repository: BucketRepository,
    data_item_repository: DataItemRepository,
    bucket_owner_repository: BucketOwnerRepository,
    endpoints: Collection,
    consensus: Collection,
    current_user_dependency: Callable[..., UserDTO],
    command_timeout_seconds: float = 3.0,
) -> APIRouter:
    router = APIRouter(tags=["data buckets"])

    def _used_bytes(bucket_name: str) -> int:
        return sum(item.total_size for item in data_item_repository.list_by_bucket(bucket_name))

    @router.get("/buckets")
    def list_buckets(
        mine_only: bool = False,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Unfiltered by default -- buckets created before ownership existed
        have no owner row and would otherwise vanish from every listing.
        mine_only=true scopes to buckets this user actually created."""
        buckets = bucket_repository.list()
        if mine_only:
            owned = set(bucket_owner_repository.list_owned(current_user.key))
            buckets = [b for b in buckets if b.name in owned]
        return [
            {
                **bucket.to_dict(),
                "used_bytes": _used_bytes(bucket.name),
                "owner_user_id": bucket_owner_repository.get_owner(bucket.name),
            }
            for bucket in buckets
        ]

    @router.get("/buckets/{name}")
    def get_bucket(name: str, _current_user: UserDTO = Depends(current_user_dependency)):
        bucket = bucket_repository.get(name)
        if bucket is None:
            raise HTTPException(status_code=404, detail="bucket not found")
        items = data_item_repository.list_by_bucket(name)
        return {
            **bucket.to_dict(),
            "used_bytes": sum(item.total_size for item in items),
            "owner_user_id": bucket_owner_repository.get_owner(name),
            "items": [item.to_dict() for item in items],
        }

    @router.post("/endpoints/{endpoint_id}/buckets", tags=["endpoint management"])
    def create_bucket(
        endpoint_id: str,
        body: _BucketCreateRequest,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Proxies BUCKET_REGISTER straight to the target endpoint's ROUTER
        (leader-proxied by the node itself if needed), mirroring
        register_function/assign_virtual_environment's relay shape. Ownership
        is recorded here, directly, synchronously -- not via the node round
        trip (see BucketOwnerRepository)."""
        rpc_uri = _endpoint_rpc_uri(endpoints, endpoint_id)
        command = Command(
            operation=wire.BUCKET_REGISTER,
            content_type="application/json",
            envelope={"name": body.name, "quota_bytes": body.quota_bytes},
        )
        result = send_command(rpc_uri, command, command_timeout_seconds)
        if result.is_err:
            raise HTTPException(status_code=504, detail=str(result.unwrap_err()))
        command_result = result.unwrap()
        if not command_result.ok:
            raise HTTPException(status_code=409, detail=command_result.error)
        bucket_owner_repository.set_owner(body.name, current_user.key)
        return {"endpoint_id": endpoint_id, **(command_result.metadata or {})}

    @router.post("/endpoints/{endpoint_id}/buckets/{bucket}/data", tags=["endpoint management"])
    async def upload_data(
        endpoint_id: str,
        bucket: str,
        key: str = Form(...),
        version: int = Form(...),
        format: str = Form("raw"),
        kind: str = Form("fs"),
        file: UploadFile = File(...),
        _current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Accepts a browser file upload and proxies it into the cluster:
        one DATA_REGISTER relay (leader-proxied by the node), then a loop of
        DATA_CHUNK_PUT relays targeting the resolved leader directly. The
        whole file is read into memory here -- acceptable for the expected
        data sizes; revisit if that becomes a bottleneck."""
        register_rpc_uri = _endpoint_rpc_uri(endpoints, endpoint_id)
        name = f"{bucket}/{key}"
        source = await file.read()
        total_size = len(source)

        register_command = Command(
            operation=wire.DATA_REGISTER,
            content_type="application/json",
            envelope={
                "name": name, "version": version, "format": format, "kind": kind,
                "total_size": total_size, "chunk_bytes": DEFAULT_CHUNK_BYTES,
            },
        )
        result = send_command(register_rpc_uri, register_command, command_timeout_seconds)
        if result.is_err:
            raise HTTPException(status_code=504, detail=str(result.unwrap_err()))
        command_result = result.unwrap()
        if not command_result.ok:
            raise HTTPException(status_code=409, detail=command_result.error)

        total_chunks = command_result.metadata.get("total_chunks", 0)
        chunk_rpc_uri = _leader_rpc_uri(endpoints, consensus, fallback=register_rpc_uri)
        for i in range(total_chunks):
            start = i * DEFAULT_CHUNK_BYTES
            chunk_command = Command(
                operation=wire.DATA_CHUNK_PUT,
                content_type="application/octet-stream",
                envelope={"name": name, "version": version, "chunk_index": i},
                payload=source[start:start + DEFAULT_CHUNK_BYTES],
            )
            chunk_result = send_command(chunk_rpc_uri, chunk_command, command_timeout_seconds)
            if chunk_result.is_err:
                raise HTTPException(status_code=504, detail=str(chunk_result.unwrap_err()))
            chunk_command_result = chunk_result.unwrap()
            if not chunk_command_result.ok:
                raise HTTPException(status_code=409, detail=chunk_command_result.error)

        return {
            "endpoint_id": endpoint_id, "bucket": bucket, "name": name, "version": version,
            "total_size": total_size, "total_chunks": total_chunks,
        }

    @router.get(
        "/endpoints/{endpoint_id}/buckets/{bucket}/data/{key}/{version}/download", tags=["endpoint management"],
    )
    def download_data(
        endpoint_id: str,
        bucket: str,
        key: str,
        version: int,
        _current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Streams a previously-uploaded dataset's raw bytes back to the
        browser -- the read counterpart of upload_data. Reads from the
        resolved leader (same _leader_rpc_uri target upload_data's chunk
        puts use), since that's the one node BlobReplicator's completeness
        gate guarantees is fully present once the item's status is "ready";
        picking a specific complete replica via DATA_INFO's peer state is a
        possible future optimization, not needed today. Raw bytes only, no
        format-aware decoding -- mirrors the dataio design's "the endpoint
        only ever moves raw bytes" principle end to end.

        Validation (item exists, upload complete, endpoint/leader
        resolvable) all happens before StreamingResponse is constructed, so
        those failures still get a clean 404/409/504 -- once streaming
        actually starts, headers are already committed and a failed chunk
        fetch can only abort the connection, not swap in a different status
        code."""
        name = f"{bucket}/{key}"
        item = data_item_repository.get(name, version)
        if item is None:
            raise HTTPException(status_code=404, detail="data not found")
        if item.status != "ready":
            raise HTTPException(status_code=409, detail="data upload is not yet complete")

        register_rpc_uri = _endpoint_rpc_uri(endpoints, endpoint_id)
        chunk_rpc_uri = _leader_rpc_uri(endpoints, consensus, fallback=register_rpc_uri)

        def _iter_chunks():
            for i in range(item.total_chunks):
                chunk_command = Command(
                    operation=wire.DATA_CHUNK_GET,
                    content_type="application/json",
                    envelope={"name": name, "version": version, "chunk_index": i},
                )
                chunk_result = send_command(chunk_rpc_uri, chunk_command, command_timeout_seconds)
                if chunk_result.is_err:
                    raise RuntimeError(f"failed to fetch chunk {i} of {name}:{version}: {chunk_result.unwrap_err()}")
                command_result = chunk_result.unwrap()
                if not command_result.ok:
                    raise RuntimeError(f"failed to fetch chunk {i} of {name}:{version}: {command_result.error}")
                yield command_result.payload

        filename = key.rsplit("/", 1)[-1]
        return StreamingResponse(
            _iter_chunks(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.delete("/endpoints/{endpoint_id}/buckets/{bucket}/data/{key}/{version}", tags=["endpoint management"])
    def delete_data(
        endpoint_id: str,
        bucket: str,
        key: str,
        version: int,
        _current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Proxies DATA_DELETE straight to the target endpoint's ROUTER --
        leader-proxied by the node itself (like DATA_REGISTER/BUCKET_REGISTER
        above), unlike DATA_CHUNK_PUT which needs the special leader
        resolution in _leader_rpc_uri. The deletion itself then replicates
        to every other cluster member via the node's own consensus path."""
        rpc_uri = _endpoint_rpc_uri(endpoints, endpoint_id)
        command = Command(
            operation=wire.DATA_DELETE,
            content_type="application/json",
            envelope={"name": f"{bucket}/{key}", "version": version},
        )
        result = send_command(rpc_uri, command, command_timeout_seconds)
        if result.is_err:
            raise HTTPException(status_code=504, detail=str(result.unwrap_err()))
        command_result = result.unwrap()
        if not command_result.ok:
            raise HTTPException(status_code=409, detail=command_result.error)
        return {"endpoint_id": endpoint_id, "bucket": bucket, "name": f"{bucket}/{key}", "version": version}

    return router
