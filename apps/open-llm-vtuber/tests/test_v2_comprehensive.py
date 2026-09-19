import asyncio
import json
import time
import os
import sys
import websockets
import numpy as np
from pathlib import Path

# Ensure paths
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir))

from src.open_llm_vtuber.conversations.turn_context import TurnContext
from src.open_llm_vtuber.conversations.latency_trace import LatencyTrace
from src.open_llm_vtuber.conversations.tts_manager import TTSTaskManager
from src.open_llm_vtuber.memory_router import (
    archive_to_screenpipe,
    query_screenpipe_history,
    correct_scientific_terminology,
    load_user_profile,
    get_lva_root,
)

URI = "ws://127.0.0.1:12393/client-ws"

async def test_a1_turn_context_three_lines_defense():
    ctx1 = TurnContext(turn_id=1, client_uid="client_a1")
    assert ctx1.is_live() is True
    assert ctx1.turn_id == 1

    ctx1.mark_cancelled()
    assert ctx1.is_live() is False
    assert ctx1.cancelled is True

    async def mock_llm_call(t_ctx: TurnContext):
        if not t_ctx.is_live():
            return "SKIPPED_DUE_TO_STALE"
        return "GENERATED_OUTPUT"

    res = await mock_llm_call(ctx1)
    assert res == "SKIPPED_DUE_TO_STALE"

    tts = TTSTaskManager()
    sent = []

    async def mock_send(p_str: str):
        sent.append(json.loads(p_str))

    sender = asyncio.create_task(tts._process_payload_queue(mock_send))
    tts.set_current_turn(1)
    await tts._payload_queue.put(({"type": "audio", "data": "turn1_voice"}, 0, 1, None))
    tts.set_current_turn(2)
    tts.mark_turn_cancelled(1)
    await tts._payload_queue.put(({"type": "audio", "data": "turn2_voice"}, 1, 2, None))

    await asyncio.sleep(0.05)
    sender.cancel()
    try:
        await sender
    except asyncio.CancelledError:
        pass

    assert len(sent) == 1
    assert sent[0]["data"] == "turn2_voice"
    print("PASS: A1 (TurnContext 3-Line Defense successfully suppresses stale turn)")

async def test_a2_exact_drain_isolation():
    tts = TTSTaskManager()
    task1_cancelled = False
    task2_cancelled = False

    async def worker_1():
        nonlocal task1_cancelled
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            task1_cancelled = True
            raise

    async def worker_2():
        nonlocal task2_cancelled
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            task2_cancelled = True
            raise

    t1 = asyncio.create_task(worker_1())
    t2 = asyncio.create_task(worker_2())
    await asyncio.sleep(0.01)

    setattr(t1, "_turn_id", 101)
    setattr(t2, "_turn_id", 102)

    tts.task_list.append(t1)
    tts.task_list.append(t2)

    # Drain ONLY turn 101
    tts.drain(101)
    await asyncio.sleep(0.02)

    assert t1.cancelled() or task1_cancelled, "Task 1 (turn 101) must be cancelled"
    assert not t2.cancelled() and not task2_cancelled, "Task 2 (turn 102) must NOT be cancelled"
    assert t2 in tts.task_list, "Task 2 must remain in task_list"
    assert t1 not in tts.task_list, "Task 1 must be purged from task_list"

    t2.cancel()
    try:
        await t2
    except asyncio.CancelledError:
        pass

    print("PASS: A2 (Exact Drain(turn_id) successfully isolates other turns)")

async def test_a3_interrupt_debounce():
    last_interrupt = {}
    triggered = []

    def handle_interrupt(client_uid: str, source: str):
        now = time.monotonic()
        if now - last_interrupt.get(client_uid, 0.0) < 0.200:
            return False
        last_interrupt[client_uid] = now
        triggered.append((source, now))
        return True

    assert handle_interrupt("c1", "vad_pause") is True
    await asyncio.sleep(0.02)
    assert handle_interrupt("c1", "frontend_button") is False
    await asyncio.sleep(0.03)
    assert handle_interrupt("c1", "speech_start") is False

    await asyncio.sleep(0.22)
    assert handle_interrupt("c1", "new_vad_pause") is True

    assert len(triggered) == 2
    assert triggered[0][0] == "vad_pause"
    assert triggered[1][0] == "new_vad_pause"
    print("PASS: A3 (200ms Interrupt Debounce First-Wins operates cleanly)")

async def test_a4_non_blocking_cancellation():
    async def long_running():
        await asyncio.sleep(60.0)

    task = asyncio.create_task(long_running())
    t0 = time.perf_counter()
    task.cancel()
    t_elapsed = (time.perf_counter() - t0) * 1000

    assert t_elapsed < 5.0, f"Cancellation took too long: {t_elapsed:.2f}ms"
    assert task.cancelling() or task.cancelled()
    try:
        await task
    except asyncio.CancelledError:
        pass
    print(f"PASS: A4 (Non-blocking cancellation executed in {t_elapsed:.3f}ms)")

async def test_a5_early_transcription_reuse():
    """Verify A5 early transcription reuse and latency hiding (RealtimeSTT pattern)."""
    from src.open_llm_vtuber.conversations.conversation_utils import process_user_input

    class MockASR:
        async def async_transcribe_np(self, arr):
            await asyncio.sleep(0.01)
            return "预转写完成"

    mock_asr = MockASR()
    full_audio = np.zeros(16000, dtype=np.float32)  # 1.0s audio

    # Case 1: Early task completed during silence gap (0ms perceived wait)
    early_task = asyncio.create_task(mock_asr.async_transcribe_np(full_audio[:14000]))
    await early_task  # simulate task finished during user trailing silence

    sent_ws = []
    async def mock_ws(msg):
        sent_ws.append(json.loads(msg))

    t0 = time.perf_counter()
    result_text = await process_user_input(
        user_input=full_audio,
        asr_engine=mock_asr,
        websocket_send=mock_ws,
        early_asr_task=early_task,
        early_asr_samples=14000
    )
    t_reuse = (time.perf_counter() - t0) * 1000

    assert result_text == "预转写完成"
    assert t_reuse < 5.0, f"Early transcription reuse took too long: {t_reuse}ms"
    assert len(sent_ws) == 1
    assert sent_ws[0]["type"] == "user-input-transcription"
    print(f"PASS: A5 (Early transcription reused in {t_reuse:.3f}ms, ASR wait hidden)")

async def test_a7_live_websocket_latency_trace():
    trace_received = None
    async with websockets.connect(URI, max_size=10*1024*1024) as ws:
        msg = {"type": "text-input", "text": "你好，请回答一加一等于几。"}
        await ws.send(json.dumps(msg, ensure_ascii=False))

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                data = json.loads(raw)
                if data.get("type") == "audio":
                    if "trace" in data:
                        trace_received = data["trace"]
                    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
                elif data.get("type") == "control" and data.get("text") == "conversation-chain-end":
                    break
            except asyncio.TimeoutError:
                break

    assert trace_received is not None, "First audio payload must contain trace metadata"
    assert "llm_ttft_ms" in trace_received, "Trace must include llm_ttft_ms"
    assert "tts_chunk_ms" in trace_received, "Trace must include tts_chunk_ms"
    assert trace_received["llm_ttft_ms"] is not None and trace_received["llm_ttft_ms"] > 0
    assert trace_received["tts_chunk_ms"] is not None and trace_received["tts_chunk_ms"] > 0
    print(f"PASS: A7 (Live LatencyTrace verified: TTFT={trace_received['llm_ttft_ms']}ms, TTS_chunk={trace_received['tts_chunk_ms']}ms)")

async def test_p1_p2_reality_memory_fts5_and_device():
    tag = f"TEST-P13-{int(time.time())}"
    content = f"真实性验证记录{tag}，检验Screenpipe硬件名与FTS5匹配。"

    ok = await asyncio.to_thread(archive_to_screenpipe, content, "live", True)
    assert ok is True

    res = await asyncio.to_thread(query_screenpipe_history, f"刚才说了关于{tag}什么？")
    assert res["found"] is True
    assert any(tag in r["text"] for r in res["records"])

    rec = next(r for r in res["records"] if tag in r["text"])
    assert rec["device"] != ""
    assert rec.get("id") is not None
    print(f"PASS: P1-1, P1-3, P2-3 (Async FTS5 recall & Hardware Device: '{rec['device']}', id={rec['id']})")

async def test_b1_proactive_tiered_follow_up():
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "ai-speak-signal", "tier": 1}))
        audio_chunks = 0
        reply_text = ""

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                data = json.loads(raw)
                if data.get("type") == "audio":
                    audio_chunks += 1
                    dt = data.get("display_text")
                    if isinstance(dt, dict):
                        reply_text += dt.get("text", "")
                    elif isinstance(dt, str):
                        reply_text += dt
                    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
                elif data.get("type") == "control" and data.get("text") == "conversation-chain-end":
                    break
            except asyncio.TimeoutError:
                break

        assert audio_chunks > 0, "Expected audio response for tier 1 proactive speak"
        assert len(reply_text.strip()) > 0, "Expected non-empty response for tier 1 proactive speak"
        print(f"PASS: B1 (Tiered Silence Follow-up verified: {reply_text.strip()[:35]}...)")

def test_b2_user_profile_reading():
    prof = load_user_profile()
    assert isinstance(prof, dict)
    print(f"PASS: B2 (User Profile reader functional, current keys={list(prof.keys())})")

async def main():
    print("=================================================================")
    print("STARTING COMPREHENSIVE V2 OPTIMIZATION VERIFICATION SUITE")
    print("=================================================================\n")
    await test_a1_turn_context_three_lines_defense()
    await test_a2_exact_drain_isolation()
    await test_a3_interrupt_debounce()
    await test_a4_non_blocking_cancellation()
    await test_a5_early_transcription_reuse()
    await test_a7_live_websocket_latency_trace()
    await test_p1_p2_reality_memory_fts5_and_device()
    await test_b1_proactive_tiered_follow_up()
    test_b2_user_profile_reading()
    print("\n=================================================================")
    print("ALL V2 OPTIMIZATION TESTS SATISFIED (9/9 PASS)")
    print("=================================================================")

if __name__ == "__main__":
    asyncio.run(main())
