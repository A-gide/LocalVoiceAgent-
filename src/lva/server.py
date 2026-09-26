"""HTTP + WebSocket surface for the assistant.

Loopback only. Every route is bound to 127.0.0.1 explicitly and the server is
started with that host, so nothing here is reachable from the network.
"""
from __future__ import annotations

import asyncio
import collections
import io
import json
import logging
import time
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

import numpy as np
from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import asr as ASR
from . import audio as A
from . import config as C
from . import llm as LLM
from . import memory as MEM
from . import pipeline as PL
from . import textutil as TX
from . import tts as TTS
from . import vocab as VO
from .contracts.commands import (
    CommandEnvelope,
    CommandResult,
    RuntimeSetModePayload,
    TurnCancelPayload,
    TurnSendTextPayload,
)
from .contracts.enums import ErrorCode, Mode, PrivacyScope
from .contracts.errors import ErrorEnvelope
from .contracts.events import EventEnvelope, RuntimeSnapshotPayload
from .core.runtime import RuntimeController
from .core.turn_executor import TurnExecutor
from .journal.repository import JournalRepository
from .providers.registry import ProviderRegistry
from .transport.auth import AuthMiddleware, TokenValidator

log = logging.getLogger("lva.server")

_core: PL.VoiceCore | None = None
_runtime: RuntimeController | None = None
_journal: JournalRepository | None = None
_registry: ProviderRegistry | None = None
_turn_executor: TurnExecutor | None = None
_hub_saga = None
_events: collections.deque = collections.deque(maxlen=400)
_sockets: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


# --------------------------------------------------------------------- events
def _broadcast(event: PL.Event) -> None:
    payload = event.as_dict()
    if event.kind == "transcript" and not C.LOG_TRANSCRIPTS:
        log.info("transcript (%d chars, %s) asr=%.0fms", len(payload.get("text", "")),
                 payload.get("domain"), payload.get("asr_ms", 0))
    else:
        log.info("event %s %s", event.kind, {k: v for k, v in payload.items()
                                             if k not in ("text", "raw", "reply", "hit")})
    _events.append(payload)

    if _loop is None or not _sockets:
        return
    dead = []
    for ws in list(_sockets):
        coro = ws.send_text(json.dumps(payload, ensure_ascii=False))
        try:
            asyncio.run_coroutine_threadsafe(coro, _loop)
        except Exception:  # noqa: BLE001
            # Scheduling failed, so the coroutine is never awaited; close it or
            # Python reports "coroutine was never awaited" at GC time.
            coro.close()
            dead.append(ws)
    for ws in dead:
        _sockets.discard(ws)


def _broadcast_ipc_event(env: EventEnvelope) -> None:
    data = env.model_dump(mode="json")
    _events.append(data)
    if _loop is None or not _sockets:
        return
    dead = []
    text = json.dumps(data, ensure_ascii=False)
    for ws in list(_sockets):
        coro = ws.send_text(text)
        try:
            asyncio.run_coroutine_threadsafe(coro, _loop)
        except Exception:
            coro.close()
            dead.append(ws)
    for ws in dead:
        _sockets.discard(ws)


def get_journal() -> JournalRepository:
    global _journal
    if _journal is None:
        _journal = JournalRepository(C.DATA / "journal.sqlite3")
    return _journal


def get_registry() -> ProviderRegistry:
    """The provider registry, populated from the concrete clients (PR-011).

    This is the wiring point the slice was missing: `ProviderRegistry` existed but
    only tests ever constructed it, so the registry was dead code in production.
    The adapters wrap the clients that already exist; nothing is reimplemented.
    """
    global _registry
    if _registry is None:
        from .providers.adapters import ASREngineAdapter, LLMStreamAdapter, TTSEngineAdapter
        from .providers.registry import ProviderRegistry

        _registry = ProviderRegistry(get_current_mode=lambda: get_runtime().mode)
        c = core()
        _registry.register_asr(ASREngineAdapter(c.load_asr(), c.asr_name), make_active=True)
        _registry.register_llm(LLMStreamAdapter(), make_active=True)
        if c.tts is not None:
            _registry.register_tts(
                TTSEngineAdapter(c.tts, getattr(c.tts, "name", None)), make_active=True
            )
        # Publish the registry's view of provider state into RuntimeState so UI and
        # Core observe the same typed status (PR-011 capability/state registry).
        rt = get_runtime()
        for provider_id, status in _registry.provider_statuses().items():
            rt.set_provider_status(provider_id, status)
    return _registry


def get_turn_executor() -> TurnExecutor:
    """Build (once) the Core-owned turn executor.

    PR-010 remainder: the orchestration that used to sit in the ``/api/ask`` route
    body lives in ``core/turn_executor.py``.  Core must not import the concrete
    clients, so the owner supplies them here as narrow callables -- the same
    injection shape the provider registry uses.
    """
    global _turn_executor
    if _turn_executor is None:
        from .core.turn_executor import TurnExecutor

        c = core()

        def _synthesize(text: str):
            engine = c.tts
            if engine is None:
                raise RuntimeError("no TTS engine loaded")
            return engine.synthesize(text)

        _turn_executor = TurnExecutor(
            runtime=get_runtime(),
            journal=get_journal(),
            correct_text=lambda text, domain: c.vocab.correct(text, domain=domain),
            build_messages=lambda corrected, block: c._prompt_messages(corrected, block),
            # F-005: inference must follow the *committed* Hub binding, not the
            # configured default.  A switch that commits a binding but leaves the
            # request on the configured model answers from the wrong model, which
            # is exactly the reproduced defect.  `bound_inference_model()` returns
            # None when nothing is bound, so a non-Hub turn keeps the default.
            stream_reply=lambda messages, mode: LLM.stream(
                messages, mode=mode, model=get_runtime().bound_inference_model()
            ),
            synthesize=_synthesize if c.tts is not None else None,
            to_wav_hex=lambda syn: A.to_wav_bytes(syn.samples, syn.sample_rate).hex(),
            strip_for_speech=TX.strip_for_speech,
            deep_hints=PL.DEEP_HINTS,
        )
        # Hand it to the runtime so any Core-side caller can reach the same executor.
        rt = get_runtime()
        rt.turn_executor = _turn_executor

        # T04: a typed `turn.send_text` must actually execute.  The dispatcher
        # calls this runner; it records the reply on the runtime first so the
        # `turn.completed` event carries the text.  `/api/ask` suppresses this and
        # runs the executor itself (with domain/speak).
        def _default_turn_runner(text: str, _turn) -> None:
            outcome = _turn_executor.run_text_turn(text)
            rt.reply_text = outcome.reply

        rt.turn_runner = _default_turn_runner
    return _turn_executor


def get_hub_saga() -> "HubRuntimeSaga":
    """Build (once) the Hub binding/lifecycle saga (PR-014 hook).

    PR-012/PR-014: the saga already exists in ``providers/hub_runtime.py`` but had
    no runtime origin -- nothing constructed it, so Hub control could never run.
    It is wired here, and the Core gate (``hub_control_allowed``) decides whether a
    Hub control command is allowed to reach it: only a **fresh
    VERIFIED_LOOPBACK** attestation permits control (plan L665).
    """
    global _hub_saga
    if _hub_saga is None:
        from .providers.hub_control import LlamaCppHubControlClient
        from .providers.hub_inference import LlamaCppHubInferenceClient
        from .providers.hub_runtime import HubRuntimeSaga

        base_url = C.hub_base_url()
        # The real Hub ships with `security.apiKeyEnabled: true`, so the clients
        # must carry the key or every management request 401s.  The key lives in
        # memory only -- never logged, never written to disk.
        hub_api_key = getattr(C, "HUB_API_KEY", "") or C.LLM_API_KEY
        # NOTE: the callbacks are resolved lazily.  ``get_runtime()`` constructs the
        # saga, so calling ``get_runtime()`` here would recurse infinitely; the
        # lambdas below only run when the saga actually fires them.
        _hub_saga = HubRuntimeSaga(
            control_client=LlamaCppHubControlClient(base_url=base_url, api_key=hub_api_key),
            inference_client=LlamaCppHubInferenceClient(base_url=base_url, api_key=hub_api_key),
            on_binding_changed=lambda binding: get_runtime().set_hub_binding(binding),
            on_interrupt=lambda reason: get_runtime().interrupt_controller.commit_interrupt(reason=reason),
            # PR-026: the Conversation Model UI shows operation progress, and
            # `hub.operation_progress` had no producer.  The Core is the only
            # event emitter, so the saga reports and the owner publishes.
            on_operation_progress=lambda model_id, percent, message: get_runtime().publish_hub_operation_progress(
                model_id, percent, message
            ),
        )
    return _hub_saga


def get_runtime() -> RuntimeController:
    global _runtime
    if _runtime is None:
        # PR-008 / B18: adopt the instance id already announced in LVA_READY so the
        # bridge sees one identity for the whole Core lifetime.  Outside bootstrap
        # mode nothing was announced and RuntimeController mints its own id.
        from .bootstrap import get_announced_runtime_instance_id

        _runtime = RuntimeController(
            event_broadcaster=_broadcast_ipc_event,
            journal=get_journal(),
            runtime_instance_id=get_announced_runtime_instance_id(),
            on_interrupt_action=_abort_playback,
            on_mode_changed=_sync_legacy_mode,
            hub_saga=get_hub_saga(),
            on_playback_mute=_set_playback_muted,
        )
        # PR-020/L1335: the Core mic stop must be a *physical* stop, so the
        # coordinator drives the real device instead of flipping its own flag.
        # The device belongs to the legacy pipeline until PR-037, and the owner
        # injects it here -- Core keeps no audio-device reference of its own.
        _runtime.capture_coordinator.on_stop_mic = _stop_core_mic_device
        _runtime.capture_coordinator.on_start_mic = _start_core_mic_device
        # T03: bind the legacy turn's side effects (history, legacy Memory) to the
        # Core turn identity.  The pipeline writes those sinks *after* streaming,
        # and previously only the stream producer was checked, so a cancelled
        # reply still reached them.  Injecting the Core gate closes that path
        # without rewriting the pipeline: the check happens at the point of write.
        # Resolved lazily -- calling ``core()`` here would construct the ASR/TTS
        # stack on every runtime creation, including the forbidden-mode paths that
        # must reject *before* the core is loaded (I07/I08).
        def _bind_effect_hooks(_core: PL.VoiceCore) -> None:
            _core.core_effect_epoch = lambda: _runtime.interrupt_controller.provider_epoch
            _core.core_effect_gate = lambda epoch: _runtime.effect_gate_allows(epoch)
            _core.bound_inference_model = lambda: _runtime.bound_inference_model()

        _runtime.effect_hook_binder = _bind_effect_hooks
        # The pipeline may already have been constructed (its `core()` is called
        # first in the lifespan), so apply the binder to the existing instance as
        # well as to any built later.
        if _core is not None:
            _bind_effect_hooks(_core)
    return _runtime


def _stop_core_mic_device() -> None:
    """Close the real capture stream so no frames can reach VAD/ASR (I09)."""
    mic = getattr(_core, "mic", None) if _core is not None else None
    if mic is None:
        return
    mic.stop()


def _start_core_mic_device() -> None:
    """Open the Core mic when a capture mode is entered (T02).

    Startup leaves the devices unopened, so the microphone is created here on the
    first explicit capture transition rather than at boot.  A later transition
    (Standby -> Live) finds the device already created and only restarts it.
    """
    if _core is None:
        return
    if not getattr(_core, "_devices_open", False):
        _core.ensure_devices()
        return
    mic = getattr(_core, "mic", None)
    if mic is not None:
        mic.start()


def _sync_legacy_mode(new_mode: Mode) -> None:
    """Mirror a Core mode change onto the legacy `VoiceCore` mode.

    Compatibility adapter only: the pre-PR-009 shell still owns its own mode
    enum, and the HTTP route must not be the thing that mutates it (I22).  This
    adapter disappears with the legacy mode under PR-037.
    """
    if _core is None:
        return
    if new_mode == Mode.LIVE:
        _core.set_mode(PL.Mode.LIVE)
    elif new_mode == Mode.PASSIVE:
        _core.set_mode(PL.Mode.RECORDING)
    else:
        _core.set_mode(PL.Mode.IDLE)


def _abort_playback(reason: str) -> None:
    """Playback-side abort for every interrupt path (PR-010 / I22).

    ``InterruptController.commit_interrupt`` bumps the Core epoch, moves the floor
    and cancels the turn, but the *audio* stops only when the owner of the player
    flushes it.  This callback is that owner-side action, so a barge-in, a Standby
    transition and a Privacy Pause all silence already-scheduled speech instead of
    letting it run to the end of the sentence.

    ``reason`` selects the abort strength.  A user barge-in keeps the full
    barge-in semantics (generation bump, pre-roll hand-off for the new utterance,
    VAD reset); a mode transition only needs the queue flushed, and must not
    inflate the barge-in counters or seed pre-roll for a turn that is not coming.
    """
    if _core is None:
        return
    try:
        if reason == "manual_barge_in" or reason == "ws_barge_in":
            _core.barge_in()
        else:
            _core.cancel_turn()
    except Exception as exc:  # noqa: BLE001
        log.warning("Playback abort during interrupt failed: %s", exc)


def _set_playback_muted(muted: bool) -> None:
    """Apply Output Mute to the real player (PR-024).

    Core owns the intent and publishes `playback.muted`; the player belongs to the
    legacy pipeline until PR-037, so the owner applies it here -- the same
    injection shape as `_abort_playback` and the capture callbacks.

    The player raises if the device refuses, and the caller turns that into a
    rejected command rather than publishing a mute that did not happen.
    """
    if _core is None:
        return
    player = getattr(_core, "player", None)
    if player is None:
        return
    player.set_muted(muted)


def core() -> PL.VoiceCore:
    global _core
    if _core is None:
        _core = PL.VoiceCore(on_event=_broadcast)
        # The runtime was built first and left a binder for the pipeline's effect
        # hooks (T03); apply it now so the sinks share the Core turn identity.
        binder = getattr(_runtime, "effect_hook_binder", None)
        if binder is not None:
            binder(_core)
    return _core


# ------------------------------------------------------------------ lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _loop
    _loop = asyncio.get_running_loop()
    c = core()
    # T02/I19: start the pipeline but do NOT open the audio devices.  The old boot
    # called the default `start(open_devices=True)`, which immediately created and
    # started the microphone -- capture before any consent.  Devices are opened
    # only when a capture mode is entered (`on_start_mic` -> `ensure_devices`).
    c.start(open_devices=False)
    rt = get_runtime()
    # T02 / I19: startup must not implicitly open the microphone.  The previous
    # boot went straight to Passive *and* set the legacy pipeline to RECORDING,
    # so the app was capturing reality the moment it launched -- before the user
    # had consented to anything.  The safe initial state is Standby: AI idle and
    # all LVA-managed capture off.  A mode only moves when a caller explicitly
    # asks for it (`runtime.set_mode`), which is where the capture intent lives.
    rt.set_mode(Mode.STANDBY)
    c.set_mode(PL.Mode.IDLE)
    # The Core mic device is not started here: it starts only when a mode that
    # needs audio is entered (`runtime.set_mode` -> `start_core_mic`).
    log.info("LVA Core ready: asr=%s tts=%s mic=%s out=%s", c.asr_name,
             getattr(c.tts, "name", "none"), getattr(c.mic, "device_name", ""),
             getattr(c.player, "device_name", ""))
    try:
        yield
    finally:
        if _core is not None:
            _core.stop()


app = FastAPI(title="LocalVoiceAgent", version="1.0", lifespan=lifespan)

# Auth validator
auth_validator = TokenValidator()
app.add_middleware(AuthMiddleware, validator=auth_validator)


# ---------------------------------------------------------------------- views
@app.get("/health")
async def health() -> JSONResponse:
    c = core()
    llm = LLM.health()
    ok = bool(llm.get("ok"))
    rt = get_runtime()
    return JSONResponse({
        "ok": ok,
        "mode": rt.mode.value,
        "muted": c.muted,
        "aec": {"enabled": c.aec is not None,
                "converged": bool(c.aec is not None and c.aec.converged),
                "delay_ms": C.ECHO_DELAY_MS if c.aec else None},
        "asr": {"engine": c.asr_name, "loaded": list(c._asr)},
        "tts": getattr(c.tts, "name", "none"),
        "llm": llm,
        "mic": getattr(c.mic, "device_name", None),
        "speaker": getattr(c.player, "device_name", None),
        "memory": c.memory.stats(),
        "stats": c.stats,
        "ts": time.time(),
    }, status_code=200 if ok else 503)


@app.get("/api/state")
async def state() -> dict:
    c = core()
    rt = get_runtime()
    return {
        "mode": rt.mode.value,
        "asr": c.asr_name,
        "tts": getattr(c.tts, "name", "none"),
        "llm_model": C.LLM_MODEL,
        "stats": c.stats,
        "domain": c.session_domain or "auto",
        "muted": c.muted,
        "last_turn": c.last_turn.as_dict() if c.last_turn else None,
        "vad_silence_s": c.vad.min_silence,
        "memory": c.memory.stats(),
        "runtime_state": rt.get_state().model_dump(mode="json"),
    }


class ModeBody(BaseModel):
    mode: str


@app.post("/api/mode")
async def set_mode(body: ModeBody) -> dict:
    """Mode switch adapted into a command (I22 / PR-010).

    The runtime transition itself goes through ``runtime.set_mode``; the legacy
    ``PL.VoiceCore`` mode is mirrored afterwards as a compatibility adapter.
    """
    rt = get_runtime()
    try:
        target_mode = Mode(body.mode.lower())
    except ValueError as e:
        raise HTTPException(400, f"unknown mode {body.mode!r}") from e

    res = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode=target_mode),
        )
    )
    if res.status != "applied":
        err = res.error or ErrorEnvelope(
            code=ErrorCode.INVALID_TRANSITION,
            message=f"mode transition to {target_mode.value} was rejected",
            severity="error",
            component="core.runtime",
            correlation_id=uuid4(),
        )
        raise HTTPException(status_code=409, detail=err.model_dump(mode="json"))

    # The legacy `VoiceCore` mode mirror is synced by the Core's on_mode_changed
    # adapter, so this route no longer mutates it directly (I22).
    return {"mode": rt.mode.value}


class DomainBody(BaseModel):
    domain: str | None = None


@app.post("/api/domain")
async def set_domain(body: DomainBody) -> dict:
    try:
        d = core().set_domain(body.domain)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"domain": d or "auto",
            "hotwords": len(core().hotwords() or []),
            "asr_supports_hotwords": core().load_asr().supports_hotwords}


class AskBody(BaseModel):
    text: str
    domain: str | None = None
    speak: bool = False


@app.post("/api/ask")
async def ask(body: AskBody) -> dict:
    """Text turn: a thin transport adapter over the Core dispatcher and executor.

    I22 / PR-010: the turn is opened through the command dispatcher
    (``turn.send_text``) and executed by the Core-owned ``TurnExecutor``.  This
    route performs no provider, playback or Journal work of its own -- it only
    translates HTTP into a command, delegates, and serializes the outcome.
    """
    rt = get_runtime()

    # I22: the mode guard, session creation and turn allocation are the dispatcher's
    # responsibility, not this route's.  Rejected before any model or Journal work
    # so a forbidden mode cannot warm up the ASR/TTS stack or open a Journal
    # connection as a side effect (plan L311/L318).
    # The route owns the richer execution below (domain + speak), so it suppresses
    # the dispatcher's default runner for this one turn (T04).
    rt.turn_runner_suppressed = True
    try:
        opened = rt.execute_command(
            CommandEnvelope(
                type="turn.send_text",
                payload=TurnSendTextPayload(type="turn.send_text", text=body.text),
            )
        )
    finally:
        rt.turn_runner_suppressed = False
    if opened.status != "applied":
        err = opened.error or ErrorEnvelope(
            code=ErrorCode.PASSIVE_PROVIDER_FORBIDDEN,
            message=f"LLM turn scheduling is forbidden in {rt.mode.value} mode",
            severity="error",
            component="core.turn",
            correlation_id=uuid4(),
        )
        raise HTTPException(status_code=403, detail=err.model_dump(mode="json"))

    executor = get_turn_executor()
    outcome = executor.run_text_turn(body.text, domain=body.domain, speak=body.speak)
    if outcome.failed:
        raise HTTPException(503, f"LLM unavailable: {outcome.failed}")

    return {
        "raw": outcome.raw_text,
        "text": outcome.corrected_text,
        "applied": outcome.applied,
        "domain": outcome.domain,
        "hits": outcome.hits,
        "reply": outcome.reply,
        "llm_mode": outcome.llm_mode,
        "ttft_ms": round(outcome.ttft_ms, 1) if outcome.ttft_ms else None,
        "total_ms": round(outcome.total_ms, 1),
        "tts_ms": round(outcome.tts_ms, 1) if outcome.tts_ms else None,
        "audio_hex": outcome.audio_hex,
        "turn_id": outcome.turn_id.model_dump(mode="json") if outcome.turn_id else None,
        "provider_epoch": outcome.provider_epoch,
    }


@app.post("/api/barge_in")
async def barge_in() -> dict:
    """Barge-in adapted into a command (I22 / PR-010).

    ``turn.cancel`` commits the interrupt transaction: it bumps the Core provider
    epoch, moves the floor to the user, cancels the active turn and -- through the
    ``on_interrupt_action`` callback this Core now supplies -- flushes the player,
    so the audio actually stops.  The legacy ``PL.VoiceCore`` generation bump is
    mirrored afterwards as a compatibility adapter.
    """
    rt = get_runtime()
    c = core()
    res = rt.execute_command(
        CommandEnvelope(
            type="turn.cancel",
            payload=TurnCancelPayload(type="turn.cancel", reason="manual_barge_in"),
        )
    )
    # The playback abort already ran inside the command, via the interrupt action
    # this Core supplies.  Calling `c.barge_in()` here as well would double-count
    # `barge_ins` in the legacy stats and bump the legacy generation twice.
    return {
        "ok": res.status == "applied",
        "provider_epoch": rt.interrupt_controller.provider_epoch,
        "stats": c.stats,
    }


@app.post("/api/command")
async def command_api(cmd: CommandEnvelope) -> dict:
    rt = get_runtime()
    res = rt.execute_command(cmd)
    return res.model_dump(mode="json")


@app.get("/api/memory/stats")
async def memory_stats() -> dict:
    return core().memory.stats()


@app.get("/api/memory/search")
async def memory_search(q: str, limit: int = 10) -> dict:
    journal = get_journal()
    hits = journal.search(q, limit=limit)
    return {"q": q, "n": len(hits), "hits": hits}


@app.get("/api/events")
async def events(since: float = 0.0) -> dict:
    return {"events": [e for e in _events if e.get("ts", 0) > since or e.get("sequence", 0) > since]}


@app.get("/api/devices")
async def devices() -> dict:
    return {"devices": A.list_devices()}


@app.post("/api/asr")
async def asr_upload(file: UploadFile) -> dict:
    data = await file.read()
    try:
        with wave.open(io.BytesIO(data)) as w:
            sr = w.getframerate()
            ch = w.getnchannels()
            raw = w.readframes(w.getnframes())
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            x = x.reshape(-1, ch).mean(axis=1)
        if sr != C.ASR_RATE:
            x = A.resample(x, sr, C.ASR_RATE)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"expected a 16-bit PCM wav: {e}") from e
    c = core()
    t0 = time.perf_counter()
    res = c.load_asr().transcribe(x)
    ms = (time.perf_counter() - t0) * 1000
    corrected = c.vocab.correct(ASR.clean(res.text))
    return {"raw": corrected.raw, "text": corrected.corrected, "domain": corrected.domain,
            "applied": corrected.applied, "flagged": corrected.flagged,
            "asr_ms": round(ms, 1), "audio_s": round(len(x) / C.ASR_RATE, 2)}


class TtsBody(BaseModel):
    text: str


@app.post("/api/tts")
async def tts_say(body: TtsBody) -> Response:
    rt = get_runtime()

    # Guard: TTS scheduling is forbidden outside Live mode (I07/I08 & Part 3.3).
    # Rejected before the engine is loaded, so a forbidden mode cannot bring the
    # TTS stack up as a side effect (plan L311/L318).
    if rt.mode != Mode.LIVE:
        err = ErrorEnvelope(
            code=ErrorCode.PASSIVE_PROVIDER_FORBIDDEN,
            message=f"TTS scheduling is forbidden in {rt.mode.value} mode",
            severity="error",
            component="core.tts",
            correlation_id=uuid4(),
        )
        raise HTTPException(status_code=403, detail=err.model_dump(mode="json"))

    c = core()
    if c.tts is None:
        raise HTTPException(503, "no TTS engine loaded")
    spoken = TX.strip_for_speech(body.text)
    t0 = time.perf_counter()
    syn = c.tts.synthesize(spoken)
    ms = (time.perf_counter() - t0) * 1000
    wav = A.to_wav_bytes(syn.samples, syn.sample_rate)
    return Response(content=wav, media_type="audio/wav",
                    headers={"X-TTFA-Ms": f"{syn.ttfa_ms:.0f}",
                             "X-Gen-Ms": f"{ms:.0f}",
                             "X-Audio-S": f"{syn.audio_s:.2f}",
                             "X-Spoken-Text": spoken[:200].encode("utf-8").decode("latin-1", "ignore")})


# ---------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    # Private entry point: the bearer token travels only in the Authorization
    # header (never a query string) and the native-bridge Origin is checked as
    # well (v1.2.1 PR-006).
    auth_header = sock.headers.get("Authorization")
    token = auth_header[7:].strip() if auth_header and auth_header.startswith("Bearer ") else None
    if not auth_validator.verify_origin(sock.headers.get("Origin")):
        await sock.close(code=4403, reason="Forbidden: invalid or missing token")
        return
    if not auth_validator.verify_token(token):
        await sock.close(code=4403, reason="Forbidden: invalid or missing token")
        return

    await sock.accept()
    _sockets.add(sock)
    c = core()
    rt = get_runtime()
    await sock.send_text(json.dumps(
        {"kind": "hello", "state": rt.get_state().model_dump(mode="json")},
        ensure_ascii=False))
    try:
        while True:
            raw = await sock.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Handle typed CommandEnvelope
            if "type" in msg and ("command_id" in msg or "payload" in msg):
                try:
                    cmd = CommandEnvelope.model_validate(msg)
                    res = rt.execute_command(cmd)
                    await sock.send_text(json.dumps({
                        "kind": "command_result",
                        **res.model_dump(mode="json")
                    }, ensure_ascii=False))
                    continue
                except Exception as exc:
                    log.warning("Failed to parse CommandEnvelope: %s", exc)

            kind = msg.get("type")
            if kind == "mode":
                target = Mode(msg.get("mode", "standby").lower())
                # I22 / PR-010: legacy WS is an adapter, so it dispatches the same
                # command the typed path uses instead of mutating runtime state.
                rt.execute_command(
                    CommandEnvelope(
                        type="runtime.set_mode",
                        payload=RuntimeSetModePayload(type="runtime.set_mode", mode=target),
                    )
                )
            elif kind == "barge_in":
                rt.execute_command(
                    CommandEnvelope(
                        type="turn.cancel",
                        payload=TurnCancelPayload(type="turn.cancel", reason="ws_barge_in"),
                    )
                )
            elif kind == "ask":
                body = {"text": msg.get("text", ""), "speak": bool(msg.get("speak"))}
                asyncio.create_task(_ws_ask(sock, body))
            elif kind == "ping":
                await sock.send_text(json.dumps({"kind": "pong", "ts": time.time()}))
    except WebSocketDisconnect:
        pass
    finally:
        _sockets.discard(sock)


async def _ws_ask(sock: WebSocket, body: dict) -> None:
    try:
        result = await ask(AskBody(**body))
    except HTTPException as e:
        result = {"error": str(e.detail)}
    await sock.send_text(json.dumps({"kind": "ask_result", **result}, ensure_ascii=False))


# -------------------------------------------------------------- static files
WEB = C.ROOT / "web"


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    p = WEB / "index.html"
    if not p.exists():
        return HTMLResponse("<h1>LocalVoiceAgent</h1><p>web/index.html missing</p>")
    return HTMLResponse(p.read_text(encoding="utf-8"))


if WEB.exists():
    app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
