"""Command line entry point.

    python -m lva serve                 run the assistant (loopback only)
    python -m lva ask "你好" [--speak]  text turn, no microphone
    python -m lva asr clip.wav          transcribe a file
    python -m lva tts "你好" --out a.wav
    python -m lva devices               list audio devices
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import config as C


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("lva.server:app", host=C.SERVICE_HOST, port=args.port,
                log_level=args.log_level, access_log=False)
    return 0


def cmd_ask(args) -> int:
    import httpx

    body = {"text": args.text, "speak": args.speak, "domain": args.domain}
    r = httpx.post(f"http://{C.SERVICE_HOST}:{args.port}/api/ask", json=body, timeout=300)
    r.raise_for_status()
    d = r.json()
    print(f"raw      : {d['raw']}")
    print(f"corrected: {d['text']}")
    if d["applied"]:
        print(f"applied  : {[a['from'] + '=>' + a['to'] for a in d['applied']]}")
    print(f"domain   : {d['domain']}   history_query: {d['history_query']}")
    if d["hits"]:
        print(f"history  : {len(d['hits'])} hit(s)")
        for h in d["hits"]:
            print(f"           [{h['iso']}] {h['text']}")
    print(f"mode     : {d['llm_mode']}   ttft {d['ttft_ms']}ms   total {d['total_ms']}ms")
    if d.get("tts_ms"):
        print(f"tts      : {d['tts_ms']}ms")
    print(f"reply    : {d['reply']}")
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    return 0


def cmd_asr(args) -> int:
    from . import asr as ASR
    from . import audio as A
    from . import vocab as VO

    samples, sr = A.read_wav(args.wav)
    if sr != C.ASR_RATE:
        samples = A.resample(samples, sr, C.ASR_RATE)
    engine = ASR.load(args.engine or C.LIVE_ASR)
    t0 = time.perf_counter()
    res = engine.transcribe(samples)
    ms = (time.perf_counter() - t0) * 1000
    corrected = VO.correct(ASR.clean(res.text))
    print(f"engine   : {engine.name} ({ms:.0f} ms, {len(samples)/C.ASR_RATE:.2f}s audio)")
    print(f"raw      : {corrected.raw}")
    print(f"corrected: {corrected.corrected}")
    print(f"domain   : {corrected.domain}")
    if corrected.applied:
        print(f"applied  : {[a['from'] + '=>' + a['to'] for a in corrected.applied]}")
    if corrected.flagged:
        print(f"flagged  : {corrected.flagged}")
    return 0


def cmd_tts(args) -> int:
    from . import audio as A
    from . import textutil as TX
    from . import tts as TTS

    eng = TTS.load(args.engine)
    text = TX.strip_for_speech(args.text)
    t0 = time.perf_counter()
    syn = eng.synthesize(text)
    ms = (time.perf_counter() - t0) * 1000
    out = args.out or (C.BENCH / "tts_cli.wav")
    A.write_wav(out, syn.samples, syn.sample_rate)
    print(f"engine : {getattr(eng, 'name', '?')}  voice={getattr(eng, 'voice', '-')}")
    print(f"text   : {text}")
    print(f"audio  : {syn.audio_s:.2f}s @ {syn.sample_rate}Hz   wall {ms:.0f}ms   "
          f"ttfa {syn.ttfa_ms:.0f}ms   rtf {syn.rtf:.3f}")
    print(f"written: {out}")
    return 0


def cmd_devices(args) -> int:
    from . import audio as A

    for d in A.list_devices():
        tags = []
        if d["in"]:
            tags.append(f"in{d['in']}")
        if d["out"]:
            tags.append(f"out{d['out']}")
        print(f"{d['index']:>3}  {d['hostapi']:<18} {','.join(tags):<10} {d['name']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lva", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the assistant server")
    s.add_argument("--port", type=int, default=C.SERVICE_PORT)
    s.add_argument("--log-level", default="info")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("ask", help="text turn through the running server")
    s.add_argument("text")
    s.add_argument("--speak", action="store_true")
    s.add_argument("--domain", default=None)
    s.add_argument("--port", type=int, default=C.SERVICE_PORT)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("asr", help="transcribe a wav file")
    s.add_argument("wav")
    s.add_argument("--engine", default=None)
    s.set_defaults(func=cmd_asr)

    s = sub.add_parser("tts", help="synthesise text to a wav file")
    s.add_argument("text")
    s.add_argument("--engine", default=C.TTS_ENGINE)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_tts)

    s = sub.add_parser("devices", help="list audio devices")
    s.set_defaults(func=cmd_devices)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
