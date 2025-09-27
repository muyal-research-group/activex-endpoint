from typing import Dict,Callable, Any,List,Optional
from nanoid import generate as nanoid 
import humanfriendly as HF
import time as T
import asyncio
from axo.helpers import _generate_id
from axo.models import AxoContext



AnyFunctionType = Callable[..., any]

class Heater:
    def __init__(self,max_idle_time:str = "1h"):
        self.start_time = T.time()
        self.last_invocation = T.time()
        self.max_idle_time = HF.parse_timespan(max_idle_time)
        self.envent = asyncio.Event()
        self.q = []
    def warm(self,task_id:str=""):
        self.q.append(task_id)
        self.last_invocation = T.time()
    def is_cold(self)->bool:
        
        return self.get_current_active_time()  >= self.max_idle_time
    def get_current_active_time(self):
        return T.time()-self.last_invocation

class Task:
    def __init__(
        self,
        namespace: str,
        operation: str,
        metadata: Dict[str, Any],
        fargs: Optional[List[Any]] = None,
        fkwargs: Optional[Dict[str, Any]] = None,
        ctx:Optional[AxoContext] = None,
        ao_state: bytes = b"",
        ao_source: str = "",
    ):
        self.task_id = nanoid()
        self.namespace = namespace
        self.operation = operation
        self.metadata = metadata or {}
        self.fargs = fargs or []
        self.fkwargs = fkwargs or {}
        self.ctx =  ctx or AxoContext()

        # Defaults
        self.axo_endpoint_id = ""
        self.axo_bucket_id = ""
        self.axo_sink_bucket_id = ""
        self.axo_source_bucket_id = ""
        self.axo_output_key = ""
        self.separator = ";"
        self.ao_state:bytes = ao_state
        self.ao_source:str= ao_source
        # self.

    # ------------------------------------------
    def __get_state(self) -> Dict[str, Any]:
        """
        Returns the lookup dict for ID and dependency retrieval.
        METHOD.EXEC → merge metadata + fkwargs
        Others      → just metadata
        """
        if self.operation == "METHOD.EXEC":
            merged = {**self.metadata, **self.fkwargs}
            return merged
        return self.metadata

    # ------------------------------------------
    def get_dependencies(self) -> List[str]:
        d1 = self.__get_state().get("dependencies", [])
        d2 = self.__get_state().get("axo_dependencies", [])
        def safe_list(value) -> List[str]:
            if not isinstance(value, list):
                return []
            # Keep only strings
            return [item for item in value if isinstance(item, str)]
        return safe_list(d1) + safe_list(d2)

    def get_separator(self) -> str:
        return self.__get_state().get("separator", self.separator)

    # ------------------------------------------
    def get_endpoint_id(self) -> str:
        return self.__get_state().get(
            "axo_endpoint_id",
            f"axo-endpoint-{_generate_id(size=5)}"
        )

    def get_sink_bucket_id(self) -> str:
        return self.__get_state().get(
            "axo_sink_bucket_id",
            _generate_id(size=12)
        )

    def get_axo_bucket_id(self) -> str:
        return self.__get_state().get(
            "axo_bucket_id",
            _generate_id(size=12)
            # nanoid(alphabet=string.ascii_lowercase+string.digits)
        )

    def get_axo_key(self) -> str:
        return self.__get_state().get(
            "axo_key",
            _generate_id(size=12)
            # nanoid(alphabet=string.ascii_lowercase+string.digits)
        )

    def get_source_bucket_id(self) -> str:
        return self.__get_state().get(
            "axo_source_bucket_id",
            _generate_id(size=12)
            # nanoid(alphabet=string.ascii_lowercase+string.digits)
        )

    def get_source_keys(self) -> List[str]:
        return self.__get_state().get("axo_source_keys", [])

    def get_sink_keys(self) -> List[str]:
        return self.__get_state().get("axo_sink_keys", [])

    def is_bucket_main_source(self) -> bool:
        return (
            not self.__get_state().get("axo_source_key") and
            len(self.get_source_keys()) == 0
        )
