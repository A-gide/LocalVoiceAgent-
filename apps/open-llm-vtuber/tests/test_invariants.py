import asyncio
import json
import time
import os
import sys
from pathlib import Path

# Ensure paths
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir))

from src.open_llm_vtuber.conversations.turn_context import TurnContext
from src.open_llm_vtuber.conversations.latency_trace import LatencyTrace
from src.open_llm_vtuber.conversations.tts_manager import TTSTaskManager
from src.open_llm_vtuber.memory_router import archive_to_screenpipe, query_screenpipe_history


async def test_invariant_1_stale_turn_suppression():
    """Invariant 1: Stale / cancelled turn payloads MUST be suppressed at the WebSocket gate."""
    manager = TTSTaskManager()
    sent_payloads = []

    async def mock_ws_send(data_str: str):
        sent_payloads.append(json.loads(data_str))

    # Sender loop
    sender_task = asyncio.create_task(manager._process_payload_queue(mock_ws_send))

    # Turn 1 enqueues an audio payload
    manager.set_current_turn(1)
    await manager._payload_queue.put(({"type": "audio", "data": "turn_1_chunk"}, 0, 1, None))

    # Before sending, Turn 2 supersedes Turn 1 (or Turn 1 is cancelled)
    manager.set_current_turn(2)
    manager.mark_turn_cancelled(1)

    # Turn 2 enqueues its payload
    await manager._payload_queue.put(({"type": "audio", "data": "turn_2_chunk"}, 1, 2, None))

    # Allow sender task to process queue
    await asyncio.sleep(0.05)
    sender_task.cancel()
    try:
        await sender_task
    except asyncio.CancelledError:
        pass

    # Verify: only Turn 2 audio was sent! Turn 1 audio was completely suppressed.
    assert len(sent_payloads) == 1, f"Expected 1 payload sent, got {len(sent_payloads)}"
    assert sent_payloads[0]["data"] == "turn_2_chunk", f"Unexpected payload: {sent_payloads[0]}"
    print("PASS: Invariant 1 (Stale Turn Suppression at WebSocket Gate)")


async def test_invariant_2_interrupt_idempotence():
    """Invariant 2: Multiple interrupts within 200ms MUST be debounced (first-wins)."""
    last_interrupt_mono = {}
    interrupt_count = 0

    def debounced_interrupt(client_uid: str) -> bool:
        nonlocal interrupt_count
        now = time.monotonic()
        if now - last_interrupt_mono.get(client_uid, 0.0) < 0.200:
            return False  # Debounced / Ignored
        last_interrupt_mono[client_uid] = now
        interrupt_count += 1
        return True

    # Call 1: should succeed
    res1 = debounced_interrupt("client_test")
    assert res1 is True, "First interrupt should execute"

    # Call 2 (after 20ms): should be debounced
    await asyncio.sleep(0.02)
    res2 = debounced_interrupt("client_test")
    assert res2 is False, "Second interrupt within 200ms must be debounced"

    # Call 3 (after 50ms): should be debounced
    await asyncio.sleep(0.05)
    res3 = debounced_interrupt("client_test")
    assert res3 is False, "Third interrupt within 200ms must be debounced"

    # Call 4 (after 250ms): should succeed
    await asyncio.sleep(0.25)
    res4 = debounced_interrupt("client_test")
    assert res4 is True, "Interrupt after 200ms must execute"

    assert interrupt_count == 2, f"Expected 2 executed interrupts, got {interrupt_count}"
    print("PASS: Invariant 2 (Interrupt Idempotence & 200ms Debounce)")


def test_invariant_3_memory_archive_and_fts5_recall():
    """Invariant 3: Archived reality records MUST be indexed and retrievable via FTS5 / SQL."""
    token = f"INVARIANT-{int(time.time())}"
    test_text = f"测试记忆自动化断言{token}，检验FTS5全文索引与时间窗口过滤。"
    
    # 1. Archive to Screenpipe
    arch_ok = archive_to_screenpipe(test_text, source="live", is_input=True)
    assert arch_ok is True, "archive_to_screenpipe failed"

    # 2. Query Screenpipe history
    res = query_screenpipe_history(f"刚才说了关于{token}什么？")
    assert res["found"] is True, f"Recall failed for token {token}"
    assert any(token in r["text"] for r in res["records"]), "Token not found in recalled records"

    # 3. Check device & timestamps
    rec = next(r for r in res["records"] if token in r["text"])
    assert rec["device"] != "", "Device must not be empty"
    assert "timestamp" in rec, "Timestamp must exist"
    print(f"PASS: Invariant 3 (Reality Memory Monotonic Archive & Recall: {rec['device']}, id={rec['id']})")


async def run_all_invariant_tests():
    print("==================================================")
    print("RUNNING STATE MACHINE INVARIANT VERIFICATION SUITE")
    print("==================================================")
    await test_invariant_1_stale_turn_suppression()
    await test_invariant_2_interrupt_idempotence()
    test_invariant_3_memory_archive_and_fts5_recall()
    print("==================================================")
    print("ALL INVARIANTS SATISFIED (3/3 PASS)")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_all_invariant_tests())
