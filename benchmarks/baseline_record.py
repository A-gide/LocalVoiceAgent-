"""Wave 0b baseline profile recorder (PR-022).

Frozen plan references:

* line 1354 - PR-022 adds ``benchmarks/baseline-*`` to the repository;
* line 1355 - the steps list "baseline commands" beside the harness and the
  CI test groups;
* line 1626 - "Wave 0b records the target-device baseline `B0`"; only numbers
  from the same profile may be compared;
* line 1650 - any model / context / ASR / TTS device change requires the
  profile to be re-measured, so the profile must be *recorded*, not inferred.

Design constraints taken from the plan and the surrounding instrument:

* The gate metrics themselves stay in their owning harnesses
  (``benchmarks/wasapi_loopback.py``, ``scripts/soak.py``,
  ``benchmarks/run_acceptance_tests.py``). This module does **not** re-implement
  measurement; it pins *which* numbers were produced *under which* profile and
  supplies the drift check that compares a new run against the recorded one.
* Every number carries its own timestamp, so a baseline from a different
  runtime profile can never be silently compared against a fresh one
  (line 1626 / 1650).
* Baseline files are redacted on write: a profile records device names and
  counters, never a transcript or a personal absolute path.

Usage::

    python benchmarks/baseline_record.py list
    python benchmarks/baseline_record.py gates
    python benchmarks/baseline_record.py compare benchmarks/baseline-b0.json fresh.json
    python benchmarks/baseline_record.py record-b0 --write   # only with real evidence
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lva.observability.redact import redact_dict  # noqa: E402

BENCHMARKS_DIR = Path(__file__).resolve().parent

# Gate definitions copied from the frozen plan (lines 1638-1647). This table is
# the contract the compare step reports against.
GATES: dict[str, str] = {
    "simulated_speech_onset_to_silence": "P95 <= min(250ms, B0_P95 * 1.10); P99 <= 400ms",
    "physical_onset_to_acoustic_silence": "P95 <= min(250ms, B0_P95 * 1.10); P99 <= 400ms (100 valid samples)",
    "interrupt_commit_to_stop_request": "P95 <= 20ms",
    "audio_callback_duration": "P99 < 1ms",
    "standby_cpu": "record P50/P95; P95 must not exceed B0 * 1.10",
    "rss_12h": "after warm-up < max(200MB, 10%); slope must not rise monotonically",
    "handles_threads_queues": "peak <= warm-up +10%; no unbounded backlog",
    "journal": "no unrecovered lock; integrity_check=ok; import counts reconcile",
    "vram_peak_gb": "reference profile < 7.5 GB",
}

# Metrics the B0 baseline itself is expected to carry.
B0_METRICS: tuple[str, ...] = (
    "simulated_speech_onset_to_silence_p95_ms",
    "simulated_speech_onset_to_silence_p99_ms",
    "interrupt_commit_to_stop_request_p95_ms",
    "audio_callback_duration_p99_ms",
    "standby_cpu_p50_percent",
    "standby_cpu_p95_percent",
    "rss_warmup_mb",
    "vram_peak_gb",
)

# A baseline is only comparable against the same runtime profile (line 1626).
PROFILE_FIELDS: tuple[str, ...] = (
    "llm_profile",
    "llm_context",
    "asr_device",
    "tts_device",
    "gpu",
    "cpu",
    "ram_gb",
    "os",
)

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9 ._+\-]")


def _sanitize(value: Any) -> Any:
    """Keep profile values free of paths and free text."""
    if isinstance(value, str):
        return _SAFE_TOKEN.sub("", value).strip()
    return value


def reference_profile() -> dict[str, Any]:
    """The plan's Reference Runtime Profile (lines 1628-1636).

    Machine-identity fields (CPU/GPU/RAM/OS) are declared as *inputs*: a
    constrained session that cannot read them must pass them explicitly rather
    than let this function invent a value.
    """
    return {
        "llm_profile": "Spark-X2.5-4B Q8",
        "llm_context": 8192,
        "asr_device": "SenseVoice CPU",
        "tts_device": "MeloTTS/sherpa-onnx CPU",
        "live_sessions": 1,
    }


def machine_facts(
    *,
    cpu: str | None = None,
    gpu: str | None = None,
    ram_gb: float | None = None,
    os_name: str | None = None,
) -> dict[str, Any]:
    """Collect what the host reports, honouring explicit overrides."""
    return {
        "os": _sanitize(os_name or platform.platform()),
        "cpu": _sanitize(cpu) if cpu else "UNKNOWN",
        "gpu": _sanitize(gpu) if gpu else "UNKNOWN",
        "ram_gb": ram_gb if ram_gb is not None else "UNKNOWN",
        "python": platform.python_version(),
    }


def new_baseline(
    label: str,
    *,
    metrics: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Build a baseline document. Unmeasured metrics are recorded as null."""
    merged_profile = reference_profile()
    if profile:
        merged_profile.update({k: _sanitize(v) for k, v in profile.items()})
    recorded = {name: (metrics or {}).get(name) for name in B0_METRICS}
    unknown = [name for name, value in recorded.items() if value is None]
    return {
        "schema": "lva-baseline/1",
        "label": label,
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source or "UNSPECIFIED",
        "profile": merged_profile,
        "machine": facts or machine_facts(),
        "metrics": recorded,
        "unmeasured_metrics": unknown,
        "gates": GATES,
    }


def baseline_path(label: str) -> Path:
    return BENCHMARKS_DIR / f"baseline-{label}.json"


def write_baseline(document: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = redact_dict(document)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def load_baseline(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def profile_mismatches(baseline: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Report every runtime-profile field that differs (line 1626 / 1650)."""
    out: list[str] = []
    left = baseline.get("profile", {})
    right = fresh.get("profile", {})
    for field in PROFILE_FIELDS:
        a, b = left.get(field), right.get(field)
        if a != b:
            out.append(f"{field}: baseline={a!r} fresh={b!r}")
    return out


def compare(baseline: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Compare a fresh run against a recorded baseline.

    A profile difference makes the comparison invalid rather than merely noisy,
    so it is reported as a refusal.
    """
    drift = profile_mismatches(baseline, fresh)
    base_metrics = baseline.get("metrics", {})
    fresh_metrics = fresh.get("metrics", {})

    comparisons: dict[str, Any] = {}
    for name in B0_METRICS:
        old, new = base_metrics.get(name), fresh_metrics.get(name)
        if old is None or new is None:
            comparisons[name] = {"status": "NOT_COMPARABLE", "baseline": old, "fresh": new}
            continue
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
            comparisons[name] = {"status": "NON_NUMERIC", "baseline": old, "fresh": new}
            continue
        ratio = (new / old) if old else None
        comparisons[name] = {
            "status": "OK",
            "baseline": old,
            "fresh": new,
            "delta": round(new - old, 4),
            "ratio": round(ratio, 4) if ratio is not None else None,
            "exceeds_10_percent": bool(ratio is not None and ratio > 1.10),
        }

    return {
        "schema": "lva-baseline-compare/1",
        "baseline_label": baseline.get("label"),
        "fresh_label": fresh.get("label"),
        "profile_comparable": not drift,
        "profile_mismatches": drift,
        "verdict": "REFUSED_PROFILE_MISMATCH" if drift else "COMPARABLE",
        "metrics": comparisons,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list recorded baseline files")
    sub.add_parser("gates", help="print the gate table from the frozen plan")

    cmp_p = sub.add_parser("compare", help="compare a fresh run against a baseline")
    cmp_p.add_argument("baseline", type=Path)
    cmp_p.add_argument("fresh", type=Path)

    rec = sub.add_parser("record-b0", help="record the B0 baseline document")
    rec.add_argument("--metrics", type=Path, default=None, help="JSON file with measured metrics")
    rec.add_argument("--source", default="UNSPECIFIED", help="provenance of the numbers")
    rec.add_argument("--cpu", default=None)
    rec.add_argument("--gpu", default=None)
    rec.add_argument("--ram-gb", type=float, default=None)
    rec.add_argument("--os", dest="os_name", default=None)
    rec.add_argument("--write", action="store_true", help="write benchmarks/baseline-b0.json")

    args = parser.parse_args(argv)

    if args.command == "list":
        found = sorted(BENCHMARKS_DIR.glob("baseline-*.json"))
        if not found:
            print("no baseline-*.json recorded yet")
        for path in found:
            try:
                doc = load_baseline(path)
            except Exception as exc:  # noqa: BLE001
                print(f"{path.name}: UNREADABLE ({exc})")
                continue
            print(
                f"{path.name}: label={doc.get('label')} "
                f"recorded_at={doc.get('recorded_at_utc')} "
                f"unmeasured={len(doc.get('unmeasured_metrics', []))}"
            )
        return 0

    if args.command == "gates":
        print(json.dumps(GATES, indent=2, ensure_ascii=False))
        return 0

    if args.command == "compare":
        result = compare(load_baseline(args.baseline), load_baseline(args.fresh))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["profile_comparable"] else 3

    metrics = json.loads(args.metrics.read_text(encoding="utf-8")) if args.metrics else {}
    document = new_baseline(
        "b0",
        metrics=metrics,
        facts=machine_facts(
            cpu=args.cpu, gpu=args.gpu, ram_gb=args.ram_gb, os_name=args.os_name
        ),
        source=args.source,
    )
    if args.write:
        path = write_baseline(document, baseline_path("b0"))
        print(f"wrote {path}")
    else:
        print(json.dumps(document, indent=2, ensure_ascii=False))
        print("(dry run: pass --write to persist, after real device evidence exists)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

