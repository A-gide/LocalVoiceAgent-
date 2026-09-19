"""LocalVoiceAgent - a fully local, privacy-first voice assistant.

Modules
-------
config      paths, ports and tunables (env-overridable)
audio       file I/O, resampling, capture, interruptible playback
asr         SenseVoice / Paraformer / Qwen3-ASR on CPU
tts         MeloTTS streaming, sentence chunking, Windows SAPI fallback
llm         OpenAI-compatible loopback client with fast/deep routing
vocab       scientific terminology correction (pinyin + letter fuzzy match)
memory      SQLite archive with CJK-capable full-text search
pipeline    VAD, RECORDING/LIVE separation, barge-in
server      FastAPI + WebSocket surface
textutil    normalisation and speech-safe text cleanup
"""

__version__ = "1.0.0"
