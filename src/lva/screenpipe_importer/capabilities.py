"""Screenpipe source-capability contract (R37 §2, T05).

The importer's correctness rests on facts about the *running* source: whether it
filters by ``start_time``, whether ids are stable, whether a redaction or a
deletion is signalled, and how pagination orders records.  The official docs
describe the *current* upstream, which is not an acceptance of the machine's
version, so none of these may be assumed.

This module keeps that distinction explicit: a capability is either **observed**
from a real probe or **unknown**.  Unknown capabilities are carried as ``None``
rather than defaulted to the convenient value, and an import/reconcile that would
rely on an unknown capability reports it instead of silently proceeding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Capabilities the importer's correctness depends on.  A ``None`` value means
#: "not observed on this machine", never "assumed true".
REQUIRED_CAPABILITIES = (
    "version",
    "start_time_is_filter",
    "stable_source_ids",
    "redaction_mark",
    "deletion_notice",
    "pagination_ordering",
)


@dataclass
class SourceCapabilities:
    """What a probe actually observed about the running Screenpipe source."""

    version: str | None = None
    start_time_is_filter: bool | None = None
    stable_source_ids: bool | None = None
    redaction_mark: bool | None = None
    deletion_notice: bool | None = None
    pagination_ordering: str | None = None  # "ascending" | "descending" | None
    evidence: dict[str, Any] = field(default_factory=dict)

    def unknown_capabilities(self) -> list[str]:
        """The required capabilities this probe could not observe."""
        return [name for name in REQUIRED_CAPABILITIES if getattr(self, name) is None]

    @property
    def fully_observed(self) -> bool:
        return not self.unknown_capabilities()

    def refuse_reason(self, capability: str) -> str | None:
        """Return a refusal string when ``capability`` is not observed.

        Callers use this to fail closed instead of assuming the friendly value.
        """
        if capability not in REQUIRED_CAPABILITIES:
            return None
        if getattr(self, capability) is None:
            return (
                f"UNVERIFIED_SCREENPIPE_CAPABILITY: '{capability}' was not observed "
                "on the running source; refusing to assume it"
            )
        return None


async def probe_capabilities(client: Any) -> SourceCapabilities:
    """Observe what the running source actually supports, honestly.

    Only facts the client can actually report are filled in; everything else
    stays ``None`` so downstream code must acknowledge the gap.  This is a
    *reading* of the source, not a compatibility verdict.
    """
    caps = SourceCapabilities()
    probe = getattr(client, "probe_capabilities", None)
    if probe is None:
        return caps
    try:
        observed = await probe()
    except Exception as exc:  # noqa: BLE001 - an unreachable source proves nothing
        caps.evidence["probe_error"] = str(exc)
        return caps
    if not isinstance(observed, dict):
        return caps
    caps.evidence = dict(observed)
    version = observed.get("version")
    if isinstance(version, str) and version not in ("", "unknown"):
        caps.version = version
    # A health/version response does not by itself prove pagination or redaction
    # semantics, so those remain unobserved unless the source reports them.
    for name in ("start_time_is_filter", "stable_source_ids", "redaction_mark", "deletion_notice"):
        value = observed.get(name)
        if isinstance(value, bool):
            setattr(caps, name, value)
    ordering = observed.get("pagination_ordering")
    if ordering in ("ascending", "descending"):
        caps.pagination_ordering = ordering
    return caps
