from typing import Dict,Any
from axo_endpoint.config import Config
import zmq
from axo.log import get_logger
import time as T
import asyncio
import json as J
from axo_endpoint.endpoints import EndpointManager
from axo_endpoint.metrics import MetricCollector


logger = get_logger(name=__name__,ltype="JSON")
HB_TOPIC = b"AXO.HEARTBEAT"
NEIGHBORS: Dict[str, Dict[str, Any]] = {}

def _rpc_uri_from(config: Config) -> str:
    """Build the contact URI for this endpoint's request/response socket."""
    return f"{config.AXO_PROTOCOL}://{config.AXO_HOSTNAME}:{config.AXO_REQ_RES_PORT}"

def _gossip_bind_uri(config: Config) -> str:
    return f"{config.AXO_PROTOCOL}://{config.AXO_GOSSIP_BIND_HOST}:{config.AXO_GOSSIP_PORT}"

async def heartbeat_publisher_task(ctx: zmq.asyncio.Context, config: Config,metrics_collector:MetricCollector):
    """
    Bind PUB locally; other peers will SUB to this address or to a relay.
    """
    pub = ctx.socket(zmq.PUB)
    pub.bind(_gossip_bind_uri(config))
    logger.debug({"event": "GOSSIP.PUB.BOUND", "uri": _gossip_bind_uri(config)})
    try:
        while True:
            try:
                metrics_str = await metrics_collector.to_json()
                rpc_uri     = _rpc_uri_from(config)
                await pub.send_multipart([
                    HB_TOPIC,
                    config.AXO_ENDPOINT_ID.encode(),
                    b"axo-endpoint",
                    rpc_uri.encode(),
                    metrics_str.encode(),
                ])
                logger.debug({
                    "event":"HEARTBEAT.SENT",
                    "endpoint_id":config.AXO_ENDPOINT_ID,
                    "rpc_uri":rpc_uri
                })
                _ = await metrics_collector.add(f"{config.AXO_ENDPOINT_ID}.HEARTBEATS",1)
                await asyncio.sleep(config.AXO_HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.warning({"event": "HEARTBEAT.SEND.FAIL", "err": str(e)})
                await asyncio.sleep(min(1.0, config.AXO_HEARTBEAT_INTERVAL))
    finally:
        try: 
            pub.close(0)
        except Exception as e:
            logger.warning({"event":"PUB.CLOSE.FAILED","error":str(e)})

async def heartbeat_subscriber_task(ctx: zmq.asyncio.Context,endpoint_manager:EndpointManager, config: Config):
    """
    Subscribe to *multiple* seeds. Each seed is a PUB address (“tcp://host:port”).
    You can list several in AXO_GOSSIP_SEEDS.
    """
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.SUBSCRIBE, HB_TOPIC)
    connected = 0
    for seed in (config.AXO_GOSSIP_SEEDS or []):
        try:
            sub.connect(seed)
            connected += 1
            logger.debug({
                "event":"GOSSIP.CONNECT.SUCCESSFULLY",
                "seed":seed,
                "connected":connected
            })
            # print("CONNECTED", seed)
        except Exception as e:
            logger.warning({"event": "GOSSIP.SUB.CONNECT.FAIL", "seed": seed, "err": str(e)})

    if connected == 0:
        # Optionally also SUB to *your own* local PUB if no seeds provided (handy in single-host dev)
        try:
            sub.connect(_gossip_bind_uri(config))
            connected = 1
        except Exception as e:
            logger.error({"event": "GOSSIP.SUB.CONNECT.NONE", "err": str(e)})

    logger.debug({"event": "GOSSIP.SUB.CONNECTED", "count": connected})

    try:
        while True:
            frames = await sub.recv_multipart()

            # frames: [HB, peer_id, service, rpc_uri, json_metrics]
            _, peer_id_b, svc_b, rpc_uri_b, metrics_b = frames
            peer_id = peer_id_b.decode()
            if peer_id == config.AXO_ENDPOINT_ID:
                # ignore self
                continue


            svc     = svc_b.decode()
            rpc_uri = rpc_uri_b.decode()
            metrics = J.loads(metrics_b.decode())
            now     = T.time()
            logger.debug({
                "event":"HEARBEAT.RECEIVED",
                "endpoint_id":peer_id,
                "current_endpoint_id":config.AXO_ENDPOINT_ID,
                "metrics":metrics
                
            })

            # Upsert neighbor
            NEIGHBORS[peer_id] = {
                "svc": svc,
                "rpc_uri": rpc_uri,
                "metrics": metrics,
                "last": now,
            }

            # Reflect into your DistributedEndpointManager for convenience
            if peer_id not in endpoint_manager.endpoints:
                # Parse host/port for add_endpoint
                try:
                    proto, rest = rpc_uri.split("://", 1)
                    host, port = rest.split(":")
                    endpoint_manager.add_endpoint(
                        endpoint_id=peer_id,
                        hostname=host,
                        protocol=proto,
                        pubsub_port=config.AXO_GOSSIP_PORT,     # best effort; or carry a second URI in HB
                        req_res_port=int(port),
                    )
                    logger.info({"event":"NEIGHBOR.ADDED", "peer_id": peer_id, "rpc_uri": rpc_uri})
                except Exception as e:
                    logger.warning({"event":"NEIGHBOR.ADD.FAIL", "peer_id": peer_id, "rpc_uri": rpc_uri, "err": str(e)})
            else:
                # You can update metadata or metrics in your manager if you like
                pass

    finally:
        sub.close(0)

async def neighbors_gc_task(config: Config,endpoint_manager:EndpointManager):
    """Evict stale neighbors (no HB within TTL)."""
    ttl = float(config.AXO_HEARTBEAT_TTL)
    while True:
        try:
            now = T.time()
            stale_ids = [pid for pid, d in NEIGHBORS.items() if now - d.get("last", 0) > ttl]
            for pid in stale_ids:
                NEIGHBORS.pop(pid, None)
                # Optional: also remove from endpoint_manager
                if pid in endpoint_manager.endpoints and pid != config.AXO_ENDPOINT_ID:
                    try:
                        endpoint_manager.delete_endpoint(pid)   # if you have such a method
                    except Exception:
                        pass
                logger.info({"event":"NEIGHBOR.REMOVED", "peer_id": pid, "reason": "stale"})
        except Exception as e:
            logger.warning({"event": "NEIGHBORS.GC.FAIL", "err": str(e)})
        await asyncio.sleep(max(1.0, ttl / 2.0))