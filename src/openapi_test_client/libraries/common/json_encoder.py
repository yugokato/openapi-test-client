import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class CustomJsonEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, UUID | Decimal):
            return str(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)
        elif isinstance(obj, BaseModel):
            return obj.model_dump(mode="json", exclude_unset=True)
        else:
            try:
                return super().default(obj)
            except TypeError:
                return str(obj)
