"""Central configuration for LocalVoiceAgent.

Every value can be overridden with an environment variable so the same code can
run from a different root without editing files.  Nothing here points at a cloud
service: the only network endpoints are loopback addresses.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------- root
ROOT = Path(os.environ.get("LVA_ROOT", r"E:\AI\LocalVoiceAgent"))

SRC = ROOT / "src"
MODELS = ROOT / "models"
DATA = ROOT / "data"
LOGS = ROOT / "logs"
BENCH = ROOT / "benchmarks"
WEB = ROOT / "web"
VOCAB = ROOT / "vocabulary"
RECORDINGS = ROOT / "recordings"
VOICES = ROOT / "voices"
BACKUPS = ROOT / "backups"
DOCS = ROOT / "docs"
APPS = ROOT / "apps"

for _d in (DATA, LOGS, BENCH, VOCAB, RECORDINGS, VOICES, BACKUPS, DOCS):
    _d.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------- models
SENSEVOICE_DIR = MODELS / "sensevoice"
PARAFORMER_DIR = MODELS / "paraformer"
QWEN3ASR_DIR = MODELS / "qwen3asr"
MELOTTS_DIR = MODELS / "melotts"
MELOTTS_INT8_DIR = MODELS / "melotts_int8"
SILERO_VAD = MODELS / "silero_vad.onnx"

# -------------------------------------------------------------------- audio
ASR_RATE = 16000          # everything fed to the ASR engines
TTS_RATE = 44100          # MeloTTS zh_en native output rate
CAPTURE_RATE = 48000      # device rate pulled from WASAPI, then resampled
BLOCK_FRAMES = 1024       # frames per capture callback
VAD_WINDOW = 512          # samples per VAD decision window @16k (32 ms)

# ---------------------------------------------------------------- services
SERVICE_HOST = "127.0.0.1"        # loopback only; never 0.0.0.0
SERVICE_PORT = int(os.environ.get("LVA_PORT", "8765"))
# PR-015: the Hub control face.  LVA no longer owns a llama-server port; this is
# the Hub the Core talks to, kept as a named constant so nothing hardcodes it.
HUB_PORT = int(os.environ.get("LVA_HUB_PORT", "8080"))
#: Local Hub API key.  The Hub ships with `security.apiKeyEnabled: true`, so the
#: management client must present it.  Held in memory only -- never logged and
#: never written to disk; empty means "this Hub does not require a key".
HUB_API_KEY = os.environ.get("LVA_HUB_API_KEY", "")


def hub_base_url(*, with_v1: bool = False) -> str:
    """The single derivation of the Hub endpoint.

    Callers must use this instead of building the URL from `SERVICE_HOST` and
    `HUB_PORT` themselves, and providers must default to it instead of carrying
    their own literal.  The R20 incident (a wrong port in one of six copies) is the
    reason this exists: one fact, one place to change it.
    """
    base = f"http://{SERVICE_HOST}:{HUB_PORT}"
    return f"{base}/v1" if with_v1 else base


# ---------------------------------------------------------------------- llm
# PR-015 (plan L1263/L1285): the default LLM endpoint is the **Hub inference
# face**, not a bare child llama-server.  The Hub is the model runtime authority
# (hard constraint 2); a direct child endpoint must not be the default.  Derived
# from `hub_base_url()` so the port keeps a single source (R25/B7).
LLM_BASE_URL = os.environ.get("LVA_LLM_URL", "") or hub_base_url(with_v1=True)
LLM_API_KEY = os.environ.get("LVA_LLM_KEY", "")   # never written to logs
LLM_MODEL = os.environ.get("LVA_LLM_MODEL", "local-live-llm")
LLM_TIMEOUT = float(os.environ.get("LVA_LLM_TIMEOUT", "180"))
LLM_CONTEXT = int(os.environ.get("LVA_LLM_CONTEXT", "8192"))
LLM_MAX_TOKENS = int(os.environ.get("LVA_LLM_MAX_TOKENS", "512"))
# A deep question spends most of its budget inside the thinking pass before the
# answer even starts, so it gets a larger ceiling.
LLM_DEEP_MAX_TOKENS = int(os.environ.get("LVA_LLM_DEEP_MAX_TOKENS", "2048"))

DB_PATH = DATA / "memory.db"

# ------------------------------------------------------------------ engines
# Chosen from this machine's own measurements; see benchmarks/*.md,
# benchmarks/asr-correction-effect.json and DEPLOYMENT_REPORT.md.
#   live    SenseVoice  - best scientific-term accuracy AFTER correction
#                         (sci CER 0.180 vs 0.187 paraformer / 0.220 qwen3-asr)
#                         and 络合 recovered 4/4.  RTF 0.034, 297 MB, 0 MB VRAM.
#   arch    SenseVoice  - the always-on recorder must stay cheap: RTF 0.034
#                         costs ~3% of a core, versus 24% for qwen3-asr.
#   second  Qwen3-ASR   - best raw accuracy on real human speech (CER 0.0252)
#                         but 10x the compute, so it is an on-demand re-pass
#                         over a chosen clip rather than the live path.
LIVE_ASR = os.environ.get("LVA_LIVE_ASR", "sensevoice")
ARCHIVE_ASR = os.environ.get("LVA_ARCHIVE_ASR", "sensevoice")
SECOND_PASS_ASR = os.environ.get("LVA_SECOND_ASR", "qwen3asr")
TTS_ENGINE = os.environ.get("LVA_TTS", "melotts")

# MeloTTS thread count.  Measured on this machine for a 6.4 s utterance:
#   2 threads 2818 ms | 4 threads 1789 ms | 6 threads 1546 ms
#   8 threads 1290 ms | 12 threads 1232 ms
# More threads genuinely shorten wall time (no oversubscription penalty), so 8 is
# used: it is ~17% faster than 6 with still-modest CPU, and the CPU is otherwise
# idle because the LLM runs on the GPU.
TTS_THREADS = int(os.environ.get("LVA_TTS_THREADS", "8"))
ASR_THREADS = int(os.environ.get("LVA_ASR_THREADS", "6"))

# ------------------------------------------------------------------ barge-in
# How much louder than the assistant's own playback user speech must be before
# it interrupts.  With speakers, lower it if interruptions are ignored and raise
# it if the assistant cuts itself off; with headphones 1.0 is plenty.
# When echo cancellation is active this gate becomes a floor rather than the main
# defence, because the assistant's voice has already been subtracted.
ECHO_GUARD = float(os.environ.get("LVA_ECHO_GUARD", "2.0"))
BARGE_FLOOR = float(os.environ.get("LVA_BARGE_FLOOR", "0.015"))
BARGE_BLOCKS = int(os.environ.get("LVA_BARGE_BLOCKS", "3"))   # ~96 ms of speech

# ------------------------------------------------------- echo cancellation
# ------------------------------------------------------------------ queues
# Bounded so a slow consumer can never make the microphone path grow without
# bound.  Overflow drops the oldest block and is counted.
FRAME_QUEUE_MAX = int(os.environ.get("LVA_FRAME_QUEUE_MAX", "256"))   # ~8 s of audio
TURN_QUEUE_MAX = int(os.environ.get("LVA_TURN_QUEUE_MAX", "4"))

# A segment shorter than this is not a turn: it is a cough, a clack, a door.
# The VAD must still have seen min_speech_duration to emit it at all, so this is
# the second, cheap gate.
MIN_UTTERANCE_S = float(os.environ.get("LVA_MIN_UTTERANCE_S", "0.35"))

# A candidate interruption pauses playback and waits this long for the utterance
# to be recognised.  If it turns out to be a backchannel or a noise, playback
# resumes from the same sample instead of the reply being lost.
BACKCHANNEL_GRACE_S = float(os.environ.get("LVA_BACKCHANNEL_GRACE_S", "2.5"))

# LVA_AEC=1 subtracts the assistant's own playback from the microphone signal
# (WebRTC AEC3 + noise suppression), which is what makes barge-in work with
# speakers rather than headphones.  LVA_ECHO_DELAY_MS is the round trip from
# writing audio to the sound card to hearing it come back: raise it if the echo
# is not being removed, lower it if it is too aggressive.  Interruptions are
# ignored for LVA_AEC_WARMUP_S while the filter learns the room.
AEC = os.environ.get("LVA_AEC", "1") == "1"
ECHO_DELAY_MS = float(os.environ.get("LVA_ECHO_DELAY_MS", "60"))
AEC_WARMUP_S = float(os.environ.get("LVA_AEC_WARMUP_S", "2.0"))

# ------------------------------------------------------------------ privacy
LOG_TRANSCRIPTS = os.environ.get("LVA_LOG_TRANSCRIPTS", "0") == "1"

# -------------------------------------------------------------------- audio
# LVA_MUTE=1 makes the assistant load a silent player instead of opening the
# sound card.  Tests and measurements run muted so they can never start talking
# out of the speakers; the normal assistant leaves this at 0.
MUTE = os.environ.get("LVA_MUTE", "0") == "1"
