from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, ValidationError, field_validator,model_validator
from option import Ok, Err, Result
import json as J
from axo.helpers import _generate_id
from axo.environment import AXO_ID_SIZE
# from enum import StrEnum
from axo_endpoint.backports import StrEnum
# import time, uuid

# Protocol constants
# ---------------------------------------------------------------------------
