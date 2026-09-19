"""Process wav files through echo cancellation and noise suppression (offline)."""

import argparse
import wave

import numpy as np

from pywebrtc_audio import AudioProcessor


def process_wav(
    near_path: str,
    far_path: str,
    out_path: str,
    ns_level: int = 1,
    stream_delay_ms: int = 0,
) -> None:
    with wave.open(near_path, "rb") as near_wav, wave.open(far_path, "rb") as far_wav:
        assert near_wav.getsampwidth() == 2, "Only 16-bit PCM supported"
        assert near_wav.getframerate() == far_wav.getframerate(), "Sample rates must match"
        assert near_wav.getnchannels() == far_wav.getnchannels(), "Channel counts must match"

        sample_rate = near_wav.getframerate()
        num_channels = near_wav.getnchannels()
        total = min(near_wav.getnframes(), far_wav.getnframes())

        near = np.frombuffer(near_wav.readframes(total), dtype=np.int16)
        far = np.frombuffer(far_wav.readframes(total), dtype=np.int16)

    ap = AudioProcessor(
        sample_rate=sample_rate,
        num_channels=num_channels,
        echo_cancellation=True,
        noise_suppression=True,
        ns_level=ns_level,
        stream_delay_ms=stream_delay_ms,
    )

    cleaned = ap.process(near, far)

    with wave.open(out_path, "wb") as out_wav:
        out_wav.setnchannels(num_channels)
        out_wav.setsampwidth(2)
        out_wav.setframerate(sample_rate)
        out_wav.writeframes(cleaned.tobytes())

    print(f"Processed {len(near)} samples, output: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline echo cancellation")
    parser.add_argument("near", help="Microphone capture wav (contains echo)")
    parser.add_argument("far", help="Speaker reference wav")
    parser.add_argument("out", help="Output wav path")
    parser.add_argument(
        "--ns-level",
        type=int,
        default=1,
        choices=[0, 1, 2, 3],
        help="Noise suppression level (0=6dB, 1=12dB, 2=18dB, 3=21dB)",
    )
    parser.add_argument(
        "--stream-delay-ms",
        type=int,
        default=0,
        help="Audio buffer delay hint in ms for AEC (default: 0 = auto-estimate)",
    )
    args = parser.parse_args()
    process_wav(
        args.near,
        args.far,
        args.out,
        ns_level=args.ns_level,
        stream_delay_ms=args.stream_delay_ms,
    )
