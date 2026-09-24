"""Pinned Hub contract for the first compatible target (v1.2.1 PR-012).

Frozen basis (plan L571, L584): the first compatibility target is the reviewed
upstream commit below plus the observed ``/api/sys/version`` fixture -- the Hub's
own master documentation is **not** treated as a long-lived contract.  The control
client must be versioned, and **unknown fields are preserved read-only rather than
written back blindly**.

Sanitised request/response fixtures live under ``tests/fixtures/hub/``.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The reviewed upstream commit this contract was derived from (plan L571).
UPSTREAM_COMMIT = "a9cf12809e8243ff0b820abda1a24934d4eb7026"

#: The Hub version this module describes.
VERSION = "0.9.8.3"

#: Operations the pinned version is known to support.  A capability the pinned
#: contract does not list must be treated as absent, not attempted hopefully.
SUPPORTED_OPERATIONS: frozenset[str] = frozenset(
    {
        "sys.version",
        "node.info",
        "models.list",
        "models.loaded",
        "models.refresh",
        "models.config.get",
        "models.load",
        "models.stop",
    }
)


class HubHandshake(str, Enum):
    """Handshake outcome (plan L575-582)."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    HUB_CONTROL_UNSAFE = "HUB_CONTROL_UNSAFE"
    HUB_BIND_UNVERIFIED = "HUB_BIND_UNVERIFIED"
    UNAVAILABLE = "UNAVAILABLE"


class HubLoadRequestV0_9_8_3(BaseModel):
    """The versioned load DTO (plan L592).

    ``extra="allow"`` is deliberate and load-bearing: the Hub may add fields the
    pinned contract does not know about, and those must survive a round trip
    instead of being dropped and silently re-written without them.
    """

    model_config = ConfigDict(extra="allow")

    modelId: str
    cmd: str | None = None
    extraParams: list[str] = Field(default_factory=list)
    llamaBinPathSelect: str | None = None
    vision: bool | None = None
    device: str | None = None


class HubVersionInfo(BaseModel):
    """``/api/sys/version`` response, tolerant of unknown fields."""

    model_config = ConfigDict(extra="allow")

    version: str | None = None


def classify_version(reported: str | None) -> HubHandshake:
    """Map a reported Hub version onto the handshake verdict.

    Only the pinned version is READY.  Anything else -- including a missing or
    unparseable version -- is DEGRADED rather than UNAVAILABLE: the process is
    reachable and some probes may still pass, so the honest verdict is "working
    with capabilities disabled", not "absent".
    """
    if reported and reported.strip() == VERSION:
        return HubHandshake.READY
    return HubHandshake.DEGRADED


def supports(operation: str, handshake: HubHandshake) -> bool:
    """Whether ``operation`` may be attempted under ``handshake``.

    A DEGRADED Hub disables the operations the pinned contract cannot confirm; a
    READY Hub may use every listed operation.  Any other verdict disables control
    entirely (plan L579/L580 both say "management disabled").
    """
    if handshake is not HubHandshake.READY and handshake is not HubHandshake.DEGRADED:
        return False
    if handshake is HubHandshake.DEGRADED:
        # Only the read-only identity probes stay available; anything that could
        # change model state is disabled until the version is understood.
        return operation in {"sys.version", "node.info", "models.list", "models.loaded"}
    return operation in SUPPORTED_OPERATIONS


def load_request_from_profile(model_id: str, profile: dict[str, Any]) -> HubLoadRequestV0_9_8_3:
    """Map a Hub-saved profile onto the versioned load DTO (plan L592).

    Unknown profile keys are carried through by ``extra="allow"``; this function
    does not invent ``-ngl``/``-c``/``mmproj`` values (plan L593).
    """
    payload = dict(profile)
    payload["modelId"] = model_id
    return HubLoadRequestV0_9_8_3.model_validate(payload)
