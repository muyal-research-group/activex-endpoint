from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from xolo.client.models import UserDTO

from axo_vem.infrastructure.database.kurrent.reader import KurrentReader


def build_router(reader: KurrentReader, current_user_dependency: Callable[..., UserDTO]) -> APIRouter:
    """The one route allowed to bypass Mongo and read Kurrent directly --
    exposing raw event history for a single entity's stream, for anything
    not yet projected into a read model."""
    router = APIRouter(tags=["job telemetry"])

    @router.get("/events/{category}/{entity_id}")
    def get_raw_events(category: str, entity_id: str, _current_user: UserDTO = Depends(current_user_dependency)):
        stream_name = f"{category}-{entity_id}"
        try:
            records = reader.get_stream(stream_name)
        except Exception:
            raise HTTPException(status_code=404, detail=f"stream not found: {stream_name}")
        if not records:
            raise HTTPException(status_code=404, detail=f"stream not found: {stream_name}")
        return [
            {
                "type": r.type,
                "data": json.loads(r.data.decode("utf-8")),
                "commit_position": r.commit_position,
            }
            for r in records
        ]

    return router
