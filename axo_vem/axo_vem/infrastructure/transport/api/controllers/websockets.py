from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster

# NOTE: unauthenticated, unlike every REST route in this API (all gated via
# current_user_dependency) -- a plain browser WebSocket handshake can't
# attach the Authorization/Temporal-Secret-Key headers the rest of this API
# relies on. Acceptable for now since these topics only ever carry the same
# read-model fields GET /buckets and GET /endpoints already expose to any
# authenticated caller, but revisit (e.g. a short-lived token as a query
# param, validated here) before this API is deployed somewhere that
# boundary actually matters.


def build_router(broadcaster: Broadcaster) -> APIRouter:
    """WebSocket routes, one per push topic, all sharing the same
    Broadcaster instance server.py wires into the projector so these
    connections receive the exact events bucket_handler.py (and, later,
    the endpoint stats poller) broadcast -- see the plan this was built
    from for why one shared broadcaster instead of one per route."""
    router = APIRouter()

    @router.websocket("/ws/buckets")
    async def ws_buckets(websocket: WebSocket) -> None:
        """Fleet-wide bucket status feed -- every DataRegistered
        ("pending")/DataUploadCompleted ("ready") message, for every
        bucket. The client (axo-ui's bucket detail page) filters
        client-side for the bucket it's currently showing."""
        await websocket.accept()
        broadcaster.register("buckets", websocket)
        try:
            while True:
                # Nothing is ever expected from the client on this
                # connection -- receive() just blocks until disconnect so
                # this coroutine (and its registration) stays alive exactly
                # as long as the socket does.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unregister("buckets", websocket)

    @router.websocket("/ws/endpoints")
    async def ws_endpoints(websocket: WebSocket) -> None:
        """Fleet-wide endpoint stats feed -- one message per endpoint per
        EndpointStatsPoller tick, for every endpoint (e.g. the dashboard).
        See ws_endpoint_scoped for the single-endpoint equivalent."""
        await websocket.accept()
        broadcaster.register("endpoints", websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unregister("endpoints", websocket)

    @router.websocket("/ws/functions")
    async def ws_functions(websocket: WebSocket) -> None:
        """Fleet-wide function lifecycle feed -- one message per
        FunctionRegistered/Deployed/Activated/Deactivated/Updated/Stopped/
        Crashed/Deleted event, for every function. Lets axo-ui's functions
        list page pick up a freshly registered function (or any later
        status change) without a manual reload, mirroring ws_endpoints."""
        await websocket.accept()
        broadcaster.register("functions", websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unregister("functions", websocket)

    @router.websocket("/ws/endpoints/{endpoint_id}")
    async def ws_endpoint_scoped(websocket: WebSocket, endpoint_id: str) -> None:
        """Same feed as ws_endpoints, pre-filtered server-side to one
        endpoint -- for a caller watching just that endpoint's detail page,
        so it doesn't have to filter the fleet-wide stream client-side."""
        topic = f"endpoints:{endpoint_id}"
        await websocket.accept()
        broadcaster.register(topic, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unregister(topic, websocket)

    return router
