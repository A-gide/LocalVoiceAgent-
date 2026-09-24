"""End-to-end integration tests for multi-turn llama.cpp-hub streaming and model lifecycle.

Verifies:
1. Multi-turn conversation streaming from Hub inference client with SSE chunks.
2. Interruption / barge-in mid-stream with StaleEffectGate suppression of late tokens.
3. Hub model switch saga: conflict resolution, profile loading, polling verification, epoch bumps.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from lva.contracts.enums import Mode
from lva.contracts.ids import TurnId
from lva.core.runtime import RuntimeController
from lva.journal.repository import JournalRepository
from lva.providers.hub_control import LlamaCppHubControlClient
from lva.providers.hub_inference import LlamaCppHubInferenceClient
from lva.providers.hub_runtime import HubRuntimeSaga
from lva.providers.registry import ProviderRegistry


class MockHubTransport(httpx.AsyncBaseTransport):
    """Hermetic in-memory mock of llama.cpp-hub HTTP and SSE endpoints."""

    def __init__(self):
        self.models_catalog = [
            {"id": "qwen2.5-7b", "name": "Qwen 2.5 7B", "size": "4.5GB"},
            {"id": "spark-4b", "name": "Spark-X2.5-4B", "size": "2.8GB"},
        ]
        self.loaded_models: list[dict] = [
            {"modelId": "spark-4b", "status": "loaded", "port": 8081}
        ]
        self.profiles = {
            "spark-4b": {"cmd": "--ctx-size 8192 -ngl 99", "llamaBinPathSelect": "default"},
            "qwen2.5-7b": {"cmd": "--ctx-size 4096 -ngl 33", "llamaBinPathSelect": "default"},
        }
        self.stopped_models: list[str] = []
        self.load_calls: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        method = request.method

        if url_path == "/api/sys/version":
            return httpx.Response(200, json={"version": "0.9.8.3", "commit": "a9cf12809e8243ff0b820abda1a24934d4eb7026"})

        if url_path == "/api/node/info":
            return httpx.Response(200, json={"nodes": [{"id": "node-1", "status": "active"}]})

        if url_path == "/api/models/list":
            return httpx.Response(200, json=self.models_catalog)

        if url_path == "/api/models/loaded":
            return httpx.Response(200, json=self.loaded_models)

        if url_path == "/api/models/config/get":
            model_id = request.url.params.get("modelId")
            if model_id in self.profiles:
                return httpx.Response(200, json=self.profiles[model_id])
            return httpx.Response(404, json={"error": f"Model {model_id} not found"})

        if url_path == "/api/models/load" and method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            model_id = body.get("modelId")
            self.load_calls.append(body)
            # Add to loaded models
            self.loaded_models = [m for m in self.loaded_models if m.get("modelId") != model_id]
            self.loaded_models.append({"modelId": model_id, "status": "loaded", "port": 8082})
            return httpx.Response(200, json={"status": "ok", "operationId": "op-load-1"})

        if url_path == "/api/models/stop" and method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            model_id = body.get("modelId")
            self.stopped_models.append(model_id)
            self.loaded_models = [m for m in self.loaded_models if m.get("modelId") != model_id]
            return httpx.Response(200, json={"status": "ok", "operationId": "op-stop-1"})

        if url_path == "/v1/models":
            data = [{"id": m.get("modelId") or m.get("id"), "object": "model"} for m in self.loaded_models]
            return httpx.Response(200, json={"data": data})

        if url_path == "/v1/chat/completions" and method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            messages = body.get("messages", [])
            last_msg = messages[-1]["content"] if messages else ""

            # Prepare streaming SSE tokens
            if "络合" in last_msg:
                tokens = ["络合", "反应", "是", "中心", "原子", "与", "配体", "结合", "的过程。"]
            elif "你好" in last_msg:
                tokens = ["你好", "！", "我是", "你的", "本地", "语音", "助手。"]
            else:
                tokens = ["收到", "：", last_msg]

            async def sse_generator():
                for t in tokens:
                    chunk = {
                        "choices": [
                            {"delta": {"content": t}, "index": 0, "finish_reason": None}
                        ]
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
                    await asyncio.sleep(0.01)
                yield b"data: [DONE]\n\n"

            return httpx.Response(200, content=sse_generator(), headers={"Content-Type": "text/event-stream"})

        return httpx.Response(404, json={"error": f"Path {url_path} not found"})


@pytest.mark.asyncio
async def test_e2e_multi_turn_hub_streaming():
    """Verify multi-turn conversation flow with Hub streaming inference."""
    mock_transport = MockHubTransport()
    inference = LlamaCppHubInferenceClient(
        base_url="http://127.0.0.1:8080",
        transport=mock_transport,
    )
    control = LlamaCppHubControlClient(
        base_url="http://127.0.0.1:8080",
        transport=mock_transport,
    )
    repo = JournalRepository()
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)

    # Turn 1: "你好"
    rt.session_controller.start_session()
    session_id = rt.session_controller.current_session_id
    turn_1 = rt.turn_controller.create_turn(session_id, user_text="你好")
    epoch = rt.interrupt_controller.provider_epoch

    assert rt.stale_gate.check_gate1_pre_dispatch(turn_1, epoch) is True

    turn_1_tokens: list[str] = []
    async for chunk in inference.stream_chat([{"role": "user", "content": "你好"}], turn_1, epoch):
        if not rt.stale_gate.check_gate2_in_stream(turn_1, epoch):
            break
        turn_1_tokens.append(chunk)

    reply_1 = "".join(turn_1_tokens)
    assert reply_1 == "你好！我是你的本地语音助手。"

    if rt.stale_gate.check_gate3_pre_side_effect(turn_1, epoch, "journal_commit"):
        repo.append_event(
            event_id=uuid4(),
            raw_text="你好",
            session_id=session_id,
            turn_sequence=turn_1.sequence,
            speaker="user",
        )
        repo.append_event(
            event_id=uuid4(),
            raw_text=reply_1,
            session_id=session_id,
            turn_sequence=turn_1.sequence,
            speaker="agent",
        )
        rt.turn_controller.complete_turn(turn_1)

    # Turn 2: "什么是络合反应"
    turn_2 = rt.turn_controller.create_turn(session_id, user_text="什么是络合反应")
    assert turn_2.sequence == 2

    turn_2_tokens: list[str] = []
    async for chunk in inference.stream_chat([{"role": "user", "content": "什么是络合反应"}], turn_2, epoch):
        if not rt.stale_gate.check_gate2_in_stream(turn_2, epoch):
            break
        turn_2_tokens.append(chunk)

    reply_2 = "".join(turn_2_tokens)
    assert reply_2 == "络合反应是中心原子与配体结合的过程。"

    if rt.stale_gate.check_gate3_pre_side_effect(turn_2, epoch, "journal_commit"):
        repo.append_event(
            event_id=uuid4(),
            raw_text="什么是络合反应",
            session_id=session_id,
            turn_sequence=turn_2.sequence,
            speaker="user",
        )
        repo.append_event(
            event_id=uuid4(),
            raw_text=reply_2,
            session_id=session_id,
            turn_sequence=turn_2.sequence,
            speaker="agent",
        )
        rt.turn_controller.complete_turn(turn_2)

    # Verify Journal v2 records
    hits = repo.search("络合反应")
    assert len(hits) >= 1
    assert any("中心原子" in h["current_text"] for h in hits)


@pytest.mark.asyncio
async def test_e2e_turn_interrupt_stale_suppression():
    """Verify barge-in / interrupt mid-stream: late tokens are dropped and uncommitted."""
    mock_transport = MockHubTransport()
    inference = LlamaCppHubInferenceClient(
        base_url="http://127.0.0.1:8080",
        transport=mock_transport,
    )
    repo = JournalRepository()
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)

    rt.session_controller.start_session()
    session_id = rt.session_controller.current_session_id
    turn_1 = rt.turn_controller.create_turn(session_id, user_text="详细解释络合反应")
    epoch_1 = rt.interrupt_controller.provider_epoch

    collected_tokens: list[str] = []
    dropped_after_interrupt = 0
    interrupted = False

    async for chunk in inference.stream_chat([{"role": "user", "content": "详细解释络合反应"}], turn_1, epoch_1):
        if len(collected_tokens) == 2 and not interrupted:
            # User barge-in occurs! Commit interrupt and bump epoch
            rt.interrupt_controller.commit_interrupt(reason="user_barge_in")
            interrupted = True

        # In-stream gate check
        if not rt.stale_gate.check_gate2_in_stream(turn_1, epoch_1):
            dropped_after_interrupt += 1
            continue
        collected_tokens.append(chunk)

    # Only 2 tokens collected before interrupt
    assert len(collected_tokens) == 2
    assert dropped_after_interrupt > 0

    # Gate 3 must strictly reject committing interrupted turn_1
    can_commit = rt.stale_gate.check_gate3_pre_side_effect(turn_1, epoch_1, "journal_commit")
    assert can_commit is False

    # Turn 2 can proceed cleanly on new epoch
    epoch_2 = rt.interrupt_controller.provider_epoch
    assert epoch_2 == epoch_1 + 1
    turn_2 = rt.turn_controller.create_turn(session_id, user_text="等一下，说简单点")
    assert turn_2.sequence == 2

    turn_2_tokens: list[str] = []
    async for chunk in inference.stream_chat([{"role": "user", "content": "等一下，说简单点"}], turn_2, epoch_2):
        if not rt.stale_gate.check_gate2_in_stream(turn_2, epoch_2):
            break
        turn_2_tokens.append(chunk)

    assert len(turn_2_tokens) > 0
    assert rt.stale_gate.check_gate3_pre_side_effect(turn_2, epoch_2, "journal_commit") is True


@pytest.mark.asyncio
async def test_hub_model_switch_saga_integration():
    """Verify HubRuntimeSaga model switch with profile loading and conflict handling."""
    mock_transport = MockHubTransport()
    control = LlamaCppHubControlClient(
        base_url="http://127.0.0.1:8080",
        transport=mock_transport,
    )
    inference = LlamaCppHubInferenceClient(
        base_url="http://127.0.0.1:8080",
        transport=mock_transport,
    )
    rt = RuntimeController()

    saga = HubRuntimeSaga(
        control_client=control,
        inference_client=inference,
        on_binding_changed=rt.set_hub_binding,
        on_interrupt=lambda reason: rt.interrupt_controller.commit_interrupt(reason=reason),
    )

    # Initially bound to spark-4b (loaded by lva)
    saga.binding.active_model_id = "spark-4b"
    saga.binding.load_origin = "loaded_by_lva"
    initial_epoch = rt.interrupt_controller.provider_epoch

    # Switch model to qwen2.5-7b
    new_binding = await saga.switch_model("qwen2.5-7b")

    # Verifications:
    # 1. Old model spark-4b was stopped
    assert "spark-4b" in mock_transport.stopped_models
    # 2. Target model was loaded with profile
    assert len(mock_transport.load_calls) == 1
    assert mock_transport.load_calls[0]["modelId"] == "qwen2.5-7b"
    assert mock_transport.load_calls[0]["cmd"] == "--ctx-size 4096 -ngl 33"
    # 3. Binding committed and verified
    assert new_binding.status == "ready"
    assert new_binding.active_model_id == "qwen2.5-7b"
    assert new_binding.load_origin == "loaded_by_lva"
    # 4. Provider epoch was incremented
    assert rt.interrupt_controller.provider_epoch == initial_epoch + 1
    # 5. Core state reflects new hub binding
    assert rt.get_state().hub_binding.active_model_id == "qwen2.5-7b"
