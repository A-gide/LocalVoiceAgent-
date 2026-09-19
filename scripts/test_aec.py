"""Echo-cancellation verification, offline and silent.

The problem being tested is the one that makes speakers unusable without AEC:
the assistant talks through the speaker, the microphone hears that same voice,
and the pipeline cannot tell it apart from the user.

The metric is deliberately *VAD segments*, not transcription.  A loud, clipped
echo is unintelligible to ASR anyway, so measuring transcription would flatter
the result; what actually breaks barge-in is the voice-activity detector firing
on the assistant's own voice, which makes the assistant interrupt itself over and
over.  A real echo path attenuates (speaker-to-microphone gain is well below 1),
so the realistic signal is a quiet, undistorted copy of the assistant.

The exact production components are used - `Aec`, `PlaybackReference`, the same
10 ms framing the microphone runs, and the same Silero VAD - so this exercises
the shipping path.  Nothing is played through the sound card.

    python scripts/test_aec.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import sherpa_onnx as so

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import asr as ASR  # noqa: E402
from lva import audio as A  # noqa: E402
from lva import config as C  # noqa: E402

SR = C.ASR_RATE
FRAME = A.Aec.FRAME

ASSISTANT_TERM = "络合"      # only in the assistant's sentence (chem_01)
USER_TERM = "配位"           # only in the user's sentence (chem_02)


def clip(name: str, gain: float = 1.0) -> np.ndarray:
    x, sr = A.read_wav(C.BENCH / "audio" / "sci" / f"{name}.wav")
    if sr != SR:
        x = A.resample(x, sr, SR)
    return x * gain


def reverb(x: np.ndarray, decay: float = 0.25, taps: int = 6) -> np.ndarray:
    """A crude room: decaying reflections, so the echo is not a bare delay."""
    out = x.copy()
    for i in range(1, taps + 1):
        d = int(SR * 0.021 * i)
        if d >= len(x):
            break
        out[d:] += x[:-d] * (decay ** i)
    return out


def build(delay_ms: int, echo_gain: float, user_gain: float,
          user_start_s: float, total_s: float):
    """(playback, microphone, user-only, user_start, user_end)."""
    tts = clip("chem_01_melotts")
    user = clip("chem_02_sapi")
    n = int(total_s * SR)
    play = np.zeros(n, dtype=np.float32)
    play[: min(len(tts), n)] = tts[: min(len(tts), n)]

    d = int(delay_ms / 1000 * SR)
    echo = np.concatenate([np.zeros(d, dtype=np.float32), reverb(play)])[:n] * echo_gain
    us = int(user_start_s * SR)
    end = min(n, us + len(user))
    usr = np.zeros(n, dtype=np.float32)
    usr[us:end] = user[: end - us] * user_gain
    return play, echo + usr, usr, us, end


def cancel(play: np.ndarray, mic: np.ndarray, delay_ms: int) -> np.ndarray:
    """Run the scenario through the production AEC + reference classes."""
    aec = A.Aec(delay_ms=delay_ms, noise_suppression=True, agc=False)
    ref = A.PlaybackReference()
    out = np.zeros_like(mic)
    for i in range(0, len(mic) - FRAME + 1, FRAME):
        ref.push(play[i:i + FRAME], SR)
        # No extra shift: see the comment in Microphone._callback.
        out[i:i + FRAME] = aec.process_frame(mic[i:i + FRAME], ref.frame(FRAME, 0.0))
    return out


def vad_segments(x: np.ndarray, threshold: float = 0.5) -> list[float]:
    """Silero VAD over a signal; returns the length of each detected segment."""
    cfg = so.VadModelConfig()
    cfg.silero_vad.model = str(C.SILERO_VAD)
    cfg.silero_vad.threshold = threshold
    cfg.silero_vad.min_silence_duration = 0.25
    cfg.silero_vad.min_speech_duration = 0.10
    cfg.silero_vad.max_speech_duration = 30.0
    cfg.silero_vad.window_size = C.VAD_WINDOW
    cfg.sample_rate = SR
    vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
    segs: list[float] = []
    for i in range(0, len(x) - C.VAD_WINDOW + 1, C.VAD_WINDOW):
        vad.accept_waveform(x[i:i + C.VAD_WINDOW])
        while not vad.empty():
            segs.append(len(vad.front.samples) / SR)
            vad.pop()
    return segs


def erle_dB(a: np.ndarray, b: np.ndarray) -> float:
    return 10 * float(np.log10((A.rms(a) + 1e-12) / (A.rms(b) + 1e-12)))


def main() -> int:
    engine = ASR.load(C.LIVE_ASR)
    print("=== echo cancellation verification (offline, silent) ===")
    print()
    results: dict = {"self_hearing": [], "talkover": {},
                     "delay_ms_default": int(C.ECHO_DELAY_MS)}

    # -- Part 1: only the assistant is talking.  Without cancellation the VAD
    # fires on the echo, which is what makes the assistant interrupt itself.
    print("-- assistant speaking alone: does the VAD fire on its own voice? --")
    print(f"  {'delay':>8} {'gain':>6} {'raw segs':>9} {'AEC segs':>9} {'ERLE':>8}")
    for delay_ms, gain in ((60, 0.30), (60, 0.60), (100, 0.30), (40, 0.60)):
        play, mic, _usr, _us, _end = build(delay_ms, gain, 0.0, 2.0, 6.0)
        win = slice(int(0.5 * SR), int(5.5 * SR))
        clean = cancel(play, mic, delay_ms)
        raw_segs = vad_segments(mic[win])
        aec_segs = vad_segments(clean[win])
        raw_asr = engine.transcribe(mic[win]).text
        aec_asr = engine.transcribe(clean[win]).text
        results["self_hearing"].append({
            "delay_ms": delay_ms, "echo_gain": gain,
            "erle_dB": round(erle_dB(mic[win], clean[win]), 1),
            "raw_segments": len(raw_segs), "aec_segments": len(aec_segs),
            "raw_vad_fires": len(raw_segs) > 0,
            "aec_vad_fires": len(aec_segs) > 0,
            "raw_heard_itself": ASSISTANT_TERM in raw_asr,
            "aec_heard_itself": ASSISTANT_TERM in aec_asr,
            "raw_asr": raw_asr, "aec_asr": aec_asr})
        print(f"  {delay_ms:6d}ms {gain:6.2f} {len(raw_segs):9d} {len(aec_segs):9d} "
              f"{results['self_hearing'][-1]['erle_dB']:6.1f} dB")

    # -- Part 2: the user talks over the assistant and must stay detectable.
    print()
    print("-- user talking over the assistant: is the user still detected? --")
    play, mic, usr, us, end = build(int(C.ECHO_DELAY_MS), 0.30, 0.55, 2.0, 8.0)
    both = slice(us + int(0.2 * SR), end)
    clean = cancel(play, mic, int(C.ECHO_DELAY_MS))
    user_txt = engine.transcribe(usr[both]).text
    aec_txt = engine.transcribe(clean[both]).text
    keep = erle_dB(usr[both], clean[both])
    user_ok = USER_TERM in aec_txt
    assistant_gone = ASSISTANT_TERM not in aec_txt
    results["talkover"] = {
        "user_alone_asr": user_txt, "aec_asr": aec_txt,
        "user_retained_dB": round(-keep, 1), "user_still_audible": user_ok,
        "assistant_absent": assistant_gone, "pass": bool(user_ok and assistant_gone)}
    print(f"  user alone      : {user_txt}")
    print(f"  after AEC       : {aec_txt}")
    print(f"  user retained   : {-keep:5.1f} dB versus the user alone")
    print(f"  -> user audible={user_ok}  assistant absent={assistant_gone}  "
          f"{'PASS' if user_ok and assistant_gone else 'FAIL'}")

    # -- Part 3: why a loudness gate could not do this.
    play, mic, _usr, _us, _end = build(int(C.ECHO_DELAY_MS), 0.30, 0.0, 2.0, 6.0)
    echo_rms = A.rms(mic[int(1.0 * SR):int(5.0 * SR)])
    note = ("the assistant's echo alone measures %.4f rms against an interruption "
            "floor of %.4f; a gate that ignores the echo therefore also ignores user "
            "speech quieter than the echo, which is why barge-in with speakers needs "
            "cancellation and not a threshold" % (echo_rms, C.BARGE_FLOOR))
    results["gate_note"] = note
    print()
    print("-- why the old loudness gate could not do this --")
    print("  " + note)

    out = C.BENCH / "aec-verification.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    fixed = [r for r in results["self_hearing"] if r["raw_vad_fires"] and not r["aec_vad_fires"]]
    ok = bool(results["talkover"].get("pass")) and bool(fixed)
    print()
    print(f"  configurations where AEC stopped the self-trigger: "
          f"{len(fixed)}/{len(results['self_hearing'])}")
    print(f"  -> {out}")
    print(f"=== {'PASS' if ok else 'FAIL'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
