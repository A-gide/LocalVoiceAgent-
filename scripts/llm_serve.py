"""Start / stop / inspect the local llama.cpp server for one GGUF model.

LM Studio ships the llama.cpp runtime but drives it through its GUI.  Running
`llama-server.exe` from that same installation keeps everything local while
giving explicit control over context size, GPU offload and the model alias that
the rest of this project talks to.  Nothing here starts LM Studio itself.

    python scripts/llm_serve.py --list
    python scripts/llm_serve.py --start spark-x2.5-4b --ctx 8192 --ngl 99
    python scripts/llm_serve.py --status
    python scripts/llm_serve.py --stop
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import config as C  # noqa: E402

MODELS_DIRS = [Path(r"W:\model"), C.MODELS / "llm"]
LMSTUDIO_BACKENDS = Path(os.environ.get("USERPROFILE", "")) / ".lmstudio" / "extensions" / "backends"

PID_FILE = C.DATA / "llama-server.pid"
LOG_FILE = C.LOGS / "llama-server.log"
STATE_FILE = C.DATA / "llm-state.json"


_VER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)$")


def _backend_rank(name: str) -> tuple:
    """Rank a backend directory: CUDA12 > CUDA > CPU/Vulkan, then newest version."""
    if "cuda12" in name:
        accel = 3
    elif "cuda" in name:
        accel = 2
    elif "vulkan" in name:
        accel = 1
    else:
        accel = 0
    m = _VER_RE.search(name)
    ver = tuple(int(g) for g in m.groups()) if m else (0, 0, 0)
    return (accel, ver)


def find_server() -> Path:
    """Newest CUDA llama-server shipped with LM Studio, else the best fallback."""
    cands: list[tuple[tuple, Path]] = []
    if LMSTUDIO_BACKENDS.exists():
        for exe in LMSTUDIO_BACKENDS.glob("llama.cpp-*/llama-server.exe"):
            cands.append((_backend_rank(exe.parent.name), exe))
    if not cands:
        raise SystemExit("no llama-server.exe found in LM Studio backends")
    best = max(cands, key=lambda kv: kv[0])
    return best[1]


def discover() -> list[dict]:
    out = []
    for d in MODELS_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.rglob("*.gguf")):
            out.append({
                "id": f.stem.lower().replace("_", "-"),
                "path": str(f),
                "gb": round(f.stat().st_size / 1024**3, 2),
            })
    return out


def resolve(name: str) -> dict:
    models = discover()
    for m in models:
        if m["id"] == name or Path(m["path"]).stem == name:
            return m
    for m in models:
        if name.lower() in m["id"]:
            return m
    raise SystemExit(f"model {name!r} not found. known: {[m['id'] for m in models]}")


def read_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def is_running(pid: int) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and "llama" in psutil.Process(pid).name().lower()
    except Exception:
        return False


def stop() -> bool:
    state = read_state()
    pid = int(state.get("pid") or 0)
    if not is_running(pid):
        print("llama-server not running (or not ours)")
        return False
    import psutil
    p = psutil.Process(pid)
    p.terminate()
    try:
        p.wait(timeout=15)
    except Exception:
        p.kill()
    print(f"stopped llama-server pid={pid}")
    PID_FILE.unlink(missing_ok=True)
    return True


def _launch_env(exe: Path) -> dict[str, str]:
    """PATH for the backend process.

    The CUDA build ships its runtime (cudart/cublas) as a separate "vendor"
    package declared in backend-manifest.json.  LM Studio adds it to PATH before
    spawning llama-server; without that the process dies immediately with
    STATUS_DLL_NOT_FOUND (0xC0000135).
    """
    env = dict(os.environ)
    parts = [str(exe.parent)]
    manifest = exe.parent / "backend-manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for name in data.get("vendor_lib_package_names", []):
                d = LMSTUDIO_BACKENDS / "vendor" / name
                if d.exists():
                    parts.append(str(d))
        except Exception:  # noqa: BLE001
            pass
    env["PATH"] = os.pathsep.join(parts + [env.get("PATH", "")])
    return env


def start(model: str, ctx: int, ngl: int, alias: str, port: int, extra: list[str]) -> int:
    if is_running(int(read_state().get("pid") or 0)):
        stop()
    exe = find_server()
    m = resolve(model)
    # Keep a slice of context for the KV cache inside 8 GB VRAM.
    cmd = [str(exe), "-m", m["path"], "-c", str(ctx), "-ngl", str(ngl),
           "--host", C.SERVICE_HOST, "--port", str(port), "-a", alias,
           "--flash-attn", "on", "--no-webui"]
    cmd += extra
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n")
    log.flush()
    creation = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=creation, env=_launch_env(exe))
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    STATE_FILE.write_text(json.dumps({
        "pid": proc.pid, "model": m["id"], "path": m["path"], "gb": m["gb"],
        "ctx": ctx, "ngl": ngl, "alias": alias, "port": port,
        "exe": str(exe), "started": time.time(),
    }, indent=1), encoding="utf-8")

    import httpx
    url = f"http://{C.SERVICE_HOST}:{port}/v1/models"
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"llama-server exited early with code {proc.returncode}; see {LOG_FILE}")
            return 1
        try:
            r = httpx.get(url, timeout=3)
            if r.status_code == 200:
                print(f"llama-server pid={proc.pid} model={m['id']} ctx={ctx} ngl={ngl} "
                      f"port={port} alias={alias}")
                return 0
        except Exception:
            pass
        time.sleep(1.0)
    print("timed out waiting for llama-server")
    return 2


def status() -> int:
    state = read_state()
    pid = int(state.get("pid") or 0)
    running = is_running(pid)
    print(json.dumps({**state, "running": running}, indent=1, ensure_ascii=False))
    return 0 if running else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--start")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--ctx", type=int, default=C.LLM_CONTEXT)
    ap.add_argument("--ngl", type=int, default=99)
    ap.add_argument("--alias", default=C.LLM_MODEL)
    ap.add_argument("--port", type=int, default=C.LLAMA_SERVER_PORT)
    ap.add_argument("--extra", nargs="*", default=[])
    a = ap.parse_args()

    if a.list:
        for m in discover():
            print(f"{m['id']:45s} {m['gb']:6.2f} GB  {m['path']}")
        return 0
    if a.stop:
        return 0 if stop() else 1
    if a.status:
        return status()
    if a.start:
        return start(a.start, a.ctx, a.ngl, a.alias, a.port, a.extra)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
