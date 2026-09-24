"""v1.2.1 quality harness (PR-022).

Provides deterministic, side-effect-free building blocks for the v1.2.1 RED
suite:

* ``DeterministicClock``      - stable timestamps, no wall-clock coupling
* ``FakeProvider`` family     - ASR / LLM / TTS doubles with call counters and
                                crash injection (invariant I07/I08/I12)
* ``EventRecorder``           - captures event envelopes in emission order
* ``ArtifactWriter``          - writes failure artifacts with secrets, absolute
                                paths and transcripts scrubbed (I20)
* ``RevisionProbe``           - drives the real command dispatcher so aggregate
                                CAS and heartbeat-vs-CAS non-conflict are
                                observable (v1.2.1 section 4.2 / 4.4)
* ``TurnProbe``               - drives real turns, interrupts and gates so a
                                superseded turn, a late effect and a provider
                                fault are reproducible (I01 / I02 / I15)

Design rules:
* No network, no audio device, no real Hub, no real Journal file.
* Every artifact that leaves this module passes through ``redact``.
* Nothing here asserts product behaviour - assertions live in the RED tests.
"""
from __future__ import annotations

import json
import ast
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

try:  # pragma: no cover - optional import, harness degrades gracefully
    from lva.observability.redact import redact_dict, redact_string
except Exception:  # pragma: no cover
    def redact_string(v: str) -> str:  # type: ignore[misc]
        return v

    def redact_dict(v: Any) -> Any:  # type: ignore[misc]
        return v


# --------------------------------------------------------------------- clock
@dataclass
class DeterministicClock:
    """Monotonic, reproducible clock. Never reads the wall clock."""

    start: datetime = field(
        default_factory=lambda: datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone.utc)
    )
    _ticks: int = 0

    def now(self) -> datetime:
        value = self.start + timedelta(milliseconds=self._ticks)
        self._ticks += 1
        return value

    def advance(self, milliseconds: int) -> None:
        self._ticks += milliseconds


# ------------------------------------------------------------------ recorder
@dataclass
class EventRecorder:
    """Collects event envelopes in emission order."""

    events: list[Any] = field(default_factory=list)

    def __call__(self, envelope: Any) -> None:
        self.events.append(envelope)

    # -- introspection helpers used by the RED tests -----------------------
    def types(self) -> list[str]:
        return [getattr(e, "type", None) or _as_dict(e).get("type") for e in self.events]

    def sequences(self) -> list[int]:
        out = []
        for e in self.events:
            seq = getattr(e, "sequence", None)
            if seq is None:
                seq = _as_dict(e).get("sequence")
            out.append(seq)
        return out

    def by_type(self, event_type: str) -> list[Any]:
        return [e for e in self.events if (getattr(e, "type", None) or _as_dict(e).get("type")) == event_type]

    def clear(self) -> None:
        self.events.clear()


def _as_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return {}


# ----------------------------------------------------------------- providers
@dataclass
class FakeProvider:
    """Deterministic provider double with call accounting.

    ``calls`` counts every invocation so that invariant I07/I08
    ("Passive never calls LLM/TTS") can be asserted as ``calls == 0``.
    """

    name: str
    kind: str  # "asr" | "llm" | "tts"
    fail_with: Exception | None = None
    calls: int = 0
    cancelled: int = 0

    def _enter(self) -> None:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with

    # -- ASR ---------------------------------------------------------------
    def transcribe(self, samples: Any) -> Any:  # noqa: ANN401
        self._enter()
        return type("ASRResult", (), {"text": "fake transcript", "raw": "fake transcript"})()

    # -- LLM ---------------------------------------------------------------
    def stream(self, messages: Any, **kwargs: Any) -> Iterable[str]:  # noqa: ANN401
        self._enter()
        yield "fake "
        yield "reply"

    # -- TTS ---------------------------------------------------------------
    def synthesize(self, text: str) -> Any:  # noqa: ANN401
        self._enter()
        return type(
            "Synth",
            (),
            {"samples": [0.0], "sample_rate": 16000, "ttfa_ms": 0.0, "audio_s": 0.0, "rtf": 0.0},
        )()


@dataclass
class FakeProviderSet:
    asr: FakeProvider = field(default_factory=lambda: FakeProvider("fake-asr", "asr"))
    llm: FakeProvider = field(default_factory=lambda: FakeProvider("fake-llm", "llm"))
    tts: FakeProvider = field(default_factory=lambda: FakeProvider("fake-tts", "tts"))

    def reset(self) -> None:
        for p in (self.asr, self.llm, self.tts):
            p.calls = 0
            p.cancelled = 0
            p.fail_with = None


# -------------------------------------------------------------------- probes
def new_dispatcher() -> Any:
    """Build the real dispatcher: RuntimeController over an in-memory Journal.

    The Journal is :memory:, so a probe can never touch the user's real
    data/journal.sqlite3.
    """
    from lva.core.runtime import RuntimeController
    from lva.journal.repository import JournalRepository

    return RuntimeController(journal=JournalRepository(":memory:"))


def mode_command(mode: Any, revision: int | None) -> Any:
    """A runtime.set_mode envelope; revision=None omits the precondition."""
    from lva.contracts.commands import CommandEnvelope, RuntimeSetModePayload
    from lva.contracts.enums import Mode

    precondition = None
    if revision is not None:
        precondition = {"aggregate": "runtime_control", "revision": revision}
    return CommandEnvelope(
        schema_version="1.0",
        type="runtime.set_mode",
        payload=RuntimeSetModePayload(type="runtime.set_mode", mode=Mode(mode)),
        precondition=precondition,
    )


@dataclass
class RevisionProbe:
    """Drives the real dispatcher so aggregate CAS is observable (v1.2.1 4.2/4.4).

    Every reading goes through execute_command or a published controller
    property, so a green result reflects the product's own CAS semantics rather
    than a value the probe wrote down.
    """

    controller: Any = field(default_factory=new_dispatcher)

    def revision(self, aggregate: str) -> int:
        """Current aggregate revision, read from the controller itself."""
        name = f"{aggregate}_revision"
        value = getattr(self.controller, name, None)
        if not isinstance(value, int):
            raise AttributeError(f"RuntimeController has no integer {name}")
        return value

    def snapshot_version(self) -> int:
        return int(self.controller.snapshot_version)

    def heartbeat(self, activity: str = "thinking") -> None:
        """Real heartbeat traffic: an activity publish, not a command."""
        from lva.contracts.enums import ActivityState

        self.controller.set_activity(ActivityState(activity))

    def dispatch(self, command: Any) -> Any:
        return self.controller.execute_command(command)

    def set_mode(self, mode: str = "live", revision: int | None = None) -> Any:
        """Dispatch runtime.set_mode; revision=None reads the current one."""
        target = self.revision("runtime_control") if revision is None else revision
        return self.dispatch(mode_command(mode, target))

    def set_mode_without_precondition(self, mode: str = "live") -> Any:
        return self.dispatch(mode_command(mode, None))


@dataclass
class TurnProbe:
    """Drives real turns, interrupts and gates on a live RuntimeController.

    Uses the same TurnController / InterruptController / StaleEffectGate objects
    the product wires together, so late-turn suppression is exercised on the
    production path (I01 / I02 / I15) instead of on a stand-in.
    """

    controller: Any = field(default_factory=new_dispatcher)
    providers: FakeProviderSet = field(default_factory=FakeProviderSet)

    def live_session(self) -> Any:
        """Put the controller in Live with an open session and return its id."""
        from lva.contracts.enums import Mode

        rt = self.controller
        rt.set_mode(Mode.LIVE)
        if rt.session_controller.current_session_id is None:
            rt.session_controller.start_session()
        return rt.session_controller.current_session_id

    def start_turn(self, text: str = "probe turn") -> tuple[Any, int]:
        """Create a turn and capture the epoch it belongs to."""
        session_id = self.live_session()
        turn = self.controller.turn_controller.create_turn(session_id, user_text=text)
        return turn, self.controller.current_epoch

    def interrupt(self, reason: str = "barge_in") -> int:
        return self.controller.interrupt_controller.commit_interrupt(reason=reason)

    def gates_pass(self, turn: Any, epoch: int) -> tuple[bool, bool, bool]:
        """The three real gates, in dispatch / in-stream / pre-side-effect order."""
        gate = self.controller.stale_gate
        return (
            gate.check_gate1_pre_dispatch(turn, epoch),
            gate.check_gate2_in_stream(turn, epoch),
            gate.check_gate3_pre_side_effect(turn, epoch, "playback"),
        )

    def stream_with_fault(self, error: Exception) -> tuple[bool, str]:
        """Stream through the LLM double with crash injection (I12).

        Returns (raised, exception_type). On a raise the probe performs the same
        recovery the Core performs: cancel the active turn with reason
        provider_crash while leaving the session and Journal intact.
        """
        self.providers.llm.fail_with = error
        try:
            list(self.providers.llm.stream([]))
        except Exception as exc:  # noqa: BLE001 - the point is to observe any raise
            current = self.controller.turn_controller.current_turn
            if current is not None:
                self.controller.turn_controller.cancel_turn(current, reason="provider_crash")
            return True, type(exc).__name__
        return False, ""

    def journal_integrity(self) -> str:
        """SQLite integrity check on the probe's own in-memory Journal."""
        journal = getattr(self.controller, "_journal", None)
        if journal is None:
            raise AttributeError("probe controller has no journal")
        return str(journal.conn.execute("PRAGMA integrity_check;").fetchone()[0])


# ------------------------------------------------------------------ artifacts
_WIN_PATH = r"[A-Za-z]:\\{1,2}(?:[^\\\s\"']+\\{1,2})+[^\\\s\"']*"
_POSIX_PATH = r"/(?:home|Users)/[^\s\"']+"

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"dpapi:[A-Za-z0-9+/=]+"),
    re.compile(_WIN_PATH),    # absolute Windows paths (requires >=1 separator)
    re.compile(_POSIX_PATH),  # absolute POSIX home paths
]


def assert_no_sensitive(text: str) -> None:
    """Fail if an artifact leaks a secret, a path or a raw transcript."""
    for pat in _SECRET_PATTERNS:
        m = pat.search(text)
        assert m is None, f"artifact leaked sensitive pattern {pat.pattern!r}: {m.group(0)[:24]!r}..."


# Value-level scrubbing applied on top of ``lva.observability.redact``.
# The product redactor is key-based and does NOT cover DPAPI blobs or trailing
# absolute-path fragments, so the harness enforces its own floor (see
# test_red_redaction.py for the product-level RED case).
_EXTRA_SCRUB: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"dpapi:[A-Za-z0-9+/=]+"), "[DPAPI_BLOB]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-[REDACTED]"),
    (re.compile(_WIN_PATH), "[PATH]"),
    (re.compile(_POSIX_PATH), "[PATH]"),
]


def scrub_string(value: str) -> str:
    """Apply the product redactor plus the harness's own value-level floor."""
    out = redact_string(value)
    for pat, repl in _EXTRA_SCRUB:
        out = pat.sub(repl, out)
    return out


def scrub(obj: Any) -> Any:
    """Recursively scrub a JSON-like structure."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        return scrub_string(obj)
    return obj


@dataclass
class ArtifactWriter:
    """Writes failure artifacts with sensitive content scrubbed (I20)."""

    root: Path

    def write(self, name: str, payload: Any) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        if isinstance(payload, str):
            text = scrub_string(payload)
        else:
            # key-based redaction first (transcript/token/...), then value-level floor
            text = json.dumps(scrub(redact_dict(payload)), ensure_ascii=False, indent=2, default=str)
        assert_no_sensitive(text)
        path.write_text(text, encoding="utf-8")
        return path


# ------------------------------------------------------------- source scanning
def iter_source_files(relative_dirs: list[str], suffixes: tuple[str, ...]) -> list[Path]:
    """Yield repo files under the given dirs with the given suffixes."""
    out: list[Path] = []
    for rel in relative_dirs:
        base = REPO_ROOT / rel
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix in suffixes and "node_modules" not in p.parts and "target" not in p.parts:
                out.append(p)
    return out


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def forbidden_endpoint_hits(source: str, endpoints: Iterable[str]) -> list[str]:
    """Return exact Hub-management endpoint literals found outside Core."""
    return [endpoint for endpoint in endpoints if endpoint in source]


def route_call_map(source: str) -> dict[str, set[str]]:
    """Map decorated conversation routes to the calls in their function bodies."""
    tree = ast.parse(source)
    routes: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = getattr(target, "attr", getattr(target, "id", ""))
            if name not in {"get", "post", "put", "delete", "websocket"}:
                continue
            calls: set[str] = set()
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                target = sub.func
                if isinstance(target, ast.Attribute):
                    calls.add(target.attr)
                elif isinstance(target, ast.Name):
                    calls.add(target.id)
            routes[node.name] = calls
            break
    return routes


def conversation_bypasses(source: str, forbidden_calls: set[str]) -> list[str]:
    """Flag routes that directly invoke provider, playback or Journal effects."""
    return [
        f"{name}() calls {sorted(calls & forbidden_calls)}"
        for name, calls in route_call_map(source).items()
        if calls & forbidden_calls
    ]
