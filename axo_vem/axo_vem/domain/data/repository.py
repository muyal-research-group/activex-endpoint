from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from axo_vem.domain.data.bucket import DataBucket
from axo_vem.domain.data.data_item import DataItem


class BucketRepository(ABC):
    """Write/read access for DataBucket aggregates. Implemented by
    infrastructure/database/mongo/bucket_repository.py's MongoBucketRepository;
    applied by the projector (application/projector/bucket_handler.py) after
    a DataBucketCreated event lands in Kurrent."""

    @abstractmethod
    def get(self, name: str) -> Optional[DataBucket]: ...

    @abstractmethod
    def list(self) -> List[DataBucket]: ...

    @abstractmethod
    def save(self, bucket: DataBucket) -> None: ...


class DataItemRepository(ABC):
    """Write/read access for DataItem aggregates, keyed by name+version.
    Implemented by MongoDataItemRepository; applied by the projector after a
    DataRegistered or DataUploadCompleted event lands in Kurrent."""

    @abstractmethod
    def get(self, name: str, version: int) -> Optional[DataItem]: ...

    @abstractmethod
    def list_by_bucket(self, bucket_name: str) -> List[DataItem]: ...

    @abstractmethod
    def save(self, item: DataItem) -> None: ...

    @abstractmethod
    def set_status(self, name: str, version: int, status: str) -> None:
        """Flips just the status field of an already-saved item -- used by
        the DataUploadCompleted branch, which only carries name/version, not
        the full item shape DataRegistered's save() call does."""
        ...

    @abstractmethod
    def delete(self, name: str, version: int) -> None:
        """Removes the item doc entirely -- used by the DataDeleted branch."""
        ...
