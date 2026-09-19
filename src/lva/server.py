"""HTTP + WebSocket surface for the assistant.

Loopback only.  Every route is bound to 127.0.0.1 explicitly and the server is
started with that host, so nothing here is reachable from the network.

Routes
------
GET  /                          the desktop-pet UI
GET  /health                    component health (used by scripts/health-check.ps1)
GET  /api/state                 mode, engines, counters
POST /api/mode                  {"mode": "idle"|"recording"|"live"}
POST /api/ask                   text-only turn, used by tests and the text box
POST /api/barge_in              stop speaking immediately
GET  /api/memory/stats          archive statistics
GET  /api/memory/search?q=...   full-text search over the archive
GET  /api/events?since=...      recent event log for the UI
GET  /api/devices               audio device inventory
POST /api/asr                   wav upload -> raw + corrected transcript
POST /api/tts                   text -> wav (TTS smoke test)
POST /api/second_pass           re-transcribe one archived clip with the heavy engine
WS   /ws                        event stream + control messages
"""
from __future__ import annotations

import asyncio
import collections
import io
import json
import logging
import time
import wave
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
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

log = logging.getLogger("lva.server")

app = FastAPI(title="LocalVoiceAgent", version="1.0")

_core: PL.VoiceCore | None = None
_events: collections.deque = collections.deque(maxlen=400)
_sockets: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


# --------------------------------------------------------------------- events
def _broadcast(event: PL.Event) -> None:
    payload = event.as_dict()
    if event.kind == "transcript" and not C.LOG_TRANSCRIPTS:
        # Logs stay free of private speech; the UI still gets the live text.
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
        try:
            asyncio.run_coroutine_threadsafe(ws.send_text(json.dumps(payload, ensure_ascii=False)),
                                             _loop)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        _sockets.discard(ws)


def core() -> PL.VoiceCore:
    global _core
    if _core is None:
        _core = PL.VoiceCore(on_event=_broadcast)
    return _core


# ------------------------------------------------------------------ lifecycle
@app.on_event("startup")
async def _startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    c = core()
    c.start()
    log.info("voice core ready: asr=%s tts=%s mic=%s out=%s", c.asr_name,
             getattr(c.tts, "name", "none"), getattr(c.mic, "device_name", ""),
             getattr(c.player, "device_name", ""))
    c.set_mode(PL.Mode.RECORDING)      # passive capture is the safe default


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _core is not None:
        _core.stop()


# ---------------------------------------------------------------------- views
@app.get("/health")
async def health() -> JSONResponse:
    c = core()
    llm = LLM.health()
    ok = bool(llm.get("ok"))
    return JSONResponse({
        "ok": ok,
        "mode": c.mode.value,
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
    return {"mode": c.mode.value, "asr": c.asr_name,
            "tts": getattr(c.tts, "name", "none"),
            "llm_model": C.LLM_MODEL, "stats": c.stats,
            "domain": c.session_domain or "auto",
            "muted": c.muted,
            "last_turn": c.last_turn.as_dict() if c.last_turn else None,
            "vad_silence_s": c.vad.min_silence,
            "memory": c.memory.stats()}


class ModeBody(BaseModel):
    mode: str


@app.post("/api/mode")
async def set_mode(body: ModeBody) -> dict:
    try:
        mode = core().set_mode(body.mode)
    except ValueError as e:
        raise HTTPException(400, f"unknown mode {body.mode!r}") from e
    return {"mode": mode.value}


class DomainBody(BaseModel):
    domain: str | None = None


@app.post("/api/domain")
async def set_domain(body: DomainBody) -> dict:
    """Pin the subject area (chemistry / physics / biology), or clear it."""
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
    """Text turn: same correction, routing and latency path as speech."""
    c = core()
    corrected = c.vocab.correct(body.text, domain=body.domain)
    t0 = time.perf_counter()
    hq = MEM.parse_history_query(corrected.corrected)
    hits = MEM.search_history(c.memory, hq) if hq else []
    block = MEM.format_history_context(hits)
    msgs = c._prompt_messages(corrected, block)
    llm_mode = "deep" if any(k in corrected.corrected for k in PL.DEEP_HINTS) else "fast"
    ttft = None
    parts: list[str] = []
    try:
        for piece in LLM.stream(msgs, mode=llm_mode):
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            parts.append(piece)
    except LLM.LLMError as e:
        raise HTTPException(503, f"LLM unavailable: {e}") from e
    reply = "".join(parts)
    total = (time.perf_counter() - t0) * 1000

    audio_b64 = None
    tts_ms = None
    if body.speak and c.tts is not None:
        t1 = time.perf_counter()
        syn = c.tts.synthesize(TX.strip_for_speech(reply))
        tts_ms = (time.perf_counter() - t1) * 1000
        audio_b64 = A.to_wav_bytes(syn.samples, syn.sample_rate).hex()

    c.memory.add(raw_text=body.text, fixed_text=corrected.corrected, source="text",
                 domain=corrected.domain)
    return {"raw": corrected.raw, "text": corrected.corrected, "applied": corrected.applied,
            "domain": corrected.domain, "history_query": hq.intent if hq else None,
            "hits": [h.as_dict() for h in hits], "reply": reply, "llm_mode": llm_mode,
            "ttft_ms": round(ttft, 1) if ttft else None, "total_ms": round(total, 1),
            "tts_ms": round(tts_ms, 1) if tts_ms else None,
            "audio_hex": audio_b64}


@app.post("/api/barge_in")
async def barge_in() -> dict:
    c = core()
    c.barge_in()
    return {"ok": True, "stats": c.stats}


@app.get("/api/memory/stats")
async def memory_stats() -> dict:
    return core().memory.stats()


@app.get("/api/memory/search")
async def memory_search(q: str, limit: int = 10) -> dict:
    hits = core().memory.search(q, limit=limit)
    return {"q": q, "n": len(hits), "hits": [h.as_dict() for h in hits]}


@app.get("/api/memory/recent")
async def memory_recent(limit: int = 20) -> dict:
    hits = core().memory.recent(limit=limit)
    return {"n": len(hits), "hits": [h.as_dict() for h in hits]}


@app.get("/api/events")
async def events(since: float = 0.0) -> dict:
    return {"events": [e for e in _events if e.get("ts", 0) > since]}


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


class SecondPassBody(BaseModel):
    utterance_id: int


@app.post("/api/second_pass")
async def second_pass(body: SecondPassBody) -> dict:
    """Re-transcribe one archived clip with the heavier engine, on demand."""
    c = core()
    row = c.memory._db.execute("SELECT * FROM utterances WHERE id=?",
                               (body.utterance_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such utterance")
    if not row["audio_path"] or not Path(row["audio_path"]).exists():
        raise HTTPException(409, "audio for that utterance is not on disk")
    x, sr = A.read_wav(row["audio_path"])
    if sr != C.ASR_RATE:
        x = A.resample(x, sr, C.ASR_RATE)
    engine = c.load_asr(C.SECOND_PASS_ASR)
    t0 = time.perf_counter()
    res = engine.transcribe(x)
    ms = (time.perf_counter() - t0) * 1000
    corrected = c.vocab.correct(ASR.clean(res.text))
    return {"engine": C.SECOND_PASS_ASR, "raw": corrected.raw, "text": corrected.corrected,
            "asr_ms": round(ms, 1), "stored_text": row["fixed_text"],
            "changed": corrected.corrected != row["fixed_text"]}


# ---------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    _sockets.add(sock)
    c = core()
    await sock.send_text(json.dumps(
        {"kind": "hello", "state": {"mode": c.mode.value, "asr": c.asr_name,
                                    "tts": getattr(c.tts, "name", "none")}},
        ensure_ascii=False))
    try:
        while True:
            raw = await sock.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "mode":
                c.set_mode(msg.get("mode", "idle"))
            elif kind == "barge_in":
                c.barge_in()
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
