"""Audio I/O: file helpers, resampling, microphone capture and interruptible playback.

The player is the piece that makes barge-in possible: `flush()` empties the
queue and silences the output stream within a few milliseconds instead of
letting the remaining seconds of speech finish.
"""
from __future__ import annotations

import collections
import math
import queue
import threading
import time
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np

from . import config as C

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - PortAudio missing
    sd = None


# ------------------------------------------------------------------ file io
def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a PCM wav file as float32 mono in [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width == 2:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported sample width: {width * 8} bit")
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(a, dtype=np.float32), sr


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (x * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- resampling
def resample(a: np.ndarray, sr: int, target: int) -> np.ndarray:
    """Polyphase resample, falling back to linear interpolation."""
    if sr == target or a.size == 0:
        return np.asarray(a, dtype=np.float32)
    try:
        from scipy.signal import resample_poly

        frac = Fraction(target, sr).limit_denominator(1000)
        out = resample_poly(a, frac.numerator, frac.denominator)
        return np.ascontiguousarray(out, dtype=np.float32)
    except Exception:
        n = int(round(len(a) * target / sr))
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        x_old = np.linspace(0.0, 1.0, len(a), endpoint=False)
        x_new = np.linspace(0.0, 1.0, n, endpoint=False)
        return np.interp(x_new, x_old, a).astype(np.float32)


def duration(a: np.ndarray, sr: int) -> float:
    return len(a) / float(sr)


def rms(a: np.ndarray) -> float:
    if a.size == 0:
        return 0.0
    return float(math.sqrt(float(np.mean(np.square(a, dtype=np.float64)))))


# ------------------------------------------------------------------- devices
def list_devices() -> list[dict]:
    if sd is None:
        return []
    out = []
    for i, d in enumerate(sd.query_devices()):
        out.append({
            "index": i,
            "name": d["name"],
            "in": int(d["max_input_channels"]),
            "out": int(d["max_output_channels"]),
            "rate": int(d["default_samplerate"]),
            "hostapi": sd.query_hostapis(d["hostapi"])["name"],
        })
    return out


def _pick_device(kind: str, wanted: str | None) -> tuple[int | None, str]:
    """Resolve a device index. `wanted` matches a case-insensitive substring."""
    if sd is None:
        return None, ""
    devices = list_devices()
    pool = [d for d in devices if d["in" if kind == "input" else "out"] > 0]
    if not pool:
        return None, ""
    if wanted:
        w = wanted.lower()
        for d in pool:
            if w in d["name"].lower() and d["hostapi"] == "Windows WASAPI":
                return d["index"], d["name"]
        for d in pool:
            if w in d["name"].lower():
                return d["index"], d["name"]
    # Prefer WASAPI default when available: lowest latency on Windows.
    api = next((i for i, h in enumerate(sd.query_hostapis()) if h["name"] == "Windows WASAPI"), None)
    if api is not None:
        default = sd.query_hostapis(api)["default_" + ("input" if kind == "input" else "output") + "_device"]
        if default is not None and default >= 0:
            d = devices[default]
            if d["in" if kind == "input" else "out"] > 0:
                return d["index"], d["name"]
    idx = sd.default.device[0 if kind == "input" else 1]
    if idx is not None and idx >= 0:
        return int(idx), devices[int(idx)]["name"]
    return pool[0]["index"], pool[0]["name"]


# ------------------------------------------------------------------ capture
class Microphone:
    """Continuous mono capture, delivered as 16 kHz float32 blocks.

    `on_block(block)` is called from the PortAudio thread; keep it short and
    hand off to a queue if the consumer is slow.
    """

    def __init__(self, on_block, device: str | None = None,
                 rate: int = C.CAPTURE_RATE, block_frames: int = C.BLOCK_FRAMES):
        if sd is None:
            raise RuntimeError("sounddevice/PortAudio unavailable")
        self.on_block = on_block
        self.device_name = ""
        idx, name = _pick_device("input", device)
        self.device_index = idx
        self.device_name = name
        # Some devices only accept their native rate; probe and fall back.
        rates = [rate, 48000, 44100, 16000]
        last_err: Exception | None = None
        for r in dict.fromkeys(rates):
            try:
                sd.check_input_settings(device=idx, channels=1, dtype="float32", samplerate=r)
                self.rate = r
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        else:
            raise RuntimeError(f"no usable input rate for device {idx}: {last_err}")
        self.block_frames = block_frames
        self._stream: sd.InputStream | None = None
        self._acc = np.zeros(0, dtype=np.float32)
        self._acc_need = int(round(self.rate / C.ASR_RATE * C.VAD_WINDOW))
        self._lock = threading.Lock()
        self.overflows = 0
        self.last_block: np.ndarray = np.zeros(0, dtype=np.float32)
        # Echo cancellation runs on 10 ms frames, then the cleaned audio is
        # re-assembled into the blocks the VAD wants.  Framing at this layer
        # keeps input and output sample-exact: every captured sample is processed
        # once and delivered once, so nothing drifts over a long session.
        self.aec: Aec | None = None
        self.reference: PlaybackReference | None = None
        self._aec_in = np.zeros(0, dtype=np.float32)
        self._aec_out = np.zeros(0, dtype=np.float32)

    def enable_aec(self, aec: "Aec | None", reference: "PlaybackReference | None") -> None:
        self.aec = aec
        self.reference = reference

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        if status and status.input_overflow:
            self.overflows += 1
        mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        with self._lock:
            self._acc = np.concatenate((self._acc, mono)) if self._acc.size else mono
            while self._acc.size >= self._acc_need:
                chunk, self._acc = self._acc[: self._acc_need], self._acc[self._acc_need:]
                block = resample(chunk, self.rate, C.ASR_RATE)
                if self.aec is not None:
                    self._aec_in = np.concatenate((self._aec_in, block))
                    step = self.aec.FRAME
                    while self._aec_in.size >= step:
                        frame, self._aec_in = self._aec_in[:step], self._aec_in[step:]
                        # The reference is fed exactly as it is being played, with
                        # no extra shift.  Shifting it here as well as passing
                        # stream_delay_ms applied the delay twice and cost ~14 dB
                        # of echo suppression (measured 4.2 dB instead of 18 dB):
                        # the canceller's own delay estimator handles alignment.
                        ref = (self.reference.frame(step, 0.0)
                               if self.reference is not None
                               else np.zeros(step, dtype=np.float32))
                        self._aec_out = np.concatenate(
                            (self._aec_out, self.aec.process_frame(frame, ref)))
                    while self._aec_out.size >= C.VAD_WINDOW:
                        block, self._aec_out = (self._aec_out[:C.VAD_WINDOW],
                                                self._aec_out[C.VAD_WINDOW:])
                        self.last_block = block
                        self.on_block(block)
                else:
                    self.last_block = block
                    self.on_block(block)

    def start(self) -> None:
        # Idempotent: PR-020 resumes the mic on Passive/Live transitions, and the
        # startup path already opened it.  A second start would leak the first
        # stream and leave two callbacks racing on the same queue.
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            device=self.device_index, channels=1, dtype="float32",
            samplerate=self.rate, blocksize=0, callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


# ----------------------------------------------------------------- playback
class Player:
    """Queue-backed output stream that can be cut off instantly.

    `flush()` is what barge-in calls: it drops every pending buffer so the
    assistant stops mid-word rather than finishing its sentence.
    """

    def __init__(self, device: str | None = None, rate: int = C.TTS_RATE):
        if sd is None:
            raise RuntimeError("sounddevice/PortAudio unavailable")
        idx, name = _pick_device("output", device)
        self.device_index = idx
        self.device_name = name
        rates = [rate, 48000, 44100]
        last_err: Exception | None = None
        for r in dict.fromkeys(rates):
            try:
                sd.check_output_settings(device=idx, channels=1, dtype="float32", samplerate=r)
                self.rate = r
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        else:
            raise RuntimeError(f"no usable output rate for device {idx}: {last_err}")

        # Every queued block carries the generation it belongs to.  The consumer
        # drops a block whose generation is no longer current, which is what makes
        # an interruption race-free: a producer that passed its own staleness
        # check just before `flush()` cannot get its audio played afterwards,
        # because the block is rejected where it is used rather than where it was
        # queued.  (Draining the queue alone does not close that window - it is
        # the bug Vocalis and GLaDOS both have.)
        self._q: queue.Queue[tuple[int, np.ndarray] | None] = queue.Queue()
        self._stream: sd.OutputStream | None = None
        self._generation = 0
        self._lock = threading.Lock()
        self.playing = threading.Event()
        self._finished = threading.Event()
        self._paused = threading.Event()
        self.stale_dropped = 0
        # What is audible right now, for the echo canceller.
        self.reference = PlaybackReference()
        # Output Mute (PR-024).  A muted player must *stop* sound, not merely
        # skip new audio: the queue is flushed on the transition, and anything
        # queued while muted is dropped rather than held, so unmuting cannot
        # replay speech the user already silenced.
        self._muted = threading.Event()

    @property
    def generation(self) -> int:
        return self._generation

    def set_generation(self, generation: int) -> None:
        """Adopt the turn identity produced by the single authority (F-004).

        The Player used to keep its own counter that only moved on ``flush``, so a
        normal new turn -- which advances the pipeline's generation but does not
        flush -- was queued under a generation the callback then rejected.  The
        result was a turn whose text generated fine but whose audio was silently
        dropped.  The pipeline owns the turn identity, so it publishes it here and
        the sink checks against that one value; the equality test stays strict, so
        a genuinely stale packet is still rejected.
        """
        with self._lock:
            self._generation = generation

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    def set_muted(self, muted: bool) -> None:
        """Stop and suppress playback, or allow it again (PR-024).

        Entering mute flushes: the generation bump is what actually silences the
        audio, and the drain frees what was queued for a sentence already under
        way.  Leaving mute does not restore that audio -- the user asked for it to
        be silenced, so replaying it afterwards would be a surprise.
        """
        if muted:
            self._muted.set()
            self.flush()
        else:
            self._muted.clear()

    def _callback(self, outdata, frames, time_info, status):  # noqa: ANN001
        need = frames
        written = 0
        if self._paused.is_set():
            # Hold position: emit silence and leave the queue untouched so the
            # assistant can resume mid-sentence instead of restarting it.
            outdata[:, 0] = 0.0
            self.reference.push(outdata[:need, 0], int(self.rate))
            return
        while written < need:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is None:                      # end-of-utterance marker
                self._finished.set()
                continue
            gen, buf = item
            if gen != self._generation:
                # Belongs to a turn that has been interrupted: discard it here,
                # at the point of use, not merely at the point of queueing.
                self.stale_dropped += 1
                continue
            take = min(need - written, len(buf))
            outdata[written:written + take, 0] = buf[:take]
            written += take
            if take < len(buf):                   # partial: put the rest back
                self._q.put((gen, buf[take:]))
                break
        if written < need:
            outdata[written:, 0] = 0.0
        self.playing.set() if written else None
        # Publish the render signal from inside the audio callback: this runs on
        # the playback clock, so the reference lines up with what is actually
        # coming out of the speakers rather than with what was queued earlier.
        self.reference.push(outdata[:need, 0], int(self.rate))

    def start(self) -> None:
        self._stream = sd.OutputStream(
            device=self.device_index, channels=1, dtype="float32",
            samplerate=self.rate, blocksize=0, callback=self._callback,
        )
        self._stream.start()

    def play(self, samples: np.ndarray, sample_rate: int, gen: int | None = None) -> None:
        x = np.asarray(samples, dtype=np.float32)
        if sample_rate != self.rate:
            x = resample(x, sample_rate, self.rate)
        if self._muted.is_set():
            # Dropped, not held: holding it would let a later unmute play speech
            # the user silenced.
            return
        if x.size:
            self._finished.clear()
            self._q.put((self._generation if gen is None else gen,
                         np.ascontiguousarray(x)))

    def mark_end(self) -> None:
        self._q.put(None)

    def wait_done(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def pending(self) -> int:
        return self._q.qsize()

    def flush(self) -> int:
        """Invalidate everything queued. Returns how many buffers were discarded.

        The generation bump is what actually stops the audio; the drain only
        frees memory.  Keeping the bump inside the same lock as the drain means a
        concurrent `play()` cannot slip a block in behind it.
        """
        dropped = 0
        with self._lock:
            self._generation += 1
            while True:
                try:
                    self._q.get_nowait()
                    dropped += 1
                except queue.Empty:
                    break
            self._finished.set()
        return dropped

    def stop(self) -> None:
        self.flush()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def pause(self) -> None:
        """Hold playback where it is, keeping the queue and the position.

        This is what makes a *reversible* interruption possible: if the audio
        that triggered it turns out to be a cough or a "mm-hm", the assistant can
        carry on from exactly this sample.  Flushing cannot be undone, which is
        why the candidate stage pauses and only the confirmed stage flushes.
        """
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


class NullPlayer:
    """A player that consumes audio and stays silent.

    Test harnesses and resource measurements must never drive the real speakers:
    a test that quietly starts talking at 1 a.m. is a bug in the test, not a
    feature of the assistant.  The queue is simulated in wall-clock time so that
    `pending()` and `flush()` behave exactly like the real player - barge-in
    timing can be measured honestly without a single sample reaching the card.
    """

    def __init__(self, *_, **__):
        self.device_index = None
        self.device_name = "null (muted)"
        self.rate = C.TTS_RATE
        self.playing = threading.Event()
        self._finished = threading.Event()
        # (queued_at, duration, generation) - same generation semantics as the
        # real player, so a test exercises the stale-block drop rather than a
        # simpler path that only exists in tests.
        self._queue: list[tuple[float, float, int]] = []
        self._lock = threading.Lock()
        self._generation = 0
        self.played_samples = 0
        self.stale_dropped = 0
        self._paused = threading.Event()
        # Same Output Mute semantics as the real player, so a test exercises the
        # product's mute path rather than a simpler one that only exists in tests.
        self._muted = threading.Event()

    @property
    def generation(self) -> int:
        return self._generation

    def set_generation(self, generation: int) -> None:
        with self._lock:
            self._generation = generation

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    def set_muted(self, muted: bool) -> None:
        """Stop and suppress playback, or allow it again (PR-024)."""
        if muted:
            self._muted.set()
            self.flush()
        else:
            self._muted.clear()

    def start(self) -> None:
        pass

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def play(self, samples: np.ndarray, sample_rate: int, gen: int | None = None) -> None:
        x = np.asarray(samples, dtype=np.float32)
        if not x.size:
            return
        if self._muted.is_set():
            # Dropped, not held: a later unmute must not play silenced speech.
            return
        self._finished.clear()
        dur = x.size / float(sample_rate)
        with self._lock:
            self._queue.append((time.time(), dur,
                                self._generation if gen is None else gen))
            self.played_samples += x.size

    def _drain(self) -> None:
        now = time.time()
        with self._lock:
            kept = []
            for t, d, g in self._queue:
                if g != self._generation:
                    self.stale_dropped += 1          # interrupted turn
                elif t + d > now:
                    kept.append((t, d, g))
            self._queue = kept

    def mark_end(self) -> None:
        self._finished.set()

    def wait_done(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            self._drain()
            if not self._queue:
                self._finished.set()
                return True
            if deadline is not None and time.time() > deadline:
                return False
            time.sleep(0.02)

    def pending(self) -> int:
        self._drain()
        return len(self._queue)

    def flush(self) -> int:
        dropped = 0
        with self._lock:
            self._generation += 1
            dropped = len(self._queue)
            self._queue.clear()
        self._finished.set()
        return dropped

    def stop(self) -> None:
        self.flush()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def make_player(muted: bool = False, device: str | None = None,
                rate: int = C.TTS_RATE) -> Player | NullPlayer:
    """Build the right player for the situation (muted = no sound at all)."""
    return NullPlayer() if muted else Player(device=device, rate=rate)


# ------------------------------------------------------------ echo canceller
class PlaybackReference:
    """What the speakers are playing right now, at the microphone's rate.

    An echo canceller cannot work without this: it subtracts the known render
    signal from what the microphone hears.  The samples are pushed from the
    output stream's callback, so the reference advances on the playback clock
    rather than on when a buffer was queued - a queued buffer is not audible yet
    and would misalign the filter.  Readers ask for the audio that is
    `delay_ms` old, which is when it comes back as echo.
    """

    def __init__(self, max_seconds: float = 2.0, rate: int = C.ASR_RATE):
        self.rate = rate
        self._buf = collections.deque()          # (end_index, samples)
        self._written = 0
        self._max = int(max_seconds * rate)
        self._lock = threading.Lock()

    def push(self, samples: np.ndarray, sample_rate: int) -> None:
        if sample_rate != self.rate:
            samples = resample(samples, sample_rate, self.rate)
        x = np.ascontiguousarray(samples, dtype=np.float32)
        if not x.size:
            return
        with self._lock:
            self._buf.append((self._written + len(x), x))
            self._written += len(x)
            # Long utterances would otherwise grow this without bound; the tail
            # is all anyone asks for.
            while self._buf and self._written - self._buf[0][0] > self._max:
                self._buf.popleft()

    def frame(self, n: int, delay_ms: float) -> np.ndarray:
        """`n` samples that were played `delay_ms` ago (zeros if unknown)."""
        delay = int(self.rate * max(0.0, delay_ms) / 1000.0)
        want_end = self._written - delay
        want_start = want_end - n
        out = np.zeros(n, dtype=np.float32)
        with self._lock:
            for end, chunk in reversed(self._buf):
                start = end - len(chunk)
                if end <= want_start:
                    break
                lo = max(start, want_start)
                hi = min(end, want_end)
                if hi > lo:
                    out[lo - want_start: hi - want_start] = chunk[lo - start: hi - start]
        return out

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


class Aec:
    """WebRTC audio processing: echo cancellation, noise suppression, AGC.

    This replaces a hand-tuned loudness gate.  The gate had to guess how much of
    the microphone signal was the assistant's own voice, and it could only ever
    guess - a linear energy ratio does not hold across volumes, rooms or tracks.
    With the render signal available the echo is actually subtracted, which is
    what makes real barge-in with a speaker (not headphones) possible.

    Frames are processed in 10 ms units, the size the underlying filter expects.
    """

    FRAME = 160                                  # 10 ms at 16 kHz

    def __init__(self, delay_ms: float = C.ECHO_DELAY_MS, noise_suppression: bool = True,
                 agc: bool = False, rate: int = C.ASR_RATE):
        from pywebrtc_audio import AudioProcessor

        self.rate = rate
        self.delay_ms = delay_ms
        self.warmup_frames = int(C.AEC_WARMUP_S * rate / self.FRAME)
        self._frames = 0
        self._ap = AudioProcessor(
            sample_rate=rate,
            echo_cancellation=True,
            noise_suppression=noise_suppression,
            auto_gain_control=agc,
            stream_delay_ms=int(delay_ms),
        )

    @property
    def converged(self) -> bool:
        """False while the adaptive filter is still learning the echo path."""
        return self._frames >= self.warmup_frames

    @property
    def speech_probability(self) -> float:
        try:
            return float(self._ap.speech_probability)
        except Exception:  # noqa: BLE001
            return 0.0

    def process_frame(self, near: np.ndarray, ref: np.ndarray) -> np.ndarray:
        """One 10 ms frame in, one 10 ms frame out."""
        near = np.ascontiguousarray(near[: self.FRAME], dtype=np.float32)
        ref = np.ascontiguousarray(ref[: self.FRAME], dtype=np.float32)
        if ref.size < self.FRAME:
            ref = np.pad(ref, (0, self.FRAME - ref.size))
        if near.size < self.FRAME:
            near = np.pad(near, (0, self.FRAME - near.size))
        self._frames += 1
        return np.asarray(self._ap.process(near, ref), dtype=np.float32)

    def reset(self) -> None:
        try:
            self._ap.reset()
        except Exception:  # noqa: BLE001
            pass
        self._frames = 0


def to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """In-memory wav for HTTP responses."""
    import io

    x = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (x * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
