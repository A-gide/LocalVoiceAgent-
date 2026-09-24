from __future__ import annotations

from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class TurnId(BaseModel):
    session_id: UUID
    sequence: int = Field(ge=1, description="Per-session monotonic sequence number, starting at 1")

    def __str__(self) -> str:
        return f"{self.session_id}:{self.sequence}"

    def __hash__(self) -> int:
        return hash((self.session_id, self.sequence))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TurnId):
            return self.session_id == other.session_id and self.sequence == other.sequence
        return False
