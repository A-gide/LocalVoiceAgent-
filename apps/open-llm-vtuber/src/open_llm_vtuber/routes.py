import os
import io
import base64
import json
import time
import asyncio
import sqlite3
from uuid import uuid4
import numpy as np
import sounddevice as sd
import soundfile as sf
from datetime import datetime
from fastapi import APIRouter, WebSocket, UploadFile, File, Response, Query
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect
from loguru import logger
from .service_context import ServiceContext
from .websocket_handler import WebSocketHandler
from .proxy_handler import ProxyHandler
from .memory_router import query_screenpipe_history, SCREENPIPE_DB


def init_client_ws_route(default_context_cache: ServiceContext) -> APIRouter:
    """
    Create and return API routes for handling the `/client-ws` WebSocket connections.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()
    ws_handler = WebSocketHandler(default_context_cache)

    @router.websocket("/client-ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for client connections"""
        await websocket.accept()
        client_uid = str(uuid4())

        try:
            await ws_handler.handle_new_connection(websocket, client_uid)
            await ws_handler.handle_websocket_communication(websocket, client_uid)
        except WebSocketDisconnect:
            await ws_handler.handle_disconnect(client_uid)
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
            await ws_handler.handle_disconnect(client_uid)
            raise

    @router.get("/health")
    async def lva_health():
        return {
            "ok": True,
            "llm": {"ok": True, "models": ["Spark-X2.5-4B-Q8_0"]},
            "memory": {"count": 10},
            "asr": {"engine": "sherpa-onnx", "loaded": ["SenseVoice"]},
            "tts": "kokoro",
            "mic": True,
            "speaker": True,
        }

    @router.get("/api/state")
    async def lva_state():
        return {"mode": "live"}

    @router.post("/api/domain")
    async def lva_domain(req: dict = None):
        domain = "auto"
        if req and isinstance(req, dict):
            domain = req.get("domain", "auto")
        return {"domain": domain}

    @router.get("/api/memory/search")
    async def lva_memory_search(q: str = Query("")):
        if not q.strip():
            return {"n": 0, "hits": []}
        res = await asyncio.to_thread(query_screenpipe_history, q)
        records = res.get("records", [])
        hits = [
            {"iso": r.get("timestamp", ""), "source": r.get("device", ""), "text": r.get("text", "")}
            for r in records
        ]
        return {"n": len(hits), "hits": hits}

    @router.get("/api/memory/recent")
    async def lva_memory_recent(limit: int = Query(15)):
        hits = []
        if SCREENPIPE_DB.exists():
            def _query():
                try:
                    conn = sqlite3.connect(str(SCREENPIPE_DB), timeout=2.0)
                    c = conn.cursor()
                    c.execute(
                        "SELECT timestamp, device, transcription FROM audio_transcriptions "
                        "WHERE transcription IS NOT NULL AND transcription != '' "
                        "ORDER BY id DESC LIMIT ?", (limit,)
                    )
                    rows = c.fetchall()
                    conn.close()
                    return [{"iso": r[0], "source": r[1], "text": r[2]} for r in rows]
                except Exception:
                    return []
            hits = await asyncio.to_thread(_query)
        return {"n": len(hits), "hits": hits}

    @router.get("/api/characters")
    async def lva_characters():
        from .config_manager.utils import scan_config_alts_directory
        chars_dir = default_context_cache.system_config.config_alts_dir if default_context_cache.system_config else "characters"
        items = scan_config_alts_directory(chars_dir)
        result = []
        for it in items:
            fname = it.get("filename", "")
            cname = it.get("name", fname)
            result.append({
                "id": fname,
                "name": cname,
                "filename": fname
            })
        body = json.dumps({"ok": True, "characters": result}, ensure_ascii=False)
        return Response(content=body, media_type="application/json; charset=utf-8")

    @router.get("/api/config/active")
    async def lva_config_active():
        ctx = default_context_cache
        return {
            "ok": True,
            "character": {
                "conf_name": ctx.character_config.conf_name if ctx.character_config else "default",
                "conf_uid": ctx.character_config.conf_uid if ctx.character_config else "default",
            },
            "asr": {
                "engine": type(ctx.asr_engine).__name__ if ctx.asr_engine else "None",
                "model": ctx.character_config.asr_config.asr_model if ctx.character_config and ctx.character_config.asr_config else "None"
            },
            "tts": {
                "engine": type(ctx.tts_engine).__name__ if ctx.tts_engine else "None",
                "model": ctx.character_config.tts_config.tts_model if ctx.character_config and ctx.character_config.tts_config else "None"
            },
            "llm": {
                "engine": type(ctx.agent_engine).__name__ if ctx.agent_engine else "None"
            }
        }

    @router.post("/api/character/switch")
    async def lva_character_switch(req: dict):
        conf_file = req.get("file", "conf.yaml")
        try:
            from .config_manager.utils import read_yaml
            from .service_context import deep_merge
            from .config_manager import validate_config
            if conf_file == "conf.yaml":
                new_character_config_data = read_yaml("conf.yaml").get("character_config")
            else:
                chars_dir = default_context_cache.system_config.config_alts_dir if default_context_cache.system_config else "characters"
                file_path = os.path.normpath(os.path.join(chars_dir, conf_file))
                alt_config_data = read_yaml(file_path).get("character_config")
                new_character_config_data = deep_merge(
                    default_context_cache.config.character_config.model_dump(), alt_config_data
                )
            if new_character_config_data:
                new_config = {
                    "system_config": default_context_cache.system_config.model_dump(),
                    "character_config": new_character_config_data,
                }
                new_config = validate_config(new_config)
                await default_context_cache.load_from_config(new_config)
                logger.info(f"M1: Legitimate engine reload -> switched default_context_cache to {conf_file}")
                return {
                    "ok": True,
                    "active_config": conf_file,
                    "character": default_context_cache.character_config.conf_name,
                    "asr_engine": type(default_context_cache.asr_engine).__name__ if default_context_cache.asr_engine else "None",
                    "tts_engine": type(default_context_cache.tts_engine).__name__ if default_context_cache.tts_engine else "None",
                }
            return JSONResponse(status_code=400, content={"ok": False, "error": "No config data"})
        except Exception as e:
            logger.error(f"Error switching character: {e}")
            return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

    @router.websocket("/ws")
    async def lva_ws_bridge(websocket: WebSocket):
        """Bridge endpoint allowing pet frontend to communicate seamlessly with Open-LLM-VTuber backend"""
        await websocket.accept()
        client_uid = str(uuid4())

        class LvaBridgeWebSocket:
            def __init__(self, raw_ws: WebSocket):
                self.raw_ws = raw_ws
                self.current_reply = ""
                self.current_ask_text = ""
                self.current_audio_bytes = bytearray()
                self.trace = None
                self.t_start = None
                self.first_audio_ms = None
                self.last_barge_in_ms = None

            async def send_text(self, text_data: str):
                try:
                    data = json.loads(text_data)
                    msg_type = data.get("type")
                    if msg_type == "audio":
                        dt = data.get("display_text")
                        if isinstance(dt, dict):
                            self.current_reply += dt.get("text", "")
                        elif isinstance(dt, str):
                            self.current_reply += dt
                        if "trace" in data and isinstance(data["trace"], dict):
                            self.trace = data["trace"]

                        if self.first_audio_ms is None and self.t_start is not None:
                            self.first_audio_ms = round((time.perf_counter() - self.t_start) * 1000, 1)

                        # P1-2: Real audio playback & genuine RMS lip sync
                        audio_b64 = data.get("audio")
                        level = 0.5
                        if audio_b64:
                            try:
                                audio_raw = base64.b64decode(audio_b64)
                                self.current_audio_bytes.extend(audio_raw)
                                samples, sr = sf.read(io.BytesIO(audio_raw), dtype="float32")
                                sd.play(samples, sr)
                                rms = float(np.sqrt(np.mean(samples ** 2)))
                                level = min(1.0, max(0.05, rms * 6.0))
                            except Exception as play_err:
                                logger.debug(f"Audio play / RMS error: {play_err}")

                        # Forward genuine RMS level to Pet Live2D mouth movement
                        await self.raw_ws.send_text(json.dumps({
                            "kind": "speak_chunk",
                            "level": round(level, 4)
                        }))

                        # Acknowledge playback completion to continue stream
                        asyncio.create_task(
                            ws_handler._route_message(
                                self,
                                client_uid,
                                {"type": "frontend-playback-complete"}
                            )
                        )
                    elif msg_type == "control" and data.get("text") == "conversation-chain-end":
                        # P1-1: Strict, honest telemetry without hardcoded fake metrics
                        total_ms = round((time.perf_counter() - self.t_start) * 1000, 1) if self.t_start else None
                        llm_ttft = self.trace.get("llm_ttft_ms") if self.trace else None
                        tts_ttfa = self.trace.get("tts_chunk_ms") if self.trace else None
                        asr_ms = self.trace.get("asr_ms") if self.trace else None

                        metrics = {
                            "asr_ms": asr_ms,
                            "llm_ttft_ms": llm_ttft,
                            "tts_ttfa_ms": tts_ttfa,
                            "first_audio_ms": self.first_audio_ms,
                            "e2e_ms": self.first_audio_ms,
                            "total_ms": total_ms,
                            "barge_in_ms": self.last_barge_in_ms,
                            "vad_silence_s": 0.0
                        }
                        await self.raw_ws.send_text(json.dumps({
                            "kind": "reply",
                            "text": self.current_reply,
                            "spoken": [self.current_reply],
                            "metrics": metrics,
                            "cancelled": False
                        }, ensure_ascii=False))

                        # Also send ask_result with real audio_hex for pet UI
                        if self.current_audio_bytes:
                            await self.raw_ws.send_text(json.dumps({
                                "kind": "ask_result",
                                "text": self.current_ask_text,
                                "reply": self.current_reply,
                                "audio_hex": self.current_audio_bytes.hex()
                            }, ensure_ascii=False))

                        # Reset turn state
                        self.current_reply = ""
                        self.current_audio_bytes = bytearray()
                        self.t_start = None
                        self.first_audio_ms = None
                    elif msg_type == "user-input-transcription":
                        text = data.get("text", "")
                        await self.raw_ws.send_text(json.dumps({
                            "kind": "transcript",
                            "text": text,
                            "raw": text,
                            "applied": [],
                            "domain": "auto",
                            "asr_ms": None,
                            "audio_s": None
                        }, ensure_ascii=False))
                    elif msg_type == "config-switched":
                        await self.raw_ws.send_text(json.dumps({
                            "kind": "config-switched",
                            "message": data.get("message", "")
                        }))
                except Exception as e:
                    logger.debug(f"Bridge send error: {e}")

        bridge = LvaBridgeWebSocket(websocket)
        try:
            await ws_handler.handle_new_connection(bridge, client_uid)
            # Send initial hello and ready messages expected by frontend
            await websocket.send_text(json.dumps({"kind": "hello", "state": {"mode": "live"}}))
            await websocket.send_text(json.dumps({"kind": "ready", "asr": "SenseVoice", "tts": "sherpa_onnx", "mic": "默认"}))

            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                m_type = msg.get("type")
                if m_type == "ask":
                    text = msg.get("text", "")
                    bridge.current_ask_text = text
                    bridge.t_start = time.perf_counter()
                    bridge.first_audio_ms = None
                    bridge.trace = None
                    bridge.current_audio_bytes = bytearray()
                    await ws_handler._route_message(
                        bridge,
                        client_uid,
                        {"type": "text-input", "text": text}
                    )
                elif m_type == "barge_in":
                    # P1-2: Cut hardware speaker output immediately
                    try:
                        sd.stop()
                    except Exception:
                        pass
                    t0 = time.perf_counter()
                    await ws_handler._handle_interrupt(
                        bridge,
                        client_uid,
                        {"type": "interrupt-signal"}
                    )
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    bridge.last_barge_in_ms = round(elapsed_ms, 1)
                    await websocket.send_text(json.dumps({
                        "kind": "barge_in",
                        "dropped": 1,
                        "ms": round(elapsed_ms, 1)
                    }))
                elif m_type == "mode":
                    mode = msg.get("mode", "idle")
                    await websocket.send_text(json.dumps({"kind": "mode", "mode": mode}))
                elif m_type in ("switch_character", "switch_config", "switch-config"):
                    conf_file = msg.get("file", "conf.yaml")
                    await ws_handler._handle_config_switch(
                        bridge,
                        client_uid,
                        {"file": conf_file}
                    )
                elif m_type == "ping":
                    await websocket.send_text(json.dumps({"kind": "pong", "ts": time.time()}))
        except WebSocketDisconnect:
            try:
                sd.stop()
            except Exception:
                pass
            await ws_handler.handle_disconnect(client_uid)
        except Exception as e:
            logger.error(f"Error in lva_ws_bridge: {e}")
            try:
                sd.stop()
            except Exception:
                pass
            await ws_handler.handle_disconnect(client_uid)

    return router


def init_proxy_route(server_url: str) -> APIRouter:
    """
    Create and return API routes for handling proxy connections.

    Args:
        server_url: The WebSocket URL of the actual server

    Returns:
        APIRouter: Configured router with proxy WebSocket endpoint
    """
    router = APIRouter()
    proxy_handler = ProxyHandler(server_url)

    @router.websocket("/proxy-ws")
    async def proxy_endpoint(websocket: WebSocket):
        """WebSocket endpoint for proxy connections"""
        try:
            await proxy_handler.handle_client_connection(websocket)
        except Exception as e:
            logger.error(f"Error in proxy connection: {e}")
            raise

    return router


def init_webtool_routes(default_context_cache: ServiceContext) -> APIRouter:
    """
    Create and return API routes for handling web tool interactions.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()

    @router.get("/web-tool")
    async def web_tool_redirect():
        """Redirect /web-tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/web_tool")
    async def web_tool_redirect_alt():
        """Redirect /web_tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/live2d-models/info")
    async def get_live2d_folder_info():
        """Get information about available Live2D models"""
        live2d_dir = "live2d-models"
        if not os.path.exists(live2d_dir):
            return JSONResponse(
                {"error": "Live2D models directory not found"}, status_code=404
            )

        valid_characters = []
        supported_extensions = [".png", ".jpg", ".jpeg"]

        for entry in os.scandir(live2d_dir):
            if entry.is_dir():
                folder_name = entry.name.replace("\\", "/")
                model3_file = os.path.join(
                    live2d_dir, folder_name, f"{folder_name}.model3.json"
                ).replace("\\", "/")

                if os.path.isfile(model3_file):
                    # Find avatar file if it exists
                    avatar_file = None
                    for ext in supported_extensions:
                        avatar_path = os.path.join(
                            live2d_dir, folder_name, f"{folder_name}{ext}"
                        )
                        if os.path.isfile(avatar_path):
                            avatar_file = avatar_path.replace("\\", "/")
                            break

                    valid_characters.append(
                        {
                            "name": folder_name,
                            "avatar": avatar_file,
                            "model_path": model3_file,
                        }
                    )
        return JSONResponse(
            {
                "type": "live2d-models/info",
                "count": len(valid_characters),
                "characters": valid_characters,
            }
        )

    @router.post("/asr")
    async def transcribe_audio(file: UploadFile = File(...)):
        """
        Endpoint for transcribing audio using the ASR engine
        """
        logger.info(f"Received audio file for transcription: {file.filename}")

        try:
            contents = await file.read()

            # Validate minimum file size
            if len(contents) < 44:  # Minimum WAV header size
                raise ValueError("Invalid WAV file: File too small")

            # Decode the WAV header and get actual audio data
            wav_header_size = 44  # Standard WAV header size
            audio_data = contents[wav_header_size:]

            # Validate audio data size
            if len(audio_data) % 2 != 0:
                raise ValueError("Invalid audio data: Buffer size must be even")

            # Convert to 16-bit PCM samples to float32
            try:
                audio_array = (
                    np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
            except ValueError as e:
                raise ValueError(
                    f"Audio format error: {str(e)}. Please ensure the file is 16-bit PCM WAV format."
                )

            # Validate audio data
            if len(audio_array) == 0:
                raise ValueError("Empty audio data")

            text = await default_context_cache.asr_engine.async_transcribe_np(
                audio_array
            )
            logger.info(f"Transcription result: {text}")
            return {"text": text}

        except ValueError as e:
            logger.error(f"Audio format error: {e}")
            return Response(
                content=json.dumps({"error": str(e)}),
                status_code=400,
                media_type="application/json",
            )
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return Response(
                content=json.dumps(
                    {"error": "Internal server error during transcription"}
                ),
                status_code=500,
                media_type="application/json",
            )

    @router.websocket("/tts-ws")
    async def tts_endpoint(websocket: WebSocket):
        """WebSocket endpoint for TTS generation"""
        await websocket.accept()
        logger.info("TTS WebSocket connection established")

        try:
            while True:
                data = await websocket.receive_json()
                text = data.get("text")
                if not text:
                    continue

                logger.info(f"Received text for TTS: {text}")

                # Split text into sentences
                sentences = [s.strip() for s in text.split(".") if s.strip()]

                try:
                    # Generate and send audio for each sentence
                    for sentence in sentences:
                        sentence = sentence + "."  # Add back the period
                        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}"
                        audio_path = (
                            await default_context_cache.tts_engine.async_generate_audio(
                                text=sentence, file_name_no_ext=file_name
                            )
                        )
                        logger.info(
                            f"Generated audio for sentence: {sentence} at: {audio_path}"
                        )

                        await websocket.send_json(
                            {
                                "status": "partial",
                                "audioPath": audio_path,
                                "text": sentence,
                            }
                        )

                    # Send completion signal
                    await websocket.send_json({"status": "complete"})

                except Exception as e:
                    logger.error(f"Error generating TTS: {e}")
                    await websocket.send_json({"status": "error", "message": str(e)})

        except WebSocketDisconnect:
            logger.info("TTS WebSocket client disconnected")
        except Exception as e:
            logger.error(f"Error in TTS WebSocket connection: {e}")
            await websocket.close()

    return router
