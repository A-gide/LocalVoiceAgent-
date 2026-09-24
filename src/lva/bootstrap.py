from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from uuid import UUID, uuid4

log = logging.getLogger("lva.bootstrap")

# The bootstrap handshake is the single source of the runtime instance identity.
# ``server.get_runtime()`` must adopt this value instead of minting its own, or the
# id announced in ``LVA_READY`` never matches the id published in ``RuntimeState``
# and the Rust bridge misreads every first event as an instance change.
_announced_instance_id: UUID | None = None


def announce_runtime_instance_id(instance_id: UUID) -> None:
    """Record the instance id announced to the parent via ``LVA_READY``."""
    global _announced_instance_id
    _announced_instance_id = instance_id


def get_announced_runtime_instance_id() -> UUID | None:
    """The instance id already announced, or ``None`` outside bootstrap mode."""
    return _announced_instance_id


@dataclass
class BootstrapConfig:
    protocol_version: int
    token: str
    nonce: str
    parent_pid: int | None = None
    # ``default_factory`` is required: a bare ``= uuid4()`` is evaluated once at
    # class-definition time, so every construction that omits the argument would
    # silently share a single instance id.
    runtime_instance_id: UUID = field(default_factory=uuid4)


def read_bootstrap_from_stdin() -> BootstrapConfig:
    """Read bootstrap token and nonce from parent process via stdin.

    Expected JSON line:
    {"protocol_version":1,"token":"base64url-256-bit","nonce":"uuid","parent_pid":1234}
    """
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("Empty stdin: failed to read bootstrap JSON from parent process")

    try:
        data = json.loads(line.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON on bootstrap stdin: {exc}") from exc

    protocol_version = data.get("protocol_version")
    if protocol_version != 1:
        raise RuntimeError(
            f"Unsupported protocol_version: {protocol_version}, expected 1"
        )

    token = data.get("token")
    if not token or not isinstance(token, str):
        raise RuntimeError("Missing or invalid 'token' in bootstrap payload")

    nonce = data.get("nonce")
    if not nonce or not isinstance(nonce, str):
        raise RuntimeError("Missing or invalid 'nonce' in bootstrap payload")

    parent_pid = data.get("parent_pid")
    return BootstrapConfig(
        protocol_version=protocol_version,
        token=token,
        nonce=nonce,
        parent_pid=int(parent_pid) if parent_pid is not None else None,
        runtime_instance_id=uuid4(),
    )


def emit_lva_ready(
    port: int,
    nonce: str,
    runtime_instance_id: UUID,
    protocol_version: int = 1,
) -> None:
    """Emit the single-line machine-readable readiness event to stdout.

    Format:
    LVA_READY {"protocol_version":1,"port":49152,"nonce":"uuid","runtime_instance_id":"uuid"}
    """
    payload = {
        "protocol_version": protocol_version,
        "port": port,
        "nonce": str(nonce),
        "runtime_instance_id": str(runtime_instance_id),
    }
    announce_runtime_instance_id(runtime_instance_id)
    line = f"LVA_READY {json.dumps(payload, separators=(',', ':'))}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    log.info("Emitted LVA_READY on port %d, nonce %s", port, nonce)
