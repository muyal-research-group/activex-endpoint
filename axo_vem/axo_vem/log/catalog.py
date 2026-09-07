from __future__ import annotations


class Component:
    SERVER             = "server"
    INGESTION          = "ingestion"
    PROJECTOR          = "projector"
    AUTH               = "auth"
    STATS_POLLER       = "stats_poller"
    ACTIVITY_RETENTION = "activity_retention"
    ENDPOINT_LIVENESS  = "endpoint_liveness"
    MONGO              = "mongo"
    KURRENT            = "kurrent"
    HTTP               = "http"


class Event:
    class Server:
        STARTED = "SERVER.STARTED"
        STOPPED = "SERVER.STOPPED"

    class Ingestion:
        STARTED            = "INGESTION.STARTED"
        FRAME_MALFORMED    = "INGESTION.FRAME_MALFORMED"
        ENVELOPE_MALFORMED = "INGESTION.ENVELOPE_MALFORMED"
        EVENT_APPENDED     = "INGESTION.EVENT_APPENDED"
        APPEND_RETRYING    = "INGESTION.APPEND_RETRYING"
        APPEND_GIVING_UP   = "INGESTION.APPEND_GIVING_UP"

    class Projector:
        SUBSCRIBED      = "PROJECTOR.SUBSCRIBED"
        RECONNECTING    = "PROJECTOR.RECONNECTING"
        STALE_RECONNECT = "PROJECTOR.STALE_RECONNECT"
        GIVING_UP       = "PROJECTOR.GIVING_UP"
        EVENT_APPLIED   = "PROJECTOR.EVENT_APPLIED"
        APPLY_FAILED    = "PROJECTOR.APPLY_FAILED"

    class Auth:
        UNAUTHORIZED = "AUTH.UNAUTHORIZED"

    class StatsPoller:
        TICK_FAILED = "STATS_POLLER.TICK_FAILED"

    class ActivityRetention:
        TICK_FAILED = "ACTIVITY_RETENTION.TICK_FAILED"
        PURGED      = "ACTIVITY_RETENTION.PURGED"

    class EndpointLiveness:
        TICK_FAILED    = "ENDPOINT_LIVENESS.TICK_FAILED"
        NO_ROUTER_BIND = "ENDPOINT_LIVENESS.NO_ROUTER_BIND"
        STATUS_CHANGED = "ENDPOINT_LIVENESS.STATUS_CHANGED"

    class Mongo:
        CONNECTED      = "MONGO.CONNECTED"
        CONNECT_FAILED = "MONGO.CONNECT_FAILED"

    class Kurrent:
        CONNECTED      = "KURRENT.CONNECTED"
        CONNECT_FAILED = "KURRENT.CONNECT_FAILED"

    class Http:
        REQUEST_HANDLED = "HTTP.REQUEST_HANDLED"
        REQUEST_FAILED  = "HTTP.REQUEST_FAILED"
