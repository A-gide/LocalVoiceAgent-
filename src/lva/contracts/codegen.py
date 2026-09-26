"""IPC contract generation chain (pinned).

Pipeline
--------
    Pydantic models
        -> model_json_schema()            (single source of truth)
        -> fail-closed normalize()        (title collisions + union inlining)
        -> typify 0.8.0                   -> Rust
        -> json-schema-to-typescript 16   -> TypeScript

All three artifacts come from one input and are written with LF endings so the
committed bytes are platform independent.

Per Part 4.1 of ARCHITECTURE-PLAN-2026-09-v1.2-COMPOSITE.md, the committed
artifacts may only ever be replaced by a full run of this module; they are
never hand-edited.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .normalize import NormalizeError, canonical_sha256, normalize

__all__ = [
    "REPO_ROOT",
    "SCHEMA_PATH",
    "TS_PATH",
    "RS_PATH",
    "CodegenError",
    "generate_normalized_schema",
    "generate_json_schema",
    "generate_typescript_contracts",
    "generate_rust_contracts",
    "run_codegen",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "schemas" / "lva-ipc-v1.json"
TS_PATH = REPO_ROOT / "apps" / "desktop-ui" / "src" / "generated" / "lva-ipc.ts"
RS_PATH = (
    REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "generated" / "lva_ipc.rs"
)

# Pinned digest of the canonical (pre-normalization) contract.  Changing the
# contract requires re-pinning this on purpose; the chain fails closed otherwise.
# Re-pinned 2026-09-24 for PR-012: the contract gained the inbound
# `hub.attest_bind` command (approved design, hard-constraint-5 authorization).
# Re-pinned 2026-09-25 for PR-024: the contract gained `playback.set_muted` so
# Output Mute reaches the Core instead of changing a local UI ref (approved
# owner authorization, hard-constraint-5).
# Re-pinned 2026-09-26 for FIX-006: the contract gained the inbound `capture.ack`
# command and the outbound `capture.operation_requested` event, so a managed
# capture operation actually reaches the executor that owns the recorder and its
# observed result comes back (approved owner authorization, hard-constraint-5).
EXPECTED_SCHEMA_SHA256 = "aad1911e25f6a0e7fc18c1f2130cf4dd31e521c7808d2ec3b74ace93b432c29f"

_NPM_ROOT = REPO_ROOT / "apps" / "desktop-ui"
_TYPIFY_DRIVER = (
    REPO_ROOT / "tools" / "codegen-rust" / "target" / "release" / "lva-codegen-rust.exe"
)
_TS_DRIVER = _NPM_ROOT / "tools" / "generate-ipc.mjs"


class CodegenError(RuntimeError):
    """Raised when any stage of the chain fails; no artifact is written."""


def _run(command: list[str], *, cwd: Path | None = None, stdin: str | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise CodegenError(
            f"{command[0]} failed (exit {result.returncode}): "
            f"{(result.stderr or '').strip()[:400]}"
        )
    return result.stdout


def generate_normalized_schema() -> tuple[dict, list[str]]:
    """Pydantic schema -> normalized schema (the input to both generators).

    The canonical schema's digest is checked against a pinned expectation before
    anything is normalized or written, so a contract that drifted without the
    pin being updated stops the chain instead of silently producing generators
    for a different contract.  Re-pin with:

        python -m lva.contracts.codegen --print-schema-sha
    """
    from .schema import generate_json_schema as _pydantic_schema

    raw = _pydantic_schema()
    actual = canonical_sha256(raw)
    if actual.lower() != EXPECTED_SCHEMA_SHA256.lower():
        raise CodegenError(
            "canonical schema SHA256 mismatch: "
            f"expected {EXPECTED_SCHEMA_SHA256}, got {actual}. "
            "The contract changed; re-pin EXPECTED_SCHEMA_SHA256 in "
            "src/lva/contracts/codegen.py once the change is intended."
        )
    try:
        return normalize(raw, expected_sha256=EXPECTED_SCHEMA_SHA256)
    except NormalizeError as exc:
        raise CodegenError(f"schema normalization refused: {exc}") from exc


def generate_json_schema() -> dict:
    """The published contract: the *canonical* Pydantic schema.

    The published artifact stays canonical -- it is not rewritten by the Rust
    lowering steps -- so the JSON Schema, the Pydantic runtime, the TypeScript
    types and the Rust types all describe the same contract.
    """
    from .schema import generate_json_schema as _pydantic_schema

    return _pydantic_schema()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def generate_typescript_contracts() -> str:
    normalized, _ = generate_normalized_schema()
    if not _TS_DRIVER.exists():
        raise CodegenError(f"TypeScript generator missing: {_TS_DRIVER}")
    return _run(["node", str(_TS_DRIVER)], cwd=_NPM_ROOT, stdin=json.dumps(normalized))


def generate_rust_contracts() -> str:
    normalized, _ = generate_normalized_schema()
    if not _TYPIFY_DRIVER.exists():
        raise CodegenError(
            f"typify driver missing: {_TYPIFY_DRIVER}\n"
            "build it with: cargo build --release --manifest-path "
            "tools/codegen-rust/Cargo.toml"
        )
    return _run([str(_TYPIFY_DRIVER), "-"], stdin=json.dumps(normalized))


def run_codegen(*, verify_only: bool = False) -> dict[str, str]:
    """Generate all three artifacts, or verify the committed ones match."""
    schema = generate_json_schema()
    ts = generate_typescript_contracts()
    rs = generate_rust_contracts()

    if not ts.endswith("\n"):
        ts += "\n"
    if not rs.endswith("\n"):
        rs += "\n"

    outputs = {
        "schemas/lva-ipc-v1.json": json.dumps(schema, indent=2, ensure_ascii=False),
        "apps/desktop-ui/src/generated/lva-ipc.ts": ts,
        "apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs": rs,
    }
    paths = {
        "schemas/lva-ipc-v1.json": SCHEMA_PATH,
        "apps/desktop-ui/src/generated/lva-ipc.ts": TS_PATH,
        "apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs": RS_PATH,
    }

    digests: dict[str, str] = {}
    mismatched: list[str] = []
    for name, text in outputs.items():
        digests[name] = canonical_sha256(text)
        target = paths[name]
        if verify_only:
            # A verification that does not read the artifact proves nothing.
            if not target.exists():
                mismatched.append(f"{name}: missing")
            elif target.read_text(encoding="utf-8") != text:
                mismatched.append(f"{name}: differs from a fresh generation")
        else:
            _write(target, text)
    if mismatched:
        raise CodegenError("generated artifacts are stale: " + "; ".join(mismatched))
    return digests


if __name__ == "__main__":
    verify = "--verify" in sys.argv
    if "--print-schema-sha" in sys.argv:
        print(canonical_sha256(generate_json_schema()))
        raise SystemExit(0)
    try:
        digests = run_codegen(verify_only=verify)
    except CodegenError as exc:
        print(f"CODEGEN FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    for name, digest in digests.items():
        print(f"{'verified' if verify else 'wrote'} {name}  sha256={digest[:16]}")
