from __future__ import annotations

from typing import Tuple

import kurrentdbclient.exceptions as kurrent_exceptions
import pymongo.errors as mongo_errors

_KURRENT_CONNECTIVITY_CODES = {
    kurrent_exceptions.ServiceUnavailableError: "KURRENT.UNAVAILABLE",
    kurrent_exceptions.DiscoveryFailedError: "KURRENT.DISCOVERY_FAILED",
    kurrent_exceptions.DeadlineExceededError: "KURRENT.TIMEOUT",
    kurrent_exceptions.GrpcDeadlineExceededError: "KURRENT.TIMEOUT",
    kurrent_exceptions.LeaderNotFoundError: "KURRENT.LEADER_NOT_FOUND",
    kurrent_exceptions.NodeIsNotLeaderError: "KURRENT.LEADER_NOT_FOUND",
}

_KURRENT_DESCRIPTIONS = {
    "KURRENT.UNAVAILABLE": "KurrentDB is unreachable -- check the container is up and "
                            "AXO_VEM_KURRENT_URI is correct.",
    "KURRENT.DISCOVERY_FAILED": "Could not discover a KurrentDB cluster node.",
    "KURRENT.TIMEOUT": "KurrentDB did not respond in time.",
    "KURRENT.LEADER_NOT_FOUND": "KurrentDB cluster has no leader right now.",
}

_MONGO_CONNECTIVITY_CODES = {
    mongo_errors.ServerSelectionTimeoutError: "MONGO.UNAVAILABLE",
    mongo_errors.AutoReconnect: "MONGO.UNAVAILABLE",
    mongo_errors.ConnectionFailure: "MONGO.UNAVAILABLE",
    mongo_errors.NetworkTimeout: "MONGO.TIMEOUT",
}

_MONGO_DESCRIPTIONS = {
    "MONGO.UNAVAILABLE": "MongoDB is unreachable -- check the container is up and "
                          "AXO_VEM_MONGO_URI is correct.",
    "MONGO.TIMEOUT": "MongoDB did not respond in time.",
}


def classify_kurrent_error(exc: Exception) -> Tuple[str, str]:
    for exc_type, code in _KURRENT_CONNECTIVITY_CODES.items():
        if isinstance(exc, exc_type):
            return code, _KURRENT_DESCRIPTIONS[code]
    return "KURRENT.UNKNOWN", str(exc)


def classify_mongo_error(exc: Exception) -> Tuple[str, str]:
    for exc_type, code in _MONGO_CONNECTIVITY_CODES.items():
        if isinstance(exc, exc_type):
            return code, _MONGO_DESCRIPTIONS[code]
    return "MONGO.UNKNOWN", str(exc)
