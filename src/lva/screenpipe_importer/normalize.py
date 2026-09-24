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
        except Exception:
            occ_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    else:
        occ_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

    # Redaction handling (Part 7.2: respect source redaction/deletion marks)
    is_redacted = bool(
        item.get("redacted")
        or content.get("redacted")
        or item.get("is_redacted")
        or transcription.strip() == "[REDACTED]"
    )
    if is_redacted:
        transcription = "[REDACTED]"

    raw_id = item.get("id") or content.get("id") or content.get("audio_chunk_id")
    if raw_id:
        external_id = str(raw_id)
    else:
        content_hash = hashlib.sha256(transcription.encode("utf-8")).hexdigest()[:12]
        external_id = f"audio_{occ_us}_{content_hash}"
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
        "confidence": None,  # Screenpipe raw transcription has no confidence; NULL per Part 7.1
        "domain": "screenpipe_capture",
        "provenance": provenance,
    }

