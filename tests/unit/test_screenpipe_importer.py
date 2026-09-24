"""Unit tests for Screenpipe REST importer (PR-018).

Verifies Part 7.2 and Part 11 (PR-018):
1. Capability probe and health checks.
2. Normalization: timestamp, timezone offset, started/ended times, redaction, nullable confidence.
3. Atomic page transaction and watermark checkpoint update.
4. Idempotent deduplication (I17): replaying same page skips duplicates.
5. Schema unknown safety stop: raises IMPORT_SCHEMA_UNSUPPORTED.
6. Optional direct read-only SQLite adapter with schema version gate.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from lva.journal.repository import JournalRepository
from lva.screenpipe_importer.client import ScreenpipeRestClient
from lva.screenpipe_importer.normalize import normalize_screenpipe_audio_item
from lva.screenpipe_importer.worker import ScreenpipeImportWorker, ScreenpipeSqliteAdapter

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "screenpipe"


class FakeScreenpipeClient(ScreenpipeRestClient):
    def __init__(self, items: list[dict] | None = None, health: bool = True) -> None:
        super().__init__(base_url="http://127.0.0.1:3030")
        self._items = items if items is not None else []
        self._health = health

    async def check_health(self) -> bool:
        return self._health

    async def probe_capabilities(self) -> dict:
        return {
            "healthy": self._health,
            "version": "0.1.0",
            "supported": self._health,
            "base_url": self.base_url,
        }

    async def search(self, *args, **kwargs) -> list[dict]:
        return self._items


def test_normalization_with_timezone_and_redaction():
    fixture_file = FIXTURES_DIR / "audio_search_page.json"
    with open(fixture_file, encoding="utf-8") as f:
        data = json.load(f)

    items = data["data"]
    assert len(items) == 3

    # Item 1: Normal audio with +08:00 offset
    norm1 = normalize_screenpipe_audio_item(items[0])
    assert norm1["raw_text"] == "今天上午讨论了本地语音助手的架构方案"
    assert norm1["utc_offset_minutes"] == 480
    assert norm1["confidence"] is None  # Must be NULL per Part 7.1
    assert norm1["speaker"] == "Builtin Microphone"
    assert norm1["audio_ref"] == "/var/screenpipe/audio_101.wav"
    assert norm1["ended_at_utc_us"] > norm1["started_at_utc_us"]
    assert norm1["provenance"]["redacted"] is False

    # Item 3: Redacted audio
    norm3 = normalize_screenpipe_audio_item(items[2])
    assert norm3["raw_text"] == "[REDACTED]"
    assert norm3["provenance"]["redacted"] is True


@pytest.mark.asyncio
async def test_atomic_page_transaction_and_checkpoint():
    fixture_file = FIXTURES_DIR / "audio_search_page.json"
    with open(fixture_file, encoding="utf-8") as f:
        data = json.load(f)

    repo = JournalRepository(":memory:")
    client = FakeScreenpipeClient(items=data["data"])
    worker = ScreenpipeImportWorker(client=client, repository=repo)

    # Initial watermark is 0
    assert worker.get_watermark() == 0

    # Import page
    imported = await worker.import_page(limit=10)
    assert imported == 3

    # Watermark was updated to max timestamp
    new_watermark = worker.get_watermark()
    assert new_watermark > 0

    # All 3 events are present in Journal
    assert repo.stats()["events"] == 3


@pytest.mark.asyncio
async def test_i17_replay_idempotency():
    fixture_file = FIXTURES_DIR / "audio_search_page.json"
    with open(fixture_file, encoding="utf-8") as f:
        data = json.load(f)

    repo = JournalRepository(":memory:")
    client = FakeScreenpipeClient(items=data["data"])
    worker = ScreenpipeImportWorker(client=client, repository=repo)

    # First import
    count1 = await worker.import_page()
    assert count1 == 3
    watermark1 = worker.get_watermark()

    # Replay same items (simulating crash re-reading identical items)
    count2 = await worker.import_page()
    assert count2 == 0
    assert worker.get_watermark() == watermark1

    # Database still has exactly 3 events
    assert repo.stats()["events"] == 3


@pytest.mark.asyncio
async def test_schema_unknown_safety_stop():
    repo = JournalRepository(":memory:")

    class BrokenSchemaClient(ScreenpipeRestClient):
        async def search(self, *args, **kwargs):
            return "NOT_A_LIST"

    worker = ScreenpipeImportWorker(client=BrokenSchemaClient(), repository=repo)
    with pytest.raises(ValueError, match="IMPORT_SCHEMA_UNSUPPORTED"):
        await worker.import_page()


def test_optional_sqlite_adapter(tmp_path: Path):
    # 1. Disabled by default
    sp_db = tmp_path / "screenpipe.db"
    adapter = ScreenpipeSqliteAdapter(sp_db, enabled=False)
    with pytest.raises(RuntimeError, match="disabled by default"):
        adapter.verify_and_connect()

    # 2. File not found when enabled
    adapter_enabled = ScreenpipeSqliteAdapter(sp_db, enabled=True)
    with pytest.raises(FileNotFoundError):
        adapter_enabled.verify_and_connect()

    # 3. Schema mismatch: missing audio tables
    conn = sqlite3.connect(str(sp_db))
    conn.execute("CREATE TABLE random_unrelated (id INT)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="IMPORT_SCHEMA_UNSUPPORTED"):
        adapter_enabled.verify_and_connect()

    # 4. Valid schema with expected audio table
    conn2 = sqlite3.connect(str(sp_db))
    conn2.execute("CREATE TABLE audio_transcriptions (id INT, transcription TEXT)")
    conn2.commit()
    conn2.close()

    conn_verified = adapter_enabled.verify_and_connect()
    assert conn_verified is not None
    conn_verified.close()


@pytest.mark.asyncio
async def test_real_client_probe_capabilities_and_type_hints(monkeypatch: pytest.MonkeyPatch):
    import typing
    import httpx

    # Verify type hints evaluate without NameError
    hints = typing.get_type_hints(ScreenpipeRestClient.probe_capabilities)
    assert hints["return"] is dict or "dict" in str(hints["return"])

    # 1. Test live mock transport with 200 response
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.1.2"})
        return httpx.Response(404)

    client = ScreenpipeRestClient(base_url="http://test-server")
    # Patch AsyncClient to use MockTransport
    transport = httpx.MockTransport(mock_handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_async_client)

    probe = await client.probe_capabilities()
    assert probe["healthy"] is True
    assert probe["supported"] is True
    assert probe["version"] == "0.1.2"

    # 2. Test connection failure
    def broken_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport_broken = httpx.MockTransport(broken_handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_async_client(transport=transport_broken, *a, **kw))

    probe_broken = await client.probe_capabilities()
    assert probe_broken["healthy"] is False
    assert probe_broken["supported"] is False
    assert "error" in probe_broken


def test_normalization_fallback_id_generation():
    # Item without any 'id' or 'audio_chunk_id'
    item1 = {
        "type": "Audio",
        "content": {
            "timestamp": "2026-09-21T08:00:00Z",
            "transcription": "第一段录音",
        },
    }
    item2 = {
        "type": "Audio",
        "content": {
            "timestamp": "2026-09-21T08:00:00Z",
            "transcription": "第二段录音",
        },
    }

    norm1 = normalize_screenpipe_audio_item(item1)
    norm2 = normalize_screenpipe_audio_item(item2)

    # Both must have non-empty deterministic IDs
    assert norm1["external_id"].startswith("audio_")
    assert norm2["external_id"].startswith("audio_")
    # Different content must not collide!
    assert norm1["external_id"] != norm2["external_id"]
    assert norm1["event_id"] != norm2["event_id"]

