"""Minimal usage of all processors: echo cancellation, noise suppression, and gain control.

Creates synthetic scenarios to demonstrate each component standalone
and then the combined AudioProcessor pipeline.
"""

import numpy as np

from pywebrtc_audio import AudioProcessor, EchoCanceller, GainController, NoiseSuppressor

frame_size = 160  # 10ms at 16kHz
t = np.arange(frame_size) / 16000

# far = what the speaker is playing (440Hz tone)
# near = what the mic picks up (just echo, no speech)
far = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
near = (far * 0.3).astype(np.int16)

input_energy = np.sum(near.astype(float) ** 2)

# --- Standalone: chain EchoCanceller + NoiseSuppressor ---
ec = EchoCanceller(sample_rate=16000)
ns = NoiseSuppressor(sample_rate=16000)

cleaned = ec.process(near, far)
cleaned = ns.process(cleaned)

print(f"AEC + NS   - Input energy: {input_energy:.0f}  Output energy: {np.sum(cleaned.astype(float) ** 2):.0f}")

# --- Standalone: GainController amplifies quiet audio ---
gc = GainController(sample_rate=16000)
rng = np.random.default_rng(42)
quiet = (rng.standard_normal(16000) * 100).astype(np.int16)
amplified = gc.process(quiet)

print(f"AGC        - Input mean: {np.abs(quiet).mean():.0f}  Output mean: {np.abs(amplified).mean():.0f}  Gain: {gc.gain_db:.1f} dB")

# --- Combined: single AudioProcessor pass (shared buffers, less overhead) ---
ap = AudioProcessor(
    sample_rate=16000,
    echo_cancellation=True,
    noise_suppression=True,
    auto_gain_control=True,
)

cleaned = ap.process(near, far)

print(f"Combined   - Input energy: {input_energy:.0f}  Output energy: {np.sum(cleaned.astype(float) ** 2):.0f}")

# --- Reset: clear internal state between conversations ---
ap.reset()
gc.reset()
