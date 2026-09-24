"""End-to-end probe for the PR-012 attestation channel.

What it proves that the unit tests cannot: a verdict produced by the **Rust**
observation shape actually travels over a real authenticated WebSocket into a real
Core, is accepted, and **opens the control gate** -- and that a stale verdict
closes it again.

Shape of the run:

1. start the real ``lva.server`` app on a real uvicorn server (only ``VoiceCore``
   is stubbed, exactly as the R07 interop probe does -- this machine has no audio
   devices and no MeloTTS model);
2. connect a real WebSocket client with the bearer token;
3. send the ``hub.attest_bind`` envelope **in the same JSON shape Rust builds**
   (see ``lib.rs::send_bind_attestation``);
4. assert Core reports ``control_allowed=True`` for a fresh VERIFIED_LOOPBACK;
5. assert a non-loopback verdict and an expired verdict both report ``False``;
6. assert a Hub control command is rejected while unverified and accepted once a
   fresh loopback verdict has arrived.

Usage:  python probe_attestation_e2e.py <port> <token> <ready_file>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

REPO = Path(r"E:\AI\LocalVoiceAgent")

# The data root must be writable.  The repo is read-only to the sandbox, so the
# probe root is taken from the environment (the caller points it at a scratch dir)
# and only falls back to a temp dir.
_root = os.environ.get("LVA_PROBE_ROOT") or os.path.join(os.environ.get("TEMP", "."), "lvaroot-attest")
os.environ["LVA_ROOT"] = _root
os.environ["PYTHONPATH"] = str(REPO / "src")
sys.path.insert(0, str(REPO / "src"))

import uvicorn  # noqa: E402

import lva.server as server  # noqa: E402


class StubCore:
    """Stands in for VoiceCore: no models, no devices, no sound."""

    muted = True
    aec = None
    stats: dict = {}
    asr_name = "stub"
    tts = None

    def __init__(self) -> None:
        self.memory = type("M", (), {"stats": staticmethod(lambda: {})})()
        self.mic = None
        self.player = None
        self._asr: dict = {}
        self.barge_in_calls = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def set_mode(self, mode) -> None:
        pass

    def barge_in(self) -> None:
        self.barge_in_calls += 1

    def load_asr(self, name=None):
        return self

    def vocab(self):  # pragma: no cover - not used by this probe
        raise AssertionError("probe does not drive a turn")


@asynccontextmanager
async def noop_lifespan(app):
    yield


def _attestation(status: str, *, fresh: bool, reason: str | None = None) -> dict:
    """Build the exact JSON shape ``lib.rs::send_bind_attestation`` produces."""
    now = datetime.now(timezone.utc)
    return {
        "status": status,
        "reason_code": reason,
        "checked_at": now.isoformat(),
        "attestation_id": f"probe-{status.lower()}",
        "revalidate_after": (
            (now + timedelta(seconds=90)).isoformat()
            if fresh and status == "VERIFIED_LOOPBACK"
            else ((now - timedelta(seconds=90)).isoformat() if not fresh else None)
        ),
    }


async def run_checks(port: int, token: str) -> list[str]:
    import websockets

    results: list[str] = []
    uri = f"ws://127.0.0.1:{port}/ws"
    async with websockets.connect(
        uri, additional_headers={"Authorization": f"Bearer {token}", "Origin": "tauri://localhost"}
    ) as ws:
        await ws.recv()  # hello
        counter = 0

        async def send(cmd_type: str, payload: dict, precondition: dict | None = None) -> dict:
            nonlocal counter
            counter += 1
            # `command_id` is a UUID in the contract, so a readable prefix like
            # "probe-1" is rejected by the envelope validator before dispatch.
            command_id = str(uuid4())
            envelope = {
                "schema_version": "1.0",
                "command_id": command_id,
                "type": cmd_type,
                "payload": payload,
            }
            if precondition is not None:
                envelope["precondition"] = precondition
            await ws.send(json.dumps(envelope))
            while True:
                raw = json.loads(await ws.recv())
                if raw.get("kind") == "command_result" and raw.get("command_id") == command_id:
                    return raw

        # NOTE on ordering: `execute_command` checks the CAS precondition *before*
        # dispatching, so a Hub control command with a missing or stale
        # precondition is rejected as STALE_REVISION and the attestation gate is
        # never consulted.  Both paths deny (fail-closed holds), but to measure
        # the *gate* every hub.bind_model below carries the current revision.
        def hub_rev() -> dict:
            return {
                "aggregate": "hub_binding",
                "revision": server.get_runtime().hub_binding_revision,
            }

        # 1. Baseline: no attestation has been sent, so control must be denied by
        #    the gate rather than by CAS.
        res = await send(
            "hub.bind_model",
            {"type": "hub.bind_model", "model_id": "probe-model"},
            precondition=hub_rev(),
        )
        code = (res.get("error") or {}).get("code")
        ok = res.get("status") == "rejected" and code == "HUB_BIND_UNVERIFIED"
        results.append(f"{'PASS' if ok else 'FAIL'} no-attestation -> gate denied ({res.get('status')}/{code})")

        # 2. An unverified bind must not open the gate either.
        res = await send(
            "hub.attest_bind",
            {"type": "hub.attest_bind", "attestation": _attestation("UNVERIFIED_BIND", fresh=False, reason="PROBE_FAILED")},
        )
        ok = res.get("status") == "applied" and (res.get("data") or {}).get("control_allowed") is False
        results.append(f"{'PASS' if ok else 'FAIL'} UNVERIFIED_BIND -> control_allowed=False")

        # 3. A fresh VERIFIED_LOOPBACK must open it.
        res = await send(
            "hub.attest_bind",
            {"type": "hub.attest_bind", "attestation": _attestation("VERIFIED_LOOPBACK", fresh=True)},
        )
        ok = res.get("status") == "applied" and (res.get("data") or {}).get("control_allowed") is True
        results.append(f"{'PASS' if ok else 'FAIL'} fresh VERIFIED_LOOPBACK -> control_allowed=True")

        # 4. With the gate open, the same command must get *past* the gate.  It is
        #    no longer a HUB_BIND_UNVERIFIED rejection; whether the saga then finds
        #    a live Hub is out of scope for this probe.
        res = await send(
            "hub.bind_model",
            {"type": "hub.bind_model", "model_id": "probe-model"},
            precondition=hub_rev(),
        )
        code = (res.get("error") or {}).get("code")
        ok = code != "HUB_BIND_UNVERIFIED"
        results.append(f"{'PASS' if ok else 'FAIL'} gate open -> command got past the gate ({res.get('status')}/{code})")

        # 5. An expired verdict must close it again (L665 is a continuing condition).
        res = await send(
            "hub.attest_bind",
            {"type": "hub.attest_bind", "attestation": _attestation("VERIFIED_LOOPBACK", fresh=False)},
        )
        ok = (res.get("data") or {}).get("control_allowed") is False
        results.append(f"{'PASS' if ok else 'FAIL'} expired VERIFIED_LOOPBACK -> control_allowed=False")

        res = await send(
            "hub.bind_model",
            {"type": "hub.bind_model", "model_id": "probe-model"},
            precondition=hub_rev(),
        )
        code = (res.get("error") or {}).get("code")
        ok = res.get("status") == "rejected" and code == "HUB_BIND_UNVERIFIED"
        results.append(f"{'PASS' if ok else 'FAIL'} gate closed again -> denied ({res.get('status')}/{code})")

    return results


def main() -> int:
    port = int(sys.argv[1])
    token = sys.argv[2]
    ready_file = Path(sys.argv[3])

    server.app.router.lifespan_context = noop_lifespan
    server._core = StubCore()
    server.auth_validator.set_token(token)
    server.auth_validator.require_auth = True

    config = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    srv = uvicorn.Server(config)

    import threading

    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()

    deadline = datetime.now(timezone.utc) + timedelta(seconds=20)
    while not srv.started and datetime.now(timezone.utc) < deadline:
        import time

        time.sleep(0.1)
    if not srv.started:
        print("PROBE FAILED: server did not start")
        return 2

    ready_file.write_text(json.dumps({"port": port}), encoding="utf-8")
    try:
        results = asyncio.run(run_checks(port, token))
    except Exception as exc:  # noqa: BLE001
        print(f"PROBE FAILED: {exc!r}")
        return 3

    for line in results:
        print(line, flush=True)
    failed = [r for r in results if r.startswith("FAIL")]
    print(f"summary: {len(results) - len(failed)}/{len(results)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
