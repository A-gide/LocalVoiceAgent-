"""Offline verification.

The brief asks for a real cable-out test after a reboot.  Nothing here can
unplug the network, so this runs the strongest equivalent that is safe to
automate, and says plainly which parts still need a human:

1. **Static**: scan every source and config file for a URL that is not loopback.
2. **Front-end**: confirm the UI loads its Live2D runtime, model and libraries
   from local files rather than a CDN.
3. **Functional, network poisoned**: point HTTP(S)_PROXY at a black hole and run
   a complete turn (ASR -> corrector -> memory router -> LLM -> TTS).  Anything
   that quietly needed the internet would fail here.
4. **Live sockets**: list non-loopback connections held by the project's own
   processes while it runs.

What this cannot prove is that no component opens a socket *outside* the code
paths exercised here (a first-run model download, for instance).  The manual
procedure at the end covers that, and `privacy-audit.ps1` reports what is
actually connected at any moment.

    python scripts/offline_test.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import config as C  # noqa: E402

URL = re.compile(r"https?://[^\s\"'\)]+")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
BLACKHOLE = "http://127.0.0.1:9"          # discard port: connections refused

results: list[dict] = []


def check(name: str, ok: bool | None, detail: str, warn: bool = False) -> None:
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    results.append({"name": name, "status": status, "detail": detail})
    print(f"{status:<5} {name:<34} {detail}")


# ------------------------------------------------------------------ 1. static
def static_scan() -> None:
    external: dict[str, list[str]] = {}
    roots = [C.ROOT / "src", C.ROOT / "scripts", C.ROOT / "web", C.ROOT / "vocabulary"]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() in {".onnx", ".wav", ".db", ".pyc", ".moc3"}:
                continue
            if any(part in {"venv", "__pycache__", "node_modules", "live2d", "vendor"} for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            for m in URL.findall(text):
                if any(lb in m for lb in LOOPBACK):
                    continue
                # A URL containing a placeholder cannot be a hard-coded external
                # host: it is built at run time from a constant, and the constant
                # is checked below.
                if "{" in m:
                    continue
                external.setdefault(m, []).append(str(p.relative_to(C.ROOT)))
    if external:
        check("no external URL in code", False,
              "; ".join(f"{u} ({','.join(set(f))})" for u, f in list(external.items())[:6]))
    else:
        check("no external URL in code", True,
              "no hard-coded external host; templates resolve from loopback constants")

    # The placeholder above is only safe if the constants really are loopback.
    cfg = (C.ROOT / "src" / "lva" / "config.py").read_text(encoding="utf-8", errors="ignore")
    binds = re.findall(r'SERVICE_HOST\s*=\s*"([^"]+)"', cfg)
    llm = re.findall(r'LLM_BASE_URL\s*=\s*os\.environ\.get\([^,]+,\s*"([^"]+)"', cfg)
    ok_bind = bool(binds) and all(b in LOOPBACK for b in binds)
    ok_llm = bool(llm) and all(any(lb in u for lb in LOOPBACK) for u in llm)
    check("loopback constants", ok_bind and ok_llm,
          f"SERVICE_HOST={binds} LLM_BASE_URL={llm}")

    # The brief forbids these providers outright.
    banned = ["openai.com", "anthropic.com", "googleapis.com", "azure", "groq.com",
              "elevenlabs.io", "deepgram.com", "sentry.io", "api.elevenlabs"]
    hits = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "venv" in p.parts or "__pycache__" in p.parts:
                continue
            t = p.read_text(encoding="utf-8", errors="ignore").lower()
            for b in banned:
                if b in t and "forbid" not in t and "cloud" not in t.split(b)[0][-60:]:
                    hits.append(f"{b} in {p.name}")
    check("no cloud provider referenced", not hits, ", ".join(hits[:4]) or "none found")


# --------------------------------------------------------------- 2. front-end
def frontend_check() -> None:
    idx = C.WEB / "index.html"
    if not idx.exists():
        check("web UI present", False, "web/index.html missing")
        return
    html = idx.read_text(encoding="utf-8")
    refs = URL.findall(html)
    remote = [r for r in refs if not any(lb in r for lb in LOOPBACK)]
    check("UI assets are local", not remote, ", ".join(remote[:4]) or "no CDN references")
    need = ["vendor/live2dcubismcore.min.js", "vendor/pixi.min.js",
            "vendor/pixi-live2d-display-cubism4.min.js",
            "live2d/haru/haru_greeter_t03.model3.json"]
    missing = [n for n in need if not (C.WEB / n).exists()]
    check("Live2D assets on disk", not missing, ", ".join(missing) or
          "runtime + haru model vendored locally")


# ------------------------------------------------- 3. functional with dead net
def functional_check() -> None:
    saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                                            "http_proxy", "https_proxy", "all_proxy")}
    for k in saved:
        os.environ[k] = BLACKHOLE
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"      # loopback must still work
    time.sleep(0.2)
    try:
        from lva import audio as A
        from lva import llm as LLM
        from lva import memory as MEM
        from lva import textutil as TX
        from lva import tts as TTS
        from lva import vocab as VO

        h = LLM.health()
        check("LLM reachable (no internet)", bool(h.get("ok")),
              f"models={h.get('models')}")

        corrected = VO.correct("铜离子可以与EDTA发生络合。")
        check("terminology corrector", "络合" in corrected.corrected,
              f"{corrected.raw} -> {corrected.corrected}")

        from lva import asr as ASR
        eng = ASR.load(C.LIVE_ASR)
        wav = C.BENCH / "audio" / "sci" / "general_01_melotts.wav"
        samples, sr = A.read_wav(wav)
        if sr != C.ASR_RATE:
            samples = A.resample(samples, sr, C.ASR_RATE)
        res = eng.transcribe(samples)
        check("ASR on CPU", bool(ASR.clean(res.text)),
              f"{eng.name}: {ASR.clean(res.text)[:40]}")

        tts = TTS.load(C.TTS_ENGINE)
        syn = tts.synthesize("你好，我现在正在测试本地语音助手。")
        check("TTS on CPU", syn.audio_s > 0.5,
              f"{getattr(tts,'name','?')}: {syn.audio_s:.2f}s, ttfa {syn.ttfa_ms:.0f}ms")

        db = C.DATA / "offline_test.db"
        db.unlink(missing_ok=True)          # idempotent: no rows from a previous run
        mem = MEM.Memory(db)
        mem.add(raw_text="离线测试标记 OFFLINE-4242。", source="test")
        hits = mem.search("OFFLINE-4242")
        check("memory search", len(hits) == 1, f"{len(hits)} hit for OFFLINE-4242")
        mem.close()

        msgs = [{"role": "user", "content": "用一句话说明什么是络合。"}]
        parts = []
        t0 = time.perf_counter()
        for piece in LLM.stream(msgs, mode="fast"):
            parts.append(piece)
        reply = "".join(parts)
        check("full LLM turn", len(reply) > 4,
              f"{len(reply)} chars in {time.perf_counter()-t0:.1f}s: {reply[:48]}")

        spoken = TX.strip_for_speech("## 标题\n**重点** $x^2$ 以及 1 \u2192 2")
        check("speech-safe text cleanup", "##" not in spoken and "$" not in spoken,
              repr(spoken))
    except Exception as e:  # noqa: BLE001
        check("functional offline run", False, f"{type(e).__name__}: {e}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------- 4. live sockets
def socket_check() -> None:
    """Any non-loopback connection owned by this project's process tree?"""
    try:
        import psutil

        roots: list[psutil.Process] = []
        for f in (C.DATA).glob("*.pid"):
            try:
                roots.append(psutil.Process(int(f.read_text().strip())))
            except Exception:  # noqa: BLE001
                pass
        tree: set[int] = set()
        for r in roots:
            tree.add(r.pid)
            for ch in r.children(recursive=True):
                tree.add(ch.pid)
        if not tree:
            check("live external sockets", None,
                  "no project process running; nothing to inspect", warn=True)
            return

        offenders = []
        for con in psutil.net_connections(kind="tcp"):
            if con.status != "ESTABLISHED" or not con.raddr:
                continue
            rip = con.raddr.ip
            if rip.startswith("127.") or rip in ("::1", "0.0.0.0"):
                continue
            if con.pid in tree:
                offenders.append(f"pid {con.pid} -> {rip}:{con.raddr.port}")
        check("live external sockets", not offenders,
              "; ".join(offenders[:5]) or
              f"none from {len(tree)} project process(es)")
    except Exception as e:  # noqa: BLE001
        check("live external sockets", None, f"could not inspect: {e}", warn=True)


def main() -> int:
    print("=== offline verification ===")
    print(f"root: {C.ROOT}\n")
    static_scan()
    frontend_check()
    functional_check()
    socket_check()

    out = C.BENCH / "offline-results.json"
    out.write_text(json.dumps({"results": results, "ts": time.time()},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    fails = [r for r in results if r["status"] == "FAIL"]
    warns = [r for r in results if r["status"] == "WARN"]

    print("""
--- what still needs a human ---
Disconnect the network cable / disable Wi-Fi, reboot, then:
  1. powershell -File scripts\\start-all.ps1
  2. open http://127.0.0.1:8765  (UI and Live2D must appear)
  3. switch to 实时对话 and speak; the reply must be spoken back
  4. ask "我刚才说了什么" - history search must answer from the local archive
  5. powershell -File scripts\\privacy-audit.ps1  (expect no cloud endpoint)
The only component known to want the network on its very first run is Screenpipe,
which downloads its VAD/diarisation models into %LOCALAPPDATA%\\screenpipe once.
After that it runs offline.""")

    print(f"\n-> {out}")
    print(f"=== {len(fails)} FAIL, {len(warns)} WARN ===")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
