from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from .redact import redact_dict

if TYPE_CHECKING:
    from ..core.runtime import RuntimeController
    from ..journal.repository import JournalRepository


def export_redacted_diagnostics(
    runtime: RuntimeController,
    journal: JournalRepository | None = None,
) -> dict[str, Any]:
    """Export a redacted diagnostic bundle for support and diagnostics.

    Guarantees (I20 & Part 4.4):
    - No secrets, tokens, or API keys.
    - No user transcripts or raw audio.
    - No absolute personal directory paths.
    """
    state = runtime.get_state()

    # Redacted service & provider maps
    services_redacted = {
        name: redact_dict(s.model_dump(mode="json"))
        for name, s in state.services.items()
    }
    providers_redacted = {
        name: redact_dict(p.model_dump(mode="json"))
        for name, p in state.providers.items()
    }

    journal_meta: dict[str, Any] = {}
    if journal is not None:
        try:
            cursor = journal.conn.execute("SELECT COUNT(*) FROM events;")
            event_count = cursor.fetchone()[0]
            cursor = journal.conn.execute("SELECT COUNT(*) FROM event_revisions;")
            rev_count = cursor.fetchone()[0]
            cursor = journal.conn.execute("PRAGMA integrity_check;")
            integrity = cursor.fetchone()[0]
            journal_meta = {
                "events_count": event_count,
                "revisions_count": rev_count,
                "integrity_check": integrity,
            }
        except Exception as exc:  # noqa: BLE001
            journal_meta = {"error": f"Failed to read journal stats: {exc}"}

    raw_bundle = {
        "schema_version": "1.0",
        "runtime_instance_id": str(runtime.runtime_instance_id),
        "snapshot_version": runtime.snapshot_version,
        "runtime_control_revision": runtime.runtime_control_revision,
        "hub_binding_revision": runtime.hub_binding_revision,
        "mode": runtime.mode.value,
        "activity": state.activity.value,
        "privacy_scope": state.privacy_scope.value,
        "services": services_redacted,
        "providers": providers_redacted,
        "mic_capture": state.mic_capture.model_dump(mode="json"),
        "managed_capture": state.managed_capture.model_dump(mode="json"),
        "stale_dropped_count": runtime.stale_gate.stale_dropped_count,
        "hub_binding": state.hub_binding.model_dump(mode="json") if state.hub_binding else None,
        "journal_summary": journal_meta,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    # Pass entire bundle through redactor as defense-in-depth
    return redact_dict(raw_bundle)
