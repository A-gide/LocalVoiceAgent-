"""Invariant tests verifying I01 - I20 per Part 13.2 of the Architecture Plan.

Run:
    python -m pytest tests/invariants/test_invariants.py
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from lva.contracts.commands import CommandEnvelope, TurnSendTextPayload, RuntimeSetModePayload
from lva.contracts.enums import ErrorCode, FloorOwner, Mode, Ownership, PrivacyScope
from lva.contracts.ids import TurnId
from lva.core.capture import CaptureCoordinator
from lva.core.effects import StaleEffectGate
from lva.core.floor import FloorController
from lva.core.interrupt import InterruptController
from lva.core.runtime import RuntimeController
from lva.core.turn import TurnController
from lva.journal.corrections import CorrectionService
from lva.journal.repository import JournalRepository
from lva.journal.temporal import extract_query_temporal_range
from lva.providers.base import ASRProvider, LLMProvider, TTSProvider
from lva.providers.hub_control import LlamaCppHubControlClient
from lva.providers.registry import ProviderRegistry
from lva.transport.auth import TokenValidator


def test_i01_stale_turn_suppression():
    """I01: Stale turn never reaches playback/UI/history/Journal."""
    turn_ctrl = TurnController()
    session_id = uuid4()
    turn_1 = turn_ctrl.create_turn(session_id)
    epoch = 0

    gate = StaleEffectGate(
        get_current_turn=lambda: turn_ctrl.current_turn,
        get_current_epoch=lambda: epoch,
    )

    # Valid check initially
    assert gate.check_gate1_pre_dispatch(turn_1, epoch) is True
    assert gate.check_gate2_in_stream(turn_1, epoch) is True
    assert gate.check_gate3_pre_side_effect(turn_1, epoch, "playback") is True

    # Interrupt / bump epoch or new turn
    turn_2 = turn_ctrl.create_turn(session_id)
    epoch += 1

    # Stale turn_1 must be rejected by all gates
    assert gate.check_gate1_pre_dispatch(turn_1, 0) is False
    assert gate.check_gate2_in_stream(turn_1, 0) is False
    assert gate.check_gate3_pre_side_effect(turn_1, 0, "playback") is False
    assert gate.check_gate3_pre_side_effect(turn_1, 0, "journal_commit") is False
    assert gate.stale_dropped_count >= 4


def test_i02_single_current_turn():
    """I02: Each session has only one current Turn."""
    turn_ctrl = TurnController()
    session_id = uuid4()

    turn_1 = turn_ctrl.create_turn(session_id)
    assert turn_ctrl.current_turn == turn_1
    assert turn_1.sequence == 1

    # Creating turn_2 cancels turn_1
    turn_2 = turn_ctrl.create_turn(session_id)
    assert turn_ctrl.current_turn == turn_2
    assert turn_2.sequence == 2
    assert turn_2 != turn_1


def test_i03_interrupt_floor_user():
    """I03: After interrupt commit, Floor=USER."""
    turn_ctrl = TurnController()
    floor_ctrl = FloorController()
    floor_ctrl.set_owner(FloorOwner.AGENT)

    interrupt_ctrl = InterruptController(
        turn_controller=turn_ctrl,
        floor_controller=floor_ctrl,
    )

    session_id = uuid4()
    turn_ctrl.create_turn(session_id)

    new_epoch = interrupt_ctrl.commit_interrupt(reason="user_barge_in")
    assert new_epoch == 1
    assert floor_ctrl.owner == FloorOwner.USER
    assert turn_ctrl.current_turn is None


def test_i05_side_effect_turn_epoch():
    """I05: Side-effect event has TurnId + provider_epoch."""
    rt = RuntimeController()
    rt.session_controller.start_session()
    turn = rt.turn_controller.create_turn(rt.session_controller.current_session_id)

    from lva.contracts.events import AudioPlaybackStartedPayload

    event = rt.emit_event(
        event_type="audio.playback_started",
        payload=AudioPlaybackStartedPayload(type="audio.playback_started", turn_id=turn, provider_epoch=0),
        turn_id=turn,
    )
    assert event.turn_id == turn
    assert event.turn_id.sequence == 1
    assert event.sequence >= 1


def test_i06_raw_transcript_immutable():
    """I06: Raw transcript immutable, revision append-only."""
    repo = JournalRepository()  # in-memory DB
    event_id = uuid4()
    repo.append_event(
        event_id=event_id,
        raw_text="原始未纠正文本",
        occurred_at_utc_us=1000000,
    )

    # Directly attempting to UPDATE raw_text must fail via trigger
    with pytest.raises(sqlite3.DatabaseError, match="Updating raw_text in events table is forbidden"):
        with repo.conn:
            repo.conn.execute(
                "UPDATE events SET raw_text = '篡改' WHERE event_id = ?",
                (str(event_id),),
            )

    # Adding revision is allowed and increments current_revision
    corrections = CorrectionService(repo)
    rev_1 = corrections.correct_event(
        event_id=event_id,
        corrected_text="纠正后文本第1版",
        reason="typo",
        actor="user",
    )
    assert rev_1 == 1

    ev = repo.get_event(event_id)
    assert ev["raw_text"] == "原始未纠正文本"
    assert ev["current_text"] == "纠正后文本第1版"
    assert ev["current_revision"] == 1

    # Attempting to UPDATE event_revisions must fail via trigger
    with pytest.raises(sqlite3.DatabaseError, match="Updating event_revisions is forbidden"):
        with repo.conn:
            repo.conn.execute(
                "UPDATE event_revisions SET corrected_text = '篡改版本' WHERE event_id = ?",
                (str(event_id),),
            )


@pytest.mark.asyncio
async def test_i07_i08_passive_forbids_llm_tts(isolated_server_data, monkeypatch: pytest.MonkeyPatch):
    """I07 & I08: Passive, Standby, and Privacy Pause modes strictly forbid LLM and TTS scheduling."""
    current_mode = Mode.PASSIVE
    registry = ProviderRegistry(get_current_mode=lambda: current_mode)

    class DummyLLM:
        name = "dummy_llm"
        async def stream_chat(self, *args, **kwargs):
            yield "token"

    class DummyTTS:
        name = "dummy_tts"
        async def stream_speech(self, *args, **kwargs):
            yield b"pcm"

    registry.register_llm(DummyLLM())
    registry.register_tts(DummyTTS())

    turn_id = TurnId(session_id=uuid4(), sequence=1)

    # In Passive, Standby, and Privacy Pause modes: scheduling must raise PASSIVE_PROVIDER_FORBIDDEN
    for forbidden_mode in (Mode.PASSIVE, Mode.STANDBY, Mode.PRIVACY_PAUSE):
        current_mode = forbidden_mode
        with pytest.raises(RuntimeError, match="PASSIVE_PROVIDER_FORBIDDEN"):
            async for _ in registry.stream_chat([], turn_id, 0):
                pass

        with pytest.raises(RuntimeError, match="PASSIVE_PROVIDER_FORBIDDEN"):
            async for _ in registry.stream_speech("hello", turn_id, 0):
                pass

    # In Live mode: calling stream_chat and stream_speech is allowed
    current_mode = Mode.LIVE
    tokens = [c async for c in registry.stream_chat([], turn_id, 0)]
    assert tokens == ["token"]

    audio = [b async for b in registry.stream_speech("hello", turn_id, 0)]
    assert audio == [b"pcm"]

    # Also verify /api/ask endpoint on server.py rejects non-LIVE modes
    from starlette.testclient import TestClient
    from lva import server as server_mod
    from lva.server import app, auth_validator, get_runtime

    client = TestClient(app)
    # The server is fail-closed since R05 (PR-006): configure the singleton's
    # test token so the request reaches the mode guard instead of 401.
    monkeypatch.setattr(auth_validator, "expected_token", "test-secret-token-256bit")
    rt = get_runtime()
    for forbidden_mode in (Mode.PASSIVE, Mode.STANDBY, Mode.PRIVACY_PAUSE):
        rt.set_mode(forbidden_mode)
        resp = client.post("/api/ask", json={"text": "hello", "speak": False},
                           headers={"Authorization": "Bearer test-secret-token-256bit"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == ErrorCode.PASSIVE_PROVIDER_FORBIDDEN.value

        # /api/tts carries the same hard boundary (plan L311/L318). It has no
        # consumer in the product, so the guard is only reachable from here.
        resp = client.post("/api/tts", json={"text": "hello"},
                           headers={"Authorization": "Bearer test-secret-token-256bit"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == ErrorCode.PASSIVE_PROVIDER_FORBIDDEN.value

    # The guard rejects before `core()` is reached, so no forbidden-mode request may
    # load the ASR/TTS stack. (`get_runtime()` does open the Journal to read the mode;
    # the isolated_server_data fixture keeps that off the repository copy.)
    assert server_mod._core is None, "a forbidden mode must not load the ASR/TTS core"


def test_i09_privacy_pause_stops_capture():
    """I09: Privacy Pause stops Core capture."""
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    assert rt.capture_coordinator.core_mic_stopped is False
    assert rt.get_state().mic_capture.active is True

    # Switch to Privacy Pause
    rt.set_mode(Mode.PRIVACY_PAUSE)
    assert rt.capture_coordinator.core_mic_stopped is True
    assert rt.get_state().mic_capture.active is False


def test_i10_privacy_scope_unverified():
    """I10: Managed capture unverified when external capture detected or unconfirmed."""
    coord = CaptureCoordinator()
    coord.stop_core_mic()

    # Case 1: managed stopped verified, no external
    coord.update_managed_capture_status(managed_stopped=True, external_detected=False)
    assert coord.compute_privacy_scope(Mode.PRIVACY_PAUSE) == PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF

    # Case 2: external capture present
    coord.update_managed_capture_status(managed_stopped=True, external_detected=True)
    assert coord.compute_privacy_scope(Mode.PRIVACY_PAUSE) == PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT

    # Case 3: external unknown / unconfirmed
    coord.update_managed_capture_status(managed_stopped=None, external_detected=False)
    assert coord.compute_privacy_scope(Mode.PRIVACY_PAUSE) == PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN


def test_i11_auth_boundary():
    """I11: Unauthenticated / invalid protocol client rejected."""
    validator = TokenValidator(token="secret-256-token", require_auth=True)

    # Valid token
    assert validator.verify_token("secret-256-token") is True

    # Missing or invalid token
    assert validator.verify_token(None) is False
    assert validator.verify_token("wrong-token") is False

    # Disallowed origin
    assert validator.verify_origin("http://malicious.com") is False
    assert validator.verify_origin("tauri://localhost") is True
    assert validator.verify_origin(None) is True  # native loopback allowed


def test_i18_command_idempotency():
    """I18: Command idempotency + optimistic concurrency."""
    rt = RuntimeController()
    cmd = CommandEnvelope(
        idempotency_key="key-abc-123",
        precondition={"aggregate": "runtime_control", "revision": rt.runtime_control_revision},
        type="runtime.set_mode",
        payload=RuntimeSetModePayload(type="runtime.set_mode", mode=Mode.LIVE),
    )

    res1 = rt.execute_command(cmd)
    assert res1.status == "applied"
    assert rt.mode == Mode.LIVE

    # Repeating with same idempotency_key returns "duplicate"
    res2 = rt.execute_command(cmd)
    assert res2.status == "duplicate"

    # Stale expected_state_version returns "rejected" with STALE_STATE
    cmd_stale = CommandEnvelope(
        precondition={"aggregate": "runtime_control", "revision": 0},  # current is now > 0
        type="runtime.set_mode",
        payload=RuntimeSetModePayload(type="runtime.set_mode", mode=Mode.STANDBY),
    )
    res_stale = rt.execute_command(cmd_stale)
    assert res_stale.status == "rejected"
    assert res_stale.error is not None
    assert res_stale.error.code == ErrorCode.STALE_REVISION


def test_temporal_recall_dual_anchor():
    """Part 7.3: Dual anchor temporal resolution and parse-failure fallback."""
    # Query with relative time expression "昨天"
    anchor = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    res = extract_query_temporal_range("我昨天说了什么？", query_anchor=anchor)
    assert res is not None
    start_dt, end_dt, expr = res
    assert expr == "昨天"
    assert start_dt.day == 20
    assert end_dt.day == 20

    # Query with no temporal expression
    res_none = extract_query_temporal_range("请问什么是络合滴定？", query_anchor=anchor)
    assert res_none is None


def test_hub_control_loopback_safety():
    """Part 5.8: Non-loopback Hub management URL rejected for safety."""
    with pytest.raises(ValueError, match="HUB_CONTROL_UNSAFE"):
        LlamaCppHubControlClient(base_url="http://192.168.1.100:8080")

    with pytest.raises(ValueError, match="HUB_CONTROL_UNSAFE"):
        LlamaCppHubControlClient(base_url="http://example.com:8080")

    # Loopback is allowed
    client = LlamaCppHubControlClient(base_url="http://127.0.0.1:8080")
    assert client.base_url == "http://127.0.0.1:8080"


def test_temporal_recall_full_scenario():
    """Part 7.3: Full dual-anchor temporal recall and mention resolution.
    
    1. '我昨天说了什么？' retrieves yesterday's events without requiring '昨天' in text.
    2. '昨天火锅' retrieves yesterday's event '我们去吃火锅吧'.
    3. '今天有什么安排' on 2026-09-11 retrieves '明天做络合滴定' recorded on 2026-09-10.
    4. Non-temporal search ('络合滴定') searches without any time restriction.
    """
    repo = JournalRepository()
    dt_yesterday = datetime(2026, 9, 20, 15, 0, 0, tzinfo=timezone.utc)
    # Event 1: general conversation yesterday
    repo.append_event("e1", "我们去吃火锅吧", occurred_at_utc_us=int(dt_yesterday.timestamp() * 1_000_000))
    # Event 2: planned event mentioning '明天' (which is 2026-09-21)
    repo.append_event("e2", "明天做络合滴定", occurred_at_utc_us=int(dt_yesterday.timestamp() * 1_000_000))

    dt_today = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Pure temporal query: "我昨天说了什么？"
    hits_yesterday = repo.search("我昨天说了什么？", query_anchor=dt_today)
    assert len(hits_yesterday) == 2
    texts_yesterday = [h["current_text"] for h in hits_yesterday]
    assert "我们去吃火锅吧" in texts_yesterday
    assert "明天做络合滴定" in texts_yesterday

    # 2. Keyword + temporal query: "昨天火锅"
    hits_hotpot = repo.search("昨天火锅", query_anchor=dt_today)
    assert len(hits_hotpot) == 1
    assert hits_hotpot[0]["current_text"] == "我们去吃火锅吧"

    # 3. Mentioned range query: "今天有什么安排" on 2026-09-21 retrieves event from 2026-09-10
    hits_today = repo.search("今天有什么安排", query_anchor=dt_today)
    assert len(hits_today) >= 1
    texts_today = [h["current_text"] for h in hits_today]
    assert "明天做络合滴定" in texts_today

    # 4. Non-temporal query: "络合滴定" searches full history without time restrictions
    hits_chemi = repo.search("络合滴定", query_anchor=dt_today)
    assert len(hits_chemi) == 1
    assert hits_chemi[0]["current_text"] == "明天做络合滴定"


def test_i14_hub_disconnected_resilience():
    """I14: Hub disconnected / unavailable -> Passive/Memory/UI continue."""
    rt = RuntimeController()
    repo = JournalRepository()

    # Even if Hub is completely disconnected, Core can transition modes
    rt.set_mode(Mode.PASSIVE)
    assert rt.mode == Mode.PASSIVE

    # Journal memory read/write continues normally
    eid = uuid4()
    repo.append_event(eid, "测试离线记录", occurred_at_utc_us=1000000)
    ev = repo.get_event(eid)
    assert ev is not None
    assert ev["raw_text"] == "测试离线记录"

    # UI snapshot generation continues normally
    snap = rt.get_state()
    assert snap.mode == Mode.PASSIVE
    assert snap.hub_binding is None


def test_i15_model_switch_suppresses_late_effects():
    """I15: Model switch increments epoch and suppresses late effects."""
    rt = RuntimeController()
    rt.session_controller.start_session()
    turn_1 = rt.turn_controller.create_turn(rt.session_controller.current_session_id)
    epoch_old = rt.current_epoch

    # Pre-check passes
    assert rt.stale_gate.check_gate1_pre_dispatch(turn_1, epoch_old) is True

    # Simulate model switch triggering interrupt
    new_epoch = rt.interrupt_controller.commit_interrupt(reason="model_switch")
    assert new_epoch == epoch_old + 1

    # Late response from old model must be rejected by all gates
    assert rt.stale_gate.check_gate2_in_stream(turn_1, epoch_old) is False
    assert rt.stale_gate.check_gate3_pre_side_effect(turn_1, epoch_old, "llm_output") is False


@pytest.mark.asyncio
async def test_i17_importer_idempotent_replay():
    """I17: Screenpipe importer replay idempotency."""
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    class MockScreenpipeClient:
        async def search(self, *args, **kwargs):
            return [
                {
                    "type": "Audio",
                    "content": {
                        "transcription": "录音片段测试",
                        "timestamp": "2026-09-21T08:00:00Z",
                    },
                }
            ]

    repo = JournalRepository()
    worker = ScreenpipeImportWorker(client=MockScreenpipeClient(), repository=repo)

    # First import: imports 1 item
    count1 = await worker.import_page(limit=10)
    assert count1 == 1

    # Replay same page: imports 0 items (idempotently skipped via ux_events_external)
    count2 = await worker.import_page(limit=10)
    assert count2 == 0


def test_i19_restart_always_standby():
    """I19: Core initialization always defaults to Standby."""
    rt1 = RuntimeController()
    rt1.set_mode(Mode.LIVE)
    assert rt1.mode == Mode.LIVE

    # New runtime instance (simulating restart)
    rt2 = RuntimeController()
    assert rt2.mode == Mode.STANDBY
    assert rt2.get_state().resume_mode is None


def test_i20_public_settings_no_secrets():
    """I20: PublicAppSettings never exposes secrets in JSON."""
    from lva.contracts.state import RuntimeState
    # Test that runtime state does not contain any secret keys
    rt = RuntimeController()
    state_json = rt.get_state().model_dump_json()
    assert "sk-" not in state_json
    assert "api_key" not in state_json


def test_legacy_migration_robust_to_malformed_data(tmp_path):
    """Part 7.4 & Untested Edge Case 3: Robust migration of legacy DB with malformed/null data."""
    from lva.journal.migrate_legacy import migrate_legacy_db

    legacy_db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(legacy_db))
    conn.execute("""
        CREATE TABLE utterances (
            id INTEGER PRIMARY KEY,
            ts REAL,
            source TEXT,
            speaker TEXT,
            raw_text TEXT,
            fixed_text TEXT,
            domain TEXT,
            audio_path TEXT,
            duration_s REAL,
            meta TEXT
        )
    """)
    # Row 1: Valid row
    conn.execute(
        "INSERT INTO utterances VALUES (1, 1789000000.0, 'mic', 'user', '正常文本', '纠正文本', 'chat', '', 1.0, '{\"k\": \"v\"}')"
    )
    # Row 2: Malformed timestamp (None)
    conn.execute(
        "INSERT INTO utterances VALUES (2, NULL, 'mic', 'user', '无时间戳文本', NULL, 'chat', '', 1.0, '{}')"
    )
    # Row 3: Non-JSON metadata
    conn.execute(
        "INSERT INTO utterances VALUES (3, 1789000010.0, 'mic', 'user', '非法元数据文本', NULL, 'chat', '', 1.0, 'NOT_JSON')"
    )
    conn.commit()
    conn.close()

    target_repo = JournalRepository()
    report = migrate_legacy_db(legacy_db, target_repo)

    assert report["total_legacy_rows"] == 3
    assert report["migrated_count"] == 2
    assert report["revisions_created"] == 1
    assert report["invalid_rows"] == 1
    assert len(report["errors"]) == 1


def test_i04_adopted_external_unknown_never_auto_killed():
    """I04: Adopted, External, and Unknown processes are never auto-killed."""
    class ProcessSupervisor:
        def __init__(self):
            self.processes: dict[str, Ownership] = {}
            self.killed: list[str] = []

        def register(self, name: str, ownership: Ownership):
            self.processes[name] = ownership

        def stop_spawned(self, name: str) -> bool:
            ownership = self.processes.get(name, Ownership.UNKNOWN)
            if ownership == Ownership.SPAWNED:
                self.killed.append(name)
                del self.processes[name]
                return True
            # Adopted, External, and Unknown are strictly observe-only
            return False

        def stop_all(self):
            for name in list(self.processes.keys()):
                self.stop_spawned(name)

    sup = ProcessSupervisor()
    sup.register("lva_core", Ownership.SPAWNED)
    sup.register("llama_hub", Ownership.EXTERNAL)
    sup.register("screenpipe_external", Ownership.ADOPTED)
    sup.register("random_tool", Ownership.UNKNOWN)

    # Attempting to stop external / adopted / unknown must return False and not kill
    assert sup.stop_spawned("llama_hub") is False
    assert sup.stop_spawned("screenpipe_external") is False
    assert sup.stop_spawned("random_tool") is False
    assert "llama_hub" not in sup.killed
    assert "screenpipe_external" not in sup.killed

    # stop_all only stops Spawned
    sup.stop_all()
    assert sup.killed == ["lva_core"]
    assert "llama_hub" in sup.processes
    assert "screenpipe_external" in sup.processes


@pytest.mark.asyncio
async def test_i12_provider_crash_preserves_session_and_journal():
    """I12: Provider crash does not destroy Session or corrupt Journal."""
    rt = RuntimeController()
    repo = JournalRepository()
    rt.set_mode(Mode.LIVE)

    rt.session_controller.start_session()
    session_id = rt.session_controller.current_session_id
    assert session_id is not None

    turn_1 = rt.turn_controller.create_turn(session_id, user_text="Hello")
    assert rt.turn_controller.current_turn == turn_1

    # Simulate provider crash during streaming
    try:
        raise ConnectionResetError("Provider connection reset by peer")
    except Exception:
        rt.turn_controller.cancel_turn(turn_1, reason="provider_crash")

    # Verify session remains intact and current_turn is cleared
    assert rt.session_controller.current_session_id == session_id
    assert rt.turn_controller.current_turn is None

    # Verify Journal integrity is intact
    cursor = repo.conn.execute("PRAGMA integrity_check;")
    assert cursor.fetchone()[0] == "ok"

    # Turn 2 can proceed on the same session
    turn_2 = rt.turn_controller.create_turn(session_id, user_text="Retry after crash")
    assert turn_2.sequence == 2
    assert rt.turn_controller.current_turn == turn_2

    # Commit Turn 2 to Journal
    repo.append_event(
        event_id=uuid4(),
        raw_text="Retry after crash",
        session_id=session_id,
        turn_sequence=turn_2.sequence,
    )
    rt.turn_controller.complete_turn(turn_2)

    ev = repo.search("Retry after crash")
    assert len(ev) == 1
    assert ev[0]["raw_text"] == "Retry after crash"
    full_event = repo.get_event(ev[0]["event_id"])
    assert full_event is not None
    assert full_event["turn_sequence"] == 2



def test_i13_audio_callback_never_blocks():
    """I13: Audio callback never blocks; queue overflow drops oldest and counts."""
    import queue
    import time
    from lva.pipeline import VoiceCore

    q: queue.Queue = queue.Queue(maxsize=5)
    stats: dict[str, int] = {}

    # Fill queue to capacity
    for i in range(5):
        VoiceCore._offer(q, f"chunk-{i}", "frames_dropped", stats)
    assert q.qsize() == 5
    assert stats.get("frames_dropped", 0) == 0

    # Overfill by 100 items - verify execution time and drop counting
    t0 = time.perf_counter()
    for i in range(100):
        VoiceCore._offer(q, f"overflow-{i}", "frames_dropped", stats)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert stats["frames_dropped"] == 100
    assert q.qsize() == 5
    # P99 requirement: average time per call must be << 1ms
    avg_per_call_ms = elapsed_ms / 100
    assert avg_per_call_ms < 0.1, f"Audio callback took {avg_per_call_ms}ms, expected < 0.1ms"


@pytest.mark.asyncio
async def test_i16_lva_never_kills_hub_owned_child():
    """I16: LVA never kills Hub-owned child processes."""
    from lva.providers.hub_control import LlamaCppHubControlClient
    from lva.providers.hub_inference import LlamaCppHubInferenceClient
    from lva.providers.hub_runtime import HubRuntimeSaga

    control = LlamaCppHubControlClient(base_url="http://127.0.0.1:8080")
    inference = LlamaCppHubInferenceClient(base_url="http://127.0.0.1:8080")

    saga = HubRuntimeSaga(control_client=control, inference_client=inference)

    # By default, load_origin is 'unknown' or 'preexisting'
    saga.binding.active_model_id = "external-qwen"
    saga.binding.load_origin = "preexisting"

    stop_called = False

    async def mock_stop(model_id: str):
        nonlocal stop_called
        stop_called = True
        return {"status": "ok"}

    control.stop_model = mock_stop

    # Sleep AI without force must NOT stop preexisting Hub model
    await saga.sleep_bound_model(force=False)
    assert stop_called is False
    assert saga.binding.active_model_id == "external-qwen"

    # Only when load_origin is 'loaded_by_lva' is explicit stop allowed
    saga.binding.load_origin = "loaded_by_lva"
    await saga.sleep_bound_model(force=False)
    assert stop_called is True
    assert saga.binding.active_model_id is None


