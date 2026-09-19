"""E2E audio processing test with speech - talk while audio plays.

Plays a tone through speakers while you talk into the mic.
Saves raw and cleaned recordings so you can verify:
  - Your speech is preserved
  - The speaker tone is removed
  - Background noise is suppressed

Usage:
    python examples/e2e_speech.py

Requires: pip install sounddevice
"""

import wave

import numpy as np
import sounddevice as sd

from pywebrtc_audio import AudioProcessor

RATE = 16000
FRAME_SIZE = 160
DURATION = 10
CHANNELS = 1

ap = AudioProcessor(
    sample_rate=RATE,
    echo_cancellation=True,
    noise_suppression=True,
)

total_frames = int(RATE * DURATION / FRAME_SIZE)
t_all = np.arange(FRAME_SIZE * total_frames) / RATE
far_signal = (np.sin(2 * np.pi * 300 * t_all) * 6000).astype(np.int16)

raw_buf = []
clean_buf = []

print(f"Recording for {DURATION}s - SPEAK into the mic while the tone plays.")
print("Say something like 'hello, testing one two three' a few times.\n")

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

        raw_buf.append(near_frame)
        clean_buf.append(cleaned)

print("\nDone! Saving...")

for name, data in [("speech_raw.wav", raw_buf), ("speech_clean.wav", clean_buf)]:
    samples = np.concatenate(data)
    with wave.open(name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())

print("  speech_raw.wav - your voice + the 300Hz tone + noise")
print("  speech_clean.wav - your voice with tone and noise removed")
print("\nListen to both and compare!")
