"""Voice pipeline: capture -> VAD -> ASR -> (LLM -> TTS) with barge-in.

Two modes, strictly separated, because an assistant that answers the television
is worse than no assistant at all:

RECORDING
    speech is transcribed, corrected and archived.  The LLM and TTS are never
    invoked, so nothing is ever spoken back.

LIVE
    the user has explicitly entered a conversation: transcribe -> answer ->
    speak, and the user can interrupt at any point.

Threading contract, which is what makes barge-in work:

* the audio thread only ever calls `feed()`, which is cheap and never blocks;
* the frame loop runs VAD + barge-in detection and must stay free, so it hands
  finished utterances to a queue instead of transcribing them inline;
* one worker thread consumes that queue and runs the slow ASR/LLM/TTS work.

The microphone is not opened in here.  `feed()` is the single entry point for
audio, so the whole state machine can be driven from a test harness with
recorded audio and its timings measured deterministically.
"""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import numpy as np
import sherpa_onnx as so

from . import asr as ASR
from . import audio as A
from . import config as C
from . import llm as LLM
from . import memory as MEM
from . import textutil as TX
from . import tts as TTS
from . import vocab as VO

log = logging.getLogger("lva.pipeline")

PERSONA = """你是运行在用户本机的本地语音助手。要求：
- 用简体中文口语化回答，简短直接，通常不超过三句话。
- 回答会被朗读出来，所以不要输出 Markdown、代码块、表情符号或列表符号。
- 你可以访问本机保存的现实历史记录（用户过去说过的话）。
- 当用户问到“过去说过什么、今天/昨天/上周发生过什么、某次讨论”时，
  只在下面提供的历史记录里寻找答案，并引用其中的内容。
- 如果历史记录里没有相关证据，就直接说没有找到相关记录，绝对不要编造
  用户过去的经历、时间或说过的话。这一点没有例外。
- 普通知识问题直接回答，不需要提到历史记录。
"""

HISTORY_HEADER = """以下是本机历史记录的检索结果，这是事实来源。
检索基于语音识别的近似匹配，问句里的词可能被听错（例如“漯河滴定”就是
“络合滴定”）。这些记录与问题主题一致时，必须直接引用记录内容作答，
并在回答里保留记录中的关键信息（专有名词、代号、数量）。
只有记录与问题确实完全无关时，才回答没有找到记录。"""

DEEP_HINTS = ("推导", "证明", "仔细分析", "详细分析", "深入比较", "逐步", "完整解释",
              "原理", "计算一下", "严格", "为什么")

# Upper bound on how long a finished turn stays marked as speaking while its
# audio drains.  Guards against a pathological queue keeping the flag set.
MAX_SPEECH_TAIL_S = 180.0


class Mode(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    LIVE = "live"


class FloorOwner(str, Enum):
    USER = "user"
    AGENT = "agent"
    NONE = "none"


@dataclass
class Event:
    kind: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "ts": self.ts, **self.data}


# Fillers that must not become a turn.  Saying "嗯" while the assistant talks is
# feedback, not a question, and answering it produces the maddening behaviour of
# a system that replies to every noise.  LiveKit and vocode both special-case
# this; the list is short and Chinese-first because that is what is spoken here.
BACKCHANNELS = {
    "嗯", "恩", "呃", "啊", "哦", "噢", "对", "对呀", "是", "是的", "好的", "好", "行",
    "继续", "然后呢", "嗯嗯", "对对", "ok", "okay", "mm", "hmm", "uh-huh",
}


def is_backchannel(text: str) -> bool:
    t = (text or "").strip().strip("，。！？!?,.").lower()
    return bool(t) and (t in BACKCHANNELS or (len(t) <= 2 and t in BACKCHANNELS))


@dataclass
class TurnMetrics:
    """Latency of one live turn.

    `e2e_ms` covers everything this process controls after the VAD has decided
    the user stopped talking.  The VAD's own silence window (~0.45 s) sits in
    front of it and is reported separately as `vad_silence_s`.
    """
    asr_ms: float = 0.0
    llm_ttft_ms: float = 0.0
    tts_ttfa_ms: float = 0.0
    first_audio_ms: float = 0.0
    e2e_ms: float = 0.0
    total_ms: float = 0.0
    barge_in_ms: float | None = None
    cancelled: bool = False
    vad_silence_s: float = 0.45

    def as_dict(self) -> dict:
        return {k: (round(v, 1) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


class Vad:
    """Thin wrapper over sherpa-onnx Silero VAD."""

    def __init__(self, threshold: float = 0.5, min_silence: float = 0.45,
                 min_speech: float = 0.25, max_speech: float = 20.0):
        cfg = so.VadModelConfig()
        cfg.silero_vad.model = str(C.SILERO_VAD)
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.min_silence_duration = min_silence
        cfg.silero_vad.min_speech_duration = min_speech
        cfg.silero_vad.max_speech_duration = max_speech
        cfg.silero_vad.window_size = C.VAD_WINDOW
        cfg.sample_rate = C.ASR_RATE
        cfg.num_threads = 1
        self._vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)
        self.min_silence = min_silence

    def accept(self, block: np.ndarray) -> list[np.ndarray]:
        self._vad.accept_waveform(block)
        out = []
        while not self._vad.empty():
            out.append(np.array(self._vad.front.samples, dtype=np.float32))
            self._vad.pop()
        return out

    @property
    def speech_detected(self) -> bool:
        return bool(self._vad.is_speech_detected())

    def reset(self) -> None:
        self._vad.reset()


class VoiceCore:
    # How much audio from just before an interruption is handed to the next
    # utterance.  ~0.77 s at 512 samples per block: long enough to keep the
    # consonant onset of a Chinese syllable, short enough not to replay the
    # assistant's own tail back into the transcript.
    PREROLL_BLOCKS = 24

    def __init__(self, memory: MEM.Memory | None = None,
                 asr_engine: str | None = None,
                 tts_engine: str | None = None,
                 archiver: str | None = None,
                 on_event: Callable[[Event], None] | None = None,
                 device_in: str | None = None, device_out: str | None = None,
                 echo_guard: float | None = None,
                 use_player: bool = True,
                 muted: bool | None = None):
        self.memory = memory or MEM.Memory()
        self.vocab = VO.default()
        self.on_event = on_event or (lambda e: None)

        self.mode = Mode.IDLE
        self.asr_name = asr_engine or C.LIVE_ASR
        self.archive_name = archiver or C.ARCHIVE_ASR
        self._asr: dict[str, ASR.BaseEngine] = {}
        self.tts = TTS.load(tts_engine or C.TTS_ENGINE) if tts_engine != "none" else None

        self.vad = Vad(min_silence=0.45)
        # Barge-in needs a *fast* confirmation, not utterance-grade segmentation:
        # the segmentation VAD waits 0.25 s of speech before it reports anything,
        # which alone pushes interruption latency past the 800 ms target.
        self.barge_vad = Vad(threshold=0.5, min_silence=0.2, min_speech=0.1,
                             max_speech=5.0)
        # Bounded, with an explicit overflow policy: the microphone path must
        # never block and must never grow without bound.  Dropping the oldest
        # block and counting it keeps latency honest under load.
        self._frame_q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=C.FRAME_QUEUE_MAX)
        self._turn_q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=C.TURN_QUEUE_MAX)
        self._frame_thread: threading.Thread | None = None
        self._turn_thread: threading.Thread | None = None
        self._running = False

        self.mic: A.Microphone | None = None
        self.player: A.Player | A.NullPlayer | None = None
        self.use_player = use_player
        # Muted runs load a silent player, so a test or a measurement can drive
        # the whole state machine without any chance of sound reaching the room.
        self.muted = C.MUTE if muted is None else muted
        self.device_in = device_in
        self.device_out = device_out

        # Barge-in must not be triggered by the assistant's own voice returning
        # through the microphone.  User speech has to be this many times louder
        # than the level currently being played before it interrupts.
        self.echo_guard = C.ECHO_GUARD if echo_guard is None else echo_guard
        self.barge_floor = C.BARGE_FLOOR
        self._playback_level = 0.0
        self._speech_run = 0
        self._speech_run_needed = C.BARGE_BLOCKS
        # Echo cancellation, and the rolling pre-roll that recovers the first
        # syllable of an interruption (clearing the buffer on barge-in otherwise
        # throws away the moment the user started talking).
        self.aec: A.Aec | None = None
        self._preroll: collections.deque = collections.deque(maxlen=self.PREROLL_BLOCKS * 2)
        self._prepend: list[np.ndarray] = []
        # A candidate interruption pauses playback instead of destroying it.  Only
        # when the utterance turns out to be a real turn do we flush and cancel;
        # a cough or a "mm-hm" resumes from the same sample.  Flushing cannot be
        # undone, so the reversible stage has to come first.
        self._candidate_pending = False
        self._candidate_deadline = 0.0
        self._speaking = threading.Event()
        self._generation = 0                 # bumped to cancel a turn (monotonic turn_id)
        self.floor_owner = FloorOwner.NONE
        self._cancel = threading.Event()

        self.history: list[dict] = []
        self.last_turn: TurnMetrics | None = None
        # When set, overrides automatic domain detection for the terminology
        # corrector and provides the contextual-bias word list to ASR engines
        # that support one.  None means "detect from the utterance".
        self.session_domain: str | None = None
        self.stats = {"utterances": 0, "live_turns": 0, "barge_ins": 0,
                      "duck_ignored": 0, "backchannels": 0}

    # ------------------------------------------------------------- lifecycle
    def load_asr(self, name: str | None = None) -> ASR.BaseEngine:
        name = name or self.asr_name
        if name not in self._asr:
            self._asr[name] = ASR.load(name)
        return self._asr[name]

    def start(self, open_devices: bool = True) -> None:
        self._running = True
        self.load_asr()
        if self.archive_name != self.asr_name:
            self.load_asr(self.archive_name)
        if open_devices:
            if self.use_player:
                self.player = A.make_player(muted=self.muted, device=self.device_out)
                self.player.start()
            # The echo canceller needs the render signal, so it can only be built
            # once the player exists.  With it active the microphone no longer
            # hears the assistant and interruption stops being a loudness guess.
            if C.AEC and not self.muted and isinstance(self.player, A.Player):
                try:
                    self.aec = A.Aec(delay_ms=C.ECHO_DELAY_MS)
                except Exception:  # noqa: BLE001
                    log.exception("echo cancellation unavailable; falling back to the gate")
                    self.aec = None
            self.mic = A.Microphone(self.feed, device=self.device_in)
            if self.aec is not None:
                self.mic.enable_aec(self.aec, self.player.reference)
            self.mic.start()
        self._frame_thread = threading.Thread(target=self._frame_loop,
                                              name="lva-frames", daemon=True)
        self._turn_thread = threading.Thread(target=self._turn_loop,
                                             name="lva-turns", daemon=True)
        self._frame_thread.start()
        self._turn_thread.start()
        self.emit("ready", mic=getattr(self.mic, "device_name", ""),
                  out=getattr(self.player, "device_name", ""),
                  asr=self.asr_name, tts=getattr(self.tts, "name", "none"),
                  muted=self.muted, aec=self.aec is not None,
                  echo_delay_ms=C.ECHO_DELAY_MS if self.aec else None)

    def stop(self) -> None:
        self._running = False
        self._frame_q.put(None)
        self._turn_q.put(None)
        for t in (self._frame_thread, self._turn_thread):
            if t:
                t.join(timeout=3)
        if self.mic:
            self.mic.stop()
        if self.player:
            self.player.stop()

    def emit(self, kind: str, **data) -> None:
        try:
            self.on_event(Event(kind, data))
        except Exception:  # noqa: BLE001
            log.exception("event handler failed")

    def set_mode(self, mode: Mode | str) -> Mode:
        mode = Mode(mode)
        if mode == self.mode:
            return mode
        if mode != Mode.LIVE:
            self.cancel_turn()
        self.mode = mode
        self.vad.reset()
        self.emit("mode", mode=mode.value)
        log.info("mode -> %s", mode.value)
        return mode

    def set_domain(self, domain: str | None) -> str | None:
        """Pin the subject area, or pass None/"" to go back to auto-detection."""
        d = (domain or "").strip().lower() or None
        if d is not None and d not in ("chemistry", "physics", "biology", "general"):
            raise ValueError(f"unknown domain {domain!r}")
        self.session_domain = None if d in (None, "general") else d
        self.emit("domain", domain=self.session_domain or "auto")
        return self.session_domain

    def hotwords(self) -> list[str] | None:
        """Contextual-bias list for engines that accept one, else None."""
        dom = self.session_domain or "general"
        words = self.vocab.hotwords(dom, limit=200) if dom != "general" else None
        return words or None

    # ----------------------------------------------------------------- audio
    @staticmethod
    def _offer(q: queue.Queue, item, counter: str, stats: dict) -> None:
        """put_nowait with drop-oldest; the producer never blocks or raises."""
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            stats[counter] = stats.get(counter, 0) + 1
            try:
                q.put_nowait(item)
            except queue.Full:
                stats[counter] = stats.get(counter, 0) + 1

    def feed(self, block: np.ndarray) -> None:
        """Entry point for captured 16 kHz audio; must never block."""
        if not self._running:
            return
        self._offer(self._frame_q, np.asarray(block, dtype=np.float32),
                    "frames_dropped", self.stats)

    def _frame_loop(self) -> None:
        while self._running:
            try:
                block = self._frame_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if block is None:
                break
            try:
                self._on_block(block)
            except Exception:  # noqa: BLE001
                log.exception("frame handling failed")

    def _on_block(self, block: np.ndarray) -> None:
        # A candidate that never turns into an utterance was noise: give the
        # assistant its voice back rather than leaving it paused for ever.
        if self._candidate_pending and time.time() > self._candidate_deadline:
            self._resume_after_candidate("no_utterance")

        segments = self.vad.accept(block)
        # Keep a rolling tail of clean audio for every block, including while the
        # assistant is talking: an interruption must be handed the moment the user
        # started speaking, and that moment is by definition during playback.
        self._preroll.append(block)

        if self._speaking.is_set() and self.mode == Mode.LIVE:
            # While the assistant is talking, segments are discarded: whatever
            # the microphone picks up during that window is either the assistant
            # (already cancelled) or an interruption that will be handled below.
            if segments and not self._candidate_pending:
                self.stats["duck_ignored"] += len(segments)
                segments = []
            self.barge_vad.accept(block)
            # With echo cancellation the assistant's own voice is gone from this
            # signal, so the interruption test no longer has to out-shout it - a
            # modest margin over the residual is enough.  Without it the old
            # loudness ratio remains the only defence.
            guard = 1.0 if (self.aec is not None and self.aec.converged) else self.echo_guard
            gate = max(self.barge_floor, self._playback_level * guard)
            if (A.rms(block) > gate and self.barge_vad.speech_detected
                    and not (self.aec is not None and not self.aec.converged)):
                self._speech_run += 1
            else:
                self._speech_run = 0
            if self._speech_run >= self._speech_run_needed:
                level = A.rms(block)
                self._speech_run = 0
                # Pause, do not destroy.  What we can hear so far is loud,
                # sustained speech - but "mm-hm" is also loud and sustained, and
                # a flushed queue cannot be un-flushed.  The utterance itself
                # decides whether this was a turn.
                self._candidate_interrupt(level)
            # While a candidate is being judged the utterance itself has to reach
            # the worker, otherwise nothing can ever confirm or dismiss it - the
            # earlier version kept these segments but returned before queueing
            # them, so an interruption paused playback and then never committed.
            if self._candidate_pending and segments:
                self._queue_segments(segments)
            return

        self._queue_segments(segments)

    def _queue_segments(self, segments: list[np.ndarray]) -> None:
        for seg in segments:
            if not self._accept_segment(seg):
                continue
            if self._prepend:
                seg = np.concatenate(self._prepend + [seg])
                self._prepend = []
            self._offer(self._turn_q, seg, "utterances_dropped", self.stats)

    def _accept_segment(self, seg: np.ndarray) -> bool:
        """Is this long enough to be a turn, rather than a cough or a clack?

        The VAD has already required min_speech_duration to emit a segment at
        all, so this is the second, cheap gate - and the one that stops a false
        segment from becoming a false answer.  Extracted so the rule is testable
        without a microphone.
        """
        if seg.size < int(C.MIN_UTTERANCE_S * C.ASR_RATE):
            self.stats["short_segments"] = self.stats.get("short_segments", 0) + 1
            return False
        return True

    def _turn_loop(self) -> None:
        while self._running:
            try:
                seg = self._turn_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if seg is None:
                break
            try:
                self._handle_utterance(seg)
            except Exception:  # noqa: BLE001
                log.exception("turn failed")

    # ------------------------------------------------------------- utterances
    def _handle_utterance(self, samples: np.ndarray) -> None:
        if self.mode == Mode.IDLE:
            return
        t0 = time.perf_counter()
        engine = self.load_asr(self.asr_name)
        # Engines with contextual biasing get the current domain's word list;
        # engines without one (SenseVoice, Paraformer on this build) are handled
        # purely by the corrector instead - no pretending that a hotword list was
        # applied when it was not.
        res = engine.transcribe(samples, hotwords=self.hotwords())
        asr_ms = (time.perf_counter() - t0) * 1000.0
        raw = ASR.clean(res.text)
        if not raw:
            return
        corrected = self.vocab.correct(raw, domain=self.session_domain)
        self.stats["utterances"] += 1
        source = "live" if self.mode == Mode.LIVE else "recording"

        self.emit("transcript", raw=raw, text=corrected.corrected,
                  domain=corrected.domain, applied=corrected.applied,
                  flagged=corrected.flagged, asr_ms=round(asr_ms, 1),
                  audio_s=round(len(samples) / C.ASR_RATE, 2), mode=self.mode.value)

        # Archive in both modes: this is the record of what was actually said.
        wav_path = self._save_audio(samples, "live" if self.mode == Mode.LIVE else "rec")
        row_id = self.memory.add(raw_text=raw, fixed_text=corrected.corrected, source=source,
                                 domain=corrected.domain, audio_path=str(wav_path or ""),
                                 duration_s=len(samples) / C.ASR_RATE)
        self.emit("archived", id=row_id, source=source)

        if self.mode != Mode.LIVE:
            return                               # RECORDING never speaks

        # This is where a candidate interruption is judged.  A backchannel
        # ("mm-hm", "对", "好的") is feedback, not a question: it is archived
        # because it was said, the assistant gets its voice back, and no turn
        # opens.  Anything else confirms the interruption and the reply is
        # discarded for good.
        if self._candidate_pending:
            if is_backchannel(corrected.corrected):
                self.stats["backchannels"] += 1
                self.emit("backchannel", text=corrected.corrected, resumed=True)
                self._resume_after_candidate("backchannel")
                return
            self.barge_in(self._playback_level)
        elif is_backchannel(corrected.corrected):
            self.stats["backchannels"] += 1
            self.emit("backchannel", text=corrected.corrected)
            return

        self.stats["live_turns"] += 1
        # The row just written is excluded from the history search, otherwise the
        # question matches itself and looks like proof the user said it before.
        self._run_turn(corrected, asr_ms, exclude_ids={row_id})

    def _save_audio(self, samples: np.ndarray, prefix: str) -> Path | None:
        try:
            d = C.RECORDINGS / time.strftime("%Y-%m-%d")
            d.mkdir(parents=True, exist_ok=True)
            stamp = f"{time.strftime('%H%M%S')}-{int(time.time() * 1000) % 1000:03d}"
            p = d / f"{prefix}-{stamp}.wav"
            A.write_wav(p, samples, C.ASR_RATE)
            return p
        except Exception:  # noqa: BLE001
            log.exception("could not archive audio")
            return None

    # ------------------------------------------------------------------ turn
    def _prompt_messages(self, corrected: VO.CorrectedText, memory_block: str) -> list[dict]:
        """System prompt, recent turns, then the user turn.

        Retrieved history is attached to the *user* message rather than the
        system prompt: a small model attends to the last message far more
        reliably than to an instruction buried at the top, and this was measured
        - the same evidence placed in the system prompt was ignored, while the
        model used it when it sat next to the question.
        """
        msgs = [{"role": "system", "content": PERSONA}]
        msgs.extend(self.history[-6:])
        user = corrected.corrected
        if corrected.domain != "general":
            user += f"\n(领域提示：{corrected.domain})"
        if memory_block:
            user = (f"{user}\n\n{HISTORY_HEADER}\n---\n{memory_block}\n---\n"
                    "请依据以上记录回答。")
        msgs.append({"role": "user", "content": user})
        return msgs

    def _run_turn(self, corrected: VO.CorrectedText, asr_ms: float,
                  exclude_ids: set[int] | None = None) -> None:
        m = TurnMetrics(asr_ms=asr_ms)
        self.last_turn = m
        self._cancel.clear()
        self._generation += 1
        gen_id = self._generation

        # --- deterministic history routing; never left to the model to decide
        memory_block = ""
        hq = MEM.parse_history_query(corrected.corrected)
        if hq is not None:
            hits = MEM.search_history(self.memory, hq, exclude_ids=exclude_ids)
            memory_block = MEM.format_history_context(hits)
            self.emit("memory", intent=hq.intent, window=hq.window_label(),
                      keywords=hq.keywords, hits=[h.as_dict() for h in hits],
                      found=len(hits))

        llm_mode = "deep" if any(k in corrected.corrected for k in DEEP_HINTS) else "fast"
        stream = LLM.stream(self._prompt_messages(corrected, memory_block), mode=llm_mode)

        chunker = TTS.SentenceChunker()
        spoken: list[str] = []
        state = {"first_token": None, "first_audio": None, "tts_ttfa": None,
                 "t_sentence": None}
        t_turn = time.perf_counter()

        def speak(sentence: str) -> None:
            # Models leak Markdown and LaTeX into replies; reading "###" or
            # "\frac{}{}" aloud is not acceptable, so it is removed here.
            spoken_text = TX.strip_for_speech(sentence)
            if not spoken_text:
                return
            if self._cancel.is_set() or gen_id != self._generation or self.tts is None:
                return
            state["t_sentence"] = time.perf_counter()

            def on_chunk(samples, sr):  # noqa: ANN001
                if self._cancel.is_set() or gen_id != self._generation:
                    return 0
                if state["tts_ttfa"] is None:
                    state["tts_ttfa"] = (time.perf_counter()
                                         - (state["t_sentence"] or t_turn)) * 1000.0
                if state["first_audio"] is None:
                    state["first_audio"] = time.perf_counter() - t_turn
                level = A.rms(samples)
                self._playback_level = max(self._playback_level * 0.7, level)
                if self.player:
                    # Tagged with this turn: after an interruption the player
                    # drops the block at the point of use, which is what makes
                    # the interruption race-free.
                    self.player.play(samples, sr, gen=gen_id)
                # The level goes to the UI so the character's mouth follows the
                # audio that is actually playing rather than a fixed animation.
                self.emit("speak_chunk", chars=len(sentence), level=round(level, 4))
                return 1

            if isinstance(self.tts, TTS.MeloTTS):
                self.tts.on_chunk = on_chunk
                try:
                    self.tts.synthesize(sentence)
                finally:
                    self.tts.on_chunk = None
            else:
                syn = self.tts.synthesize(sentence)
                if state["first_audio"] is None:
                    state["first_audio"] = time.perf_counter() - t_turn
                if state["tts_ttfa"] is None:
                    state["tts_ttfa"] = (time.perf_counter()
                                         - (state["t_sentence"] or t_turn)) * 1000.0
                if self.player:
                    self.player.play(syn.samples, syn.sample_rate, gen=gen_id)
            spoken.append(sentence)

        text_parts: list[str] = []
        self._speaking.set()
        self.floor_owner = FloorOwner.AGENT
        try:
            for piece in stream:
                if self._cancel.is_set() or gen_id != self._generation:
                    m.cancelled = True
                    break
                if state["first_token"] is None:
                    state["first_token"] = time.perf_counter() - t_turn
                text_parts.append(piece)
                for sentence in chunker.feed(piece):
                    speak(sentence)
            if not m.cancelled:
                for sentence in chunker.flush():
                    speak(sentence)
                if self.player:
                    self.player.mark_end()
        except LLM.LLMError as e:
            log.warning("LLM error: %s", e)
            self.emit("error", where="llm", detail=str(e))
        finally:
            try:
                stream.close()               # type: ignore[attr-defined]
            except Exception:
                pass
            # Stay in the "speaking" state until the queued audio has actually
            # finished playing.  Clearing it as soon as the LLM stopped streaming
            # left a tail - often many seconds - during which the assistant was
            # still audible but a user interruption was no longer recognised,
            # because barge-in detection only runs while speaking.
            if not m.cancelled and self.player is not None and self.player.pending() > 0:
                deadline = time.time() + MAX_SPEECH_TAIL_S
                while (self.player.pending() > 0 and not self._cancel.is_set()
                       and not self._candidate_pending          # let the turn thread
                       and time.time() < deadline):             # resolve the candidate
                    time.sleep(0.05)
            self._speaking.clear()
            self.floor_owner = FloorOwner.NONE
            self._playback_level = 0.0

        reply = "".join(text_parts)
        m.llm_ttft_ms = (state["first_token"] or 0) * 1000.0
        m.tts_ttfa_ms = state["tts_ttfa"] if state["tts_ttfa"] is not None else -1.0
        m.first_audio_ms = (state["first_audio"] or 0) * 1000.0
        m.e2e_ms = m.asr_ms + m.first_audio_ms
        m.total_ms = (time.perf_counter() - t_turn) * 1000.0
        # A turn cancelled before it produced anything is not a reply; announcing
        # one would make a mode switch look like the assistant had spoken.
        if reply or not m.cancelled:
            self.emit("reply", text=reply, spoken=spoken, metrics=m.as_dict(),
                      cancelled=m.cancelled, mode=llm_mode)

        if reply:
            self.history.append({"role": "user", "content": corrected.corrected})
            self.history.append({"role": "assistant", "content": reply})
            # The assistant's own words are archived as part of the room record,
            # and are never presented to the model as the user's own evidence.
            self.memory.add(raw_text=reply, fixed_text=reply, source="assistant",
                            domain=corrected.domain, duration_s=0.0,
                            meta={"in_reply_to": corrected.raw[:120]})

    # -------------------------------------------------------------- barge-in
    def barge_in(self, level: float = 0.0) -> None:
        """Stop speaking immediately and start listening to the new utterance.

        Order matters and is the whole point: the generation is bumped *first*,
        so a producer that passed its own staleness check a moment ago can no
        longer get audio played.  The player rejects blocks from a superseded
        generation where they are *used*, so the bump is what actually stops the
        sound; flushing beforehand would leave exactly the window that shows up
        as "it kept talking for another sentence after I interrupted" - the bug
        Vocalis and GLaDOS both ship.
        """
        t0 = time.perf_counter()
        self.cancel_turn()                       # generation bump, before anything else
        self.floor_owner = FloorOwner.USER
        dropped = self.player.flush() if self.player else 0
        self._speaking.clear()
        self._candidate_pending = False
        # Hand the audio from just before the interruption to the next segment,
        # otherwise the first syllable the user spoke is thrown away with the
        # buffer we just cleared.  Exchanged, not read: cleared here so the same
        # audio can never seed two turns.
        self._prepend = list(self._preroll)[-self.PREROLL_BLOCKS:]
        self._preroll.clear()
        self.vad.reset()
        self.barge_vad.reset()
        self.stats["barge_ins"] += 1
        dt = (time.perf_counter() - t0) * 1000.0
        if self.last_turn:
            self.last_turn.barge_in_ms = dt
        self.emit("barge_in", ms=round(dt, 1), dropped=dropped, level=round(level, 4),
                  preroll_blocks=len(self._prepend), floor=self.floor_owner.value,
                  turn_id=self.turn_id)

    def _candidate_interrupt(self, level: float) -> None:
        """Pause playback while we work out whether the user is talking to us.

        Cost of being wrong: a cough or a "mm-hm" would otherwise cut the reply
        off permanently.  Pausing keeps the queue and the position, so the wrong
        guess costs a short silence instead of a lost sentence.
        """
        if self._candidate_pending:
            self._candidate_deadline = time.time() + C.BACKCHANNEL_GRACE_S
            return
        if self.player:
            self.player.pause()
        self._candidate_pending = True
        self._candidate_deadline = time.time() + C.BACKCHANNEL_GRACE_S
        self.stats["interrupt_candidates"] = self.stats.get("interrupt_candidates", 0) + 1
        self.emit("interrupt_candidate", level=round(level, 4),
                  grace_s=C.BACKCHANNEL_GRACE_S)

    def _resume_after_candidate(self, reason: str) -> None:
        """The interruption was not a turn - carry on from where we stopped."""
        if self.player:
            self.player.resume()
        self._candidate_pending = False
        self.stats["interrupt_resumed"] = self.stats.get("interrupt_resumed", 0) + 1
        # The reply is still playing, so it must stay interruptible.
        if (self.player is not None and self.player.pending() > 0
                and self.mode == Mode.LIVE):
            self._speaking.set()
        self.emit("interrupt_resumed", reason=reason)

    @property
    def turn_id(self) -> int:
        return self._generation

    def cancel_turn(self) -> None:
        self._cancel.set()
        self._generation += 1
        self.floor_owner = FloorOwner.USER
        if self.player:
            self.player.flush()
