from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any
from uuid import uuid5, NAMESPACE_DNS


def normalize_screenpipe_audio_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Screenpipe audio search result into Journal event format per Part 7.2."""
    content = item.get("content", {})
    transcription = content.get("transcription", "")
    timestamp_str = content.get("timestamp") or item.get("timestamp")

    event_timezone = "UTC"
    utc_offset_minutes = 0

    if timestamp_str:
        try:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            occ_us = int(dt.timestamp() * 1_000_000)
            if dt.tzinfo and dt.utcoffset() is not None:
                utc_offset_minutes = int(dt.utcoffset().total_seconds() / 60)
                event_timezone = f"UTC{'+' if utc_offset_minutes >= 0 else ''}{utc_offset_minutes // 60:+03d}:{abs(utc_offset_minutes) % 60:02d}" if utc_offset_minutes != 0 else "UTC"
        except Exception as exc:
            # A timestamp that cannot be parsed must not be silently replaced with
            # "now": that value advances the import checkpoint past every record
            # still waiting to be imported, losing them permanently.  The caller
            # decides what to do with an unusable record (the importer skips it and
            # does not advance the watermark).
            raise ValueError(
                f"unparseable Screenpipe timestamp {timestamp_str!r}; refusing to "
                "substitute the current time, which would advance the import "
                "checkpoint past unimported records"
            ) from exc
    else:
        # A *missing* timestamp is the same defect as an unparseable one:
        # substituting "now" makes the record look like the newest thing the
        # source has, so the import checkpoint jumps to the present and every
        # earlier record that has not been imported yet is skipped forever.
        raise ValueError(
            "Screenpipe record carries no timestamp; refusing to substitute the "
            "current time, which would advance the import checkpoint past "
            "unimported records"
        )

    raw_id = item.get("id") or content.get("id") or content.get("audio_chunk_id")

    # A redaction must target an identity supplied by the source.  With only a
    # derived identity, replacing the text changes the hash inputs and can create
    # a second redacted row while leaving the original searchable.  Time/path/text
    # resemblance is not enough evidence to revise or delete an existing event.
    is_redacted = bool(
        item.get("redacted")
        or content.get("redacted")
        or item.get("is_redacted")
        or transcription.strip() == "[REDACTED]"
    )
    if is_redacted and not raw_id:
        raise ValueError(
            "UNVERIFIED_SOURCE_REDACTION: Screenpipe marked a record redacted but "
            "provided no stable source id; refusing to create a derived redacted "
            "row or claim the prior transcript was removed"
        )
    if is_redacted:
        transcription = "[REDACTED]"

    if raw_id:
        external_id = str(raw_id)
        external_id_is_derived = False
        #: Ids written by earlier formulas for this same record.  A source id is
        #: stable by definition, so there is nothing to reconcile.
        legacy_external_ids: list[str] = []
    else:
        device = content.get("device_name") or item.get("device_name") or ""
        duration = content.get("duration") or item.get("duration") or ""
        # The source gave no id.  A derived id cannot be both stable across a
        # redaction and unique per record: the capture properties (timestamp,
        # device, duration) are stable but two utterances can share them, while
        # the text is unique but is exactly what a redaction rewrites.
        #
        # Plan L901 makes the unique constraint the final idempotency guarantee,
        # so uniqueness wins -- a collision would silently drop a record.  The
        # text is therefore part of the identity, and the id is flagged as
        # derived so a reconciliation refuses to rely on it and reports the
        # limitation rather than pretending the record can be matched.
        # Plan L901 makes the unique constraint the final idempotency guarantee,
        # so uniqueness wins -- a collision would silently drop a record.  Every
        # property that can distinguish two captures is therefore part of the
        # identity, including the source file: two clips can share a timestamp,
        # device, duration and even text while being different recordings.
        #
        # The version tag is what keeps a *replay* idempotent across this change:
        # rows written by the previous formula are recognised by their legacy id
        # (see `legacy_external_ids`), so an already-imported record is not
        # inserted a second time.
        file_path = content.get("file_path") or item.get("file_path") or ""
        identity = f"{occ_us}|{device}|{duration}|{file_path}|{transcription}"
        content_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        external_id = f"audio_{occ_us}_{content_hash}"
        external_id_is_derived = True
        #: The id the pre-version formula produced, kept so a replay of a record
        #: imported before this change is recognised as the same record.
        legacy_external_ids = [
            f"audio_{occ_us}_{hashlib.sha256(transcription.encode('utf-8')).hexdigest()[:12]}"
        ]
    event_id = uuid5(NAMESPACE_DNS, f"screenpipe.audio.{external_id}")

    started_at_us = occ_us
    ended_at_us = None
    duration = content.get("duration") or item.get("duration")
    if duration is not None:
        try:
            ended_at_us = started_at_us + int(float(duration) * 1_000_000)
        except (ValueError, TypeError):
            pass

    audio_file_path = content.get("file_path") or item.get("file_path")

    provenance = {
        "screenpipe_id": external_id,
        "device_name": content.get("device_name"),
        "audio_file_path": audio_file_path,
        "redacted": is_redacted,
        # S2: whether the id came from the source or was derived here.  A caller
        # reconciling historical redactions needs to know which ids it can trust.
        "stable_id": not external_id_is_derived,
    }

    return {
        "event_id": event_id,
        "raw_text": transcription,
        "occurred_at_utc_us": occ_us,
        "event_timezone": event_timezone,
        "utc_offset_minutes": utc_offset_minutes,
        "started_at_utc_us": started_at_us,
        "ended_at_utc_us": ended_at_us,
        "speaker": content.get("device_name", "screenpipe_mic"),
        "source": "screenpipe",
        "audio_ref": audio_file_path,
        "external_source": "screenpipe_rest",
        "external_id": external_id,
        #: Previous-formula ids for this record, so a replay of an
        #: already-imported record is recognised instead of duplicated.
        "legacy_external_ids": legacy_external_ids,
        # S1: the mark is exposed at the top level as well as in provenance.
        # The importer reads it from here; keeping it *only* inside provenance
        # meant the redaction branch could never fire, so a source's later
        # redaction was silently ignored and the original text stayed.
        "redacted": is_redacted,
        "external_id_is_derived": external_id_is_derived,
        "confidence": None,  # Screenpipe raw transcription has no confidence; NULL per Part 7.1
        "domain": "screenpipe_capture",
        "provenance": provenance,
    }
