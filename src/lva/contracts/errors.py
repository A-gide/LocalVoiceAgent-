from __future__ import annotations

from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, field_validator

from lva.observability.redact import redact_dict
from .enums import ErrorCode


class ErrorEnvelope(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    severity: Literal["info", "warning", "error", "fatal"] = "error"
    component: str
    correlation_id: UUID
    redacted_details: dict[str, Any] | None = None

    @field_validator("redacted_details", mode="before")
    @classmethod
    def _sanitize_redacted_details(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return redact_dict(v)
        return v
