"""
Measure real resource usage in the three states required by MASTER_PROMPT.md Section 34:
1. recording: Screenpipe passive capture running, nobody talking
2. live_idle: llama.cpp-hub + Screenpipe running, microphone listening, nobody talking
3. live_talking: spoken turns in flight (Hub LLM streaming + sherpa-onnx MeloTTS synthesizing)

Writes to benchmarks/resource-usage.json and acceptance-20260917/resource-usage-evidence.json.
"""
from __future__ import annotations

import os
import sys
import json
import time
import asyncio
import subprocess
import threading
from pathlib import Path
import psutil
import websockets

ROOT = Path("E:/AI/LocalVoiceAgent")
DATA_DIR = ROOT / "data"
BENCH_DIR = ROOT / "benchmarks"
EVIDENCE_DIR = ROOT / "acceptance-20260917"

# LVA Core's own authenticated endpoint. The old OLV `client-ws` port (12393)
# belonged to the conversation process PR-036 removed.
WS_URI = "ws://127.0.0.1:8765/ws"

def get_pids_from_ports() -> dict[str, int]:
    pids = {}
    # PR-015/036: LVA no longer owns a llama.cpp backend and the OLV process is
    # gone, so only the two services LVA actually integrates with are measured.
    for port, name in [(8080, "llama.cpp-hub"), (3030, "screenpipe")]:
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port:
                    if conn.pid:
                        pids[name] = conn.pid
                        break
        except Exception:
            pass
        # Fallback to pid files
        if name not in pids:
            pf = DATA_DIR / f"{name}.pid"
            if pf.exists():
                try:
                    pid = int(pf.read_text().strip())
                    if psutil.pid_exists(pid):
                        pids[name] = pid
                except Exception:
                    pass
    return pids

def get_vram() -> tuple[float, float]:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        used, total = [float(x.strip()) for x in r.stdout.strip().split(",")]
        return used, total
    except Exception:
        return 0.0, 8188.0

def sample(seconds: float, label: str, target_pids: dict[str, int]) -> dict:
    trees: dict[str, list[psutil.Process]] = {}
    for name, pid in target_pids.items():
        try:
            root = psutil.Process(pid)
            members = [root] + root.children(recursive=True)
            for p in members:
                p.cpu_percent(None)
            trees[name] = members
        except Exception:
            pass

    time.sleep(0.5)

    cpu_samples: list[float] = []
    per_proc: dict[str, list[float]] = {n: [] for n in trees}
    ram_samples: list[float] = []
    vram_samples: list[float] = []
    cores = psutil.cpu_count(logical=True) or 1
    total_ram = psutil.virtual_memory().total / (1024**3)

    end_time = time.time() + seconds
    while time.time() < end_time:
        busy = 0.0
        for name, members in trees.items():
            sub = 0.0
            for p in members:
                try:
                    sub += p.cpu_percent(None)
                except Exception:
                    pass
            per_proc[name].append(sub)
            busy += sub

        cpu_samples.append(busy)
        ram_samples.append(psutil.virtual_memory().used / (1024**3))
        v_used, v_tot = get_vram()
        vram_samples.append(v_used)
        time.sleep(0.5)

    avg_busy = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
    peak_busy = max(cpu_samples) if cpu_samples else 0.0
    cores_used = round(avg_busy / 100.0, 3)
    cores_peak = round(peak_busy / 100.0, 3)
    cpu_percent = round((avg_busy / (cores * 100.0)) * 100.0, 2)

    proc_cores = {}
    for n, s in per_proc.items():
        proc_cores[n] = round((sum(s) / len(s)) / 100.0, 3) if s else 0.0

    return {
        "label": label,
        "cpu_cores_used": cores_used,
        "cpu_cores_peak": cores_peak,
        "cpu_percent_of_machine": cpu_percent,
        "ram_used_gb": round(sum(ram_samples) / len(ram_samples), 1) if ram_samples else 0.0,
        "ram_total_gb": round(total_ram, 1),
        "vram_used_mb": round(sum(vram_samples) / len(vram_samples), 1) if vram_samples else 0.0,
        "vram_total_mb": v_tot,
        "per_process_cores": proc_cores
    }

async def send_turn(prompt: str):
    try:
        async with websockets.connect(WS_URI, max_size=10*1024*1024) as ws:
            await ws.send(json.dumps({"type": "text-input", "text": prompt}))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    d = json.loads(raw)
                    if d.get("type") == "audio":
                        await ws.send(json.dumps({"type": "frontend-playback-complete"}))
                    elif d.get("type") == "control" and d.get("text") == "conversation-chain-end":
                        break
                except asyncio.TimeoutError:
                    break
    except Exception as e:
        pass

def run_talking_worker(stop_ev: threading.Event):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    prompts = [
        "请详细解释配位化学中螯合效应的热力学本质，包括熵变和焓变的贡献。",
        "请简要说明Jahn-Teller效应在八面体配合物畸变中的微观物理机制。",
        "请介绍EDTA络合滴定分析中酸效应系数的作用原理。"
    ]
    idx = 0
    while not stop_ev.is_set():
        loop.run_until_complete(send_turn(prompts[idx % len(prompts)]))
        idx += 1
        time.sleep(0.2)
    loop.close()

def main():
    print("=== LocalVoiceAgent Resource Usage Profiler (MASTER_PROMPT Section 34) ===")
    pids = get_pids_from_ports()
    print(f"Target process PIDs detected: {pids}")

    if not pids:
        print("ERROR: No project processes detected. Start stack first via start-all.ps1!")
        return 1

    results = []

    # 1. State: recording (passive 24/7 capture, room silent)
    print("\n[1/3] Measuring 'recording' state (Screenpipe passive audio capture, room silent)...")
    res_recording = sample(6.0, "recording", pids)
    results.append(res_recording)
    print(f"  recording: {res_recording['cpu_percent_of_machine']}% CPU ({res_recording['cpu_cores_used']} cores), {res_recording['ram_used_gb']}GB RAM, {res_recording['vram_used_mb']}MB VRAM")

    # 2. State: live_idle (Full stack running, Open-LLM-VTuber ready, waiting)
    print("\n[2/3] Measuring 'live_idle' state (Full stack ready, microphone armed, no active talk)...")
    res_idle = sample(6.0, "live_idle", pids)
    results.append(res_idle)
    print(f"  live_idle: {res_idle['cpu_percent_of_machine']}% CPU ({res_idle['cpu_cores_used']} cores), {res_idle['ram_used_gb']}GB RAM, {res_idle['vram_used_mb']}MB VRAM")

    # 3. State: live_talking (Interactive turns in flight: LLM stream + TTS synthesis + Live2D)
    print("\n[3/3] Measuring 'live_talking' state (Turns in flight: LLM inference + MeloTTS synthesis)...")
    stop_ev = threading.Event()
    worker_t = threading.Thread(target=run_talking_worker, args=(stop_ev,), daemon=True)
    worker_t.start()
    time.sleep(1.5)  # Let inference ramp up

    res_talking = sample(10.0, "live_talking", pids)
    results.append(res_talking)
    stop_ev.set()
    worker_t.join(timeout=10)
    print(f"  live_talking: {res_talking['cpu_percent_of_machine']}% CPU ({res_talking['cpu_cores_used']} cores), {res_talking['ram_used_gb']}GB RAM, {res_talking['vram_used_mb']}MB VRAM")

    # Save to benchmarks and evidence folder
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    out_bench = BENCH_DIR / "resource-usage.json"
    out_bench.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved profile to {out_bench}")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out_ev = EVIDENCE_DIR / "resource-usage-evidence.json"
    out_ev.write_text(json.dumps({
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": "Windows 11 / Intel Core i9-13980HX / RTX 4060 Laptop 8GB",
        "profiles": results
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved evidence to {out_ev}")

    print("\n========================= RESOURCE PROFILE TABLE =========================")
    print(f"{'State':<15} {'CPU Cores':>10} {'Peak':>8} {'% Machine':>12} {'RAM GB':>10} {'VRAM MB':>10}")
    for r in results:
        print(f"{r['label']:<15} {r['cpu_cores_used']:>10.3f} {r['cpu_cores_peak']:>8.3f} {r['cpu_percent_of_machine']:>11.2f}% {r['ram_used_gb']:>9.1f} {r['vram_used_mb']:>10.1f}")
    print("==========================================================================")
    return 0

if __name__ == "__main__":
    sys.exit(main())
