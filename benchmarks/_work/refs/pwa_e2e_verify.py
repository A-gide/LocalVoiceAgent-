"""E2E audio processing verification with real mic and speakers.

Plays a tone through your speakers for a few seconds while recording
from your mic. Saves three wav files so you can listen and compare:

  - far.wav:     what was played through the speaker (reference)
  - near_raw.wav: raw mic capture (contains echo + noise)
  - near_clean.wav: mic capture after echo cancellation + noise suppression

Usage:
    python examples/e2e_verify.py

Requires: pip install sounddevice
"""

import wave

import numpy as np
import sounddevice as sd

from pywebrtc_audio import AudioProcessor

RATE = 16000
FRAME_SIZE = 160  # 10ms
DURATION = 5  # seconds
CHANNELS = 1

ap = AudioProcessor(
    sample_rate=RATE,
    echo_cancellation=True,
    noise_suppression=True,
)

total_frames = int(RATE * DURATION / FRAME_SIZE)
far_buf = []
raw_buf = []
clean_buf = []

t_all = np.arange(FRAME_SIZE * total_frames) / RATE
far_signal = (np.sin(2 * np.pi * 440 * t_all) * 8000).astype(np.int16)

print(f"Recording for {DURATION}s - don't speak, just let the echo happen...")
print("(Make sure your speakers are on and mic is near them)")

with sd.Stream(
    samplerate=RATE, blocksize=FRAME_SIZE, channels=CHANNELS, dtype="int16"
) as stream:
    for i in range(total_frames):
        s = i * FRAME_SIZE
        far_frame = far_signal[s : s + FRAME_SIZE]

        stream.write(far_frame.reshape(-1, 1))
        near_frame, _ = stream.read(FRAME_SIZE)
        near_frame = near_frame.flatten()

        cleaned = ap.process(near_frame, far_frame)

        far_buf.append(far_frame)
        raw_buf.append(near_frame)
        clean_buf.append(cleaned)

print("Done! Saving wav files...")

for name, data in [
    ("far.wav", far_buf),
    ("near_raw.wav", raw_buf),
    ("near_clean.wav", clean_buf),
]:
    samples = np.concatenate(data)
    with wave.open(name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())
    rms = np.sqrt(np.mean(samples.astype(float) ** 2))
    print(f"  {name}: RMS={rms:.0f}")

raw_rms = np.sqrt(np.mean(np.concatenate(raw_buf).astype(float) ** 2))
clean_rms = np.sqrt(np.mean(np.concatenate(clean_buf).astype(float) ** 2))
if raw_rms > 0:
    reduction_db = 20 * np.log10(clean_rms / raw_rms)
    print(f"\nEcho reduction: {reduction_db:.1f} dB")

print("\nListen to near_raw.wav vs near_clean.wav to hear the difference.")
