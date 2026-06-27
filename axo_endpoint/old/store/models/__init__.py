from dataclasses import dataclass
from typing import Optional
@dataclass(frozen=True)
class MetadataKey:
    id: str
    version: Optional[str] = None
    alias: Optional[str] = None
    def __str__(self):
        return f"{self.id}:{self.version}:{self.alias}"
