from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database


def build_mongo_database(uri: str, db_name: str) -> Database:
    """Constructs a real MongoClient and selects the given database.
    Extracted from server.py's previously-inline MongoClient(...)[...]
    construction so the composition root doesn't hold pymongo-specific
    wiring directly."""
    return MongoClient(uri)[db_name]
