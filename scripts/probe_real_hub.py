"""Client-side verification against the REAL running Hub (R22).

Run while the user has the real llama.cpp-hub (0.9.8.3) listening.  This is the
"real Hub" half of the PR-012/013/014/015 acceptance debt that could not be
reached from inside the sandbox (the bundled JVM cannot start here: its
`java.net.http.HttpClient` fails to create a loopback self-pipe).

What it verifies:

1. the real `/api/sys/version` shape -> does `classify_version` reach READY?
2. the real listener table for the Hub port -> what does the PR-008 classifier
   conclude, and does that match plan L579/L1257?
3. the real `/v1` inference face + `/api/models/loaded` shapes;
4. that the Core-side handshake reports what the real Hub actually is.

Usage: python probe_real_hub.py <hub_port>
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(r"E:\AI\LocalVoiceAgent")
os.environ["PYTHONPATH"] = str(REPO / "src")
sys.path.insert(0, str(REPO / "src"))

HUB_DIR = Path(r"D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13")


def _api_key() -> str:
    """Read the local Hub API key without printing it."""
    try:
        cfg = json.loads((HUB_DIR / "config" / "application.json").read_text(encoding="utf-8"))
        return cfg.get("security", {}).get("apiKey", "") or ""
    except Exception:
        return ""


def _netstat_rows(port: int) -> list[str]:
    out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
    return [ln.strip() for ln in out.splitlines() if f":{port}" in ln and "LISTENING" in ln.upper()]


def _classify(address: str) -> str:
    """Mirror of network_attestation::classify for the report."""
    if address in ("127.0.0.1", "::1"):
        return "LoopbackOnly"
    if address == "0.0.0.0":
        return "AllInterfacesV4"
    if address == "::":
        return "AllInterfacesV6"
    return "Unmappable"


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    key = _api_key()
    results: list[str] = []

    # ---- 1. listener table (what PR-008 actually reads)
    rows = _netstat_rows(port)
    results.append(f"listener rows for port {port}: {len(rows)}")
    classes = set()
    for row in rows:
        m = re.match(r"TCP\s+([\d.]+):(\d+)", row)
        if m:
            cls = _classify(m.group(1))
            classes.add(cls)
            results.append(f"  LISTENING {m.group(1)}:{m.group(2)} -> {cls}")
    all_loopback = classes == {"LoopbackOnly"}
    verdict = "VERIFIED_LOOPBACK" if all_loopback else "VERIFIED_NON_LOOPBACK"
    if not classes:
        verdict = "UNVERIFIED_BIND"
    results.append(f"PR-008 classifier verdict = {verdict}")
    results.append(f"control_allowed (plan L665) = {verdict == 'VERIFIED_LOOPBACK'}")

    # ---- 2. HTTP faces
    import httpx

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    base = f"http://127.0.0.1:{port}"
    for path in ("/api/sys/version", "/api/models/loaded", "/api/models/list", "/v1/models"):
        try:
            r = httpx.get(base + path, headers=headers, timeout=10.0)
            body = r.text[:200].replace(chr(10), " ")
            results.append(f"GET {path} -> {r.status_code} {body}")
        except Exception as exc:  # noqa: BLE001
            results.append(f"GET {path} -> FAILED {exc!r}")

    # ---- 3. Core-side handshake against the real Hub
    try:
        from lva.providers.hub_contracts_v0_9_8_3 import classify_version
        from lva.providers.hub_control import LlamaCppHubControlClient

        r = httpx.get(base + "/api/sys/version", headers=headers, timeout=10.0)
        body = r.json()
        # The real envelope nests the payload under `data`; reading the top level
        # would report None and print a misleading DEGRADED here.
        payload = body.get("data") if isinstance(body.get("data"), dict) else body
        reported = payload.get("version") or payload.get("tag")
        results.append(f"reported version = {reported!r} -> classify_version = {classify_version(reported).value}")

        client = LlamaCppHubControlClient(base_url=base, api_key=key)
        import asyncio

        hs = asyncio.run(client.probe_handshake())
        results.append(f"Core probe_handshake() = {hs.value}")
        results.append(f"Core supports(models.load) = {client.supports('models.load')}")
    except Exception as exc:  # noqa: BLE001
        results.append(f"Core-side probe FAILED: {exc!r}")

    for line in results:
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
