from __future__ import annotations

import re
from typing import List, Optional

from pymongo.collection import Collection

from axo_vem.domain.data.bucket import DataBucket
from axo_vem.domain.data.data_item import DataItem
from axo_vem.domain.data.repository import BucketOwnerRepository, BucketRepository, DataItemRepository


class MongoBucketRepository(BucketRepository):
    """Read/write access to the `buckets` collection, keyed by bucket name --
    mirrors the shape of MongoJobRepository. Written by
    application/projector/bucket_handler.py, read directly via
    GET /buckets and GET /buckets/{name}
    (infrastructure/transport/api/controllers/buckets.py)."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, name: str) -> Optional[DataBucket]:
        doc = self._collection.find_one({"_id": name})
        if doc is None:
            return None
        return DataBucket(name=doc["name"], quota_bytes=doc["quota_bytes"], created_at=doc["created_at"])

    def list(self) -> List[DataBucket]:
        return [
            DataBucket(name=doc["name"], quota_bytes=doc["quota_bytes"], created_at=doc["created_at"])
            for doc in self._collection.find()
        ]

    def save(self, bucket: DataBucket) -> None:
        data = {"name": bucket.name, "quota_bytes": bucket.quota_bytes, "created_at": bucket.created_at}
        self._collection.update_one({"_id": bucket.name}, {"$set": data}, upsert=True)


class MongoBucketOwnerRepository(BucketOwnerRepository):
    """Read/write access to the `bucket_owners` collection, keyed by bucket
    name -- a plain, directly-written mapping, not fed by the projector
    (see BucketOwnerRepository's docstring for why this stays separate from
    `buckets`)."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get_owner(self, name: str) -> Optional[str]:
        doc = self._collection.find_one({"_id": name})
        return doc["owner_user_id"] if doc else None

    def set_owner(self, name: str, owner_user_id: str) -> None:
        self._collection.update_one(
            {"_id": name}, {"$set": {"owner_user_id": owner_user_id}}, upsert=True,
        )

    def list_owned(self, owner_user_id: str) -> List[str]:
        return [doc["_id"] for doc in self._collection.find({"owner_user_id": owner_user_id})]


class MongoDataItemRepository(DataItemRepository):
    """Read/write access to the `bucket_data` collection, keyed by
    "{name}:{version}". Written by application/projector/bucket_handler.py,
    read directly via GET /buckets/{name} to list a bucket's contained items."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, name: str, version: int) -> Optional[DataItem]:
        doc = self._collection.find_one({"_id": f"{name}:{version}"})
        if doc is None:
            return None
        return self._doc_to_item(doc)

    def list_by_bucket(self, bucket_name: str) -> List[DataItem]:
        pattern = f"^{re.escape(bucket_name)}/"
        return [self._doc_to_item(doc) for doc in self._collection.find({"name": {"$regex": pattern}})]

    def save(self, item: DataItem) -> None:
        data = {
            "name": item.name, "version": item.version, "format": item.format,
            "kind": item.kind, "total_size": item.total_size, "total_chunks": item.total_chunks,
            "status": item.status,
        }
        self._collection.update_one({"_id": f"{item.name}:{item.version}"}, {"$set": data}, upsert=True)

    def set_status(self, name: str, version: int, status: str) -> None:
        self._collection.update_one({"_id": f"{name}:{version}"}, {"$set": {"status": status}})

    def delete(self, name: str, version: int) -> None:
        self._collection.delete_one({"_id": f"{name}:{version}"})

    @staticmethod
    def _doc_to_item(doc: dict) -> DataItem:
        return DataItem(
            name=doc["name"], version=doc["version"], format=doc["format"],
            kind=doc["kind"], total_size=doc["total_size"], total_chunks=doc["total_chunks"],
            status=doc["status"],
        )
