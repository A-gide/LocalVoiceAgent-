from __future__ import annotations

from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class SessionRecord(BaseModel):
    session_id: UUID
    started_at_utc_us: int
    ended_at_utc_us: int | None = None
    source: str = "lva"


class TurnRecord(BaseModel):
    session_id: UUID
    turn_sequence: int = Field(ge=1)
    started_at_utc_us: int
    ended_at_utc_us: int | None = None
    status: str = "completed"


class JournalEvent(BaseModel):
    event_id: UUID
    session_id: UUID | None = None
    turn_sequence: int | None = None
    external_source: str | None = None
    external_id: str | None = None
    occurred_at_utc_us: int
    event_timezone: str = "UTC"
    utc_offset_minutes: int = 0
    started_at_utc_us: int | None = None
    ended_at_utc_us: int | None = None
    speaker: str | None = None
    source: str = "core"
    raw_text: str
    current_revision: int = 0
    audio_ref: str | None = None
    asr_provider: str | None = None
    asr_model: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    domain: str | None = None
    provenance_json: dict[str, Any] = Field(default_factory=dict)
    created_at_utc_us: int


class EventRevision(BaseModel):
    event_id: UUID
    revision: int = Field(ge=1)
    corrected_text: str
    rules_version: str | None = None
    reason: str
    actor: str = "user"
    created_at_utc_us: int


class TemporalMention(BaseModel):
    event_id: UUID
    revision: int
    mention_index: int = Field(ge=0)
    span_start: int = Field(ge=0)
    span_end: int
    expression: str
    anchor_utc_us: int
    range_start_utc_us: int | None = None
    range_end_utc_us: int | None = None
    parser_version: str = "1.0"
    parse_status: str = "parsed"


class ImportCheckpoint(BaseModel):
    importer: str
    external_source: str
    cursor: str | None = None
    watermark_utc_us: int | None = None
    source_schema_version: str | None = None
    updated_at_utc_us: int


class DeletionAuditRecord(BaseModel):
    operation_id: UUID
    requested_at_utc_us: int
    completed_at_utc_us: int | None = None
    reason_code: str
    event_id_hashes_json: list[str]
    deleted_count: int


class RevisionHistoryDTO(BaseModel):
    revision: int
    corrected_text: str
    reason: str
    actor: str
    rules_version: str | None = None
    created_at_utc_us: int


class EventHistoryDTO(BaseModel):
    event_id: UUID
    raw_text: str
    current_text: str
    current_revision: int
    occurred_at_utc_us: int
    event_timezone: str
    speaker: str | None = None
    source: str
    domain: str | None = None
    confidence: float | None = None
    revisions: list[RevisionHistoryDTO] = Field(default_factory=list)
    temporal_mentions: list[TemporalMention] = Field(default_factory=list)

