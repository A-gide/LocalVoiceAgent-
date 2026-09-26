"""Historical redaction/deletion reconciliation (R37 §2, S5/T06).

Incremental import and historical reconciliation are deliberately separate: the
incremental path only sees records the source returns from the checkpoint on,
while a redaction or deletion that arrives later has to be reconciled against
what is already stored.

The load-bearing rule is **"absence is not deletion"**.  A record disappearing
from a search result proves nothing on its own -- the search may be filtered,
paged, or transiently failing.  So this module never infers a deletion from a
missing record.  It only acts on an explicit, positively observed signal, and
when the source cannot provide one it reports the limitation rather than
claiming the reconciliation succeeded.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("lva.screenpipe_importer.reconcile")


@dataclass
class ReconcileReport:
    """What a reconciliation could and could not establish."""

    redactions_applied: int = 0
    deletions_confirmed: int = 0
    #: Records that vanished from the source but had no explicit deletion
    #: notice.  They are reported, never deleted -- absence is not proof.
    absent_without_notice: list[str] = field(default_factory=list)
    #: Records that could not be reconciled because the id is derived.
    unreconcilable_derived_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @property
    def deletion_sync_complete(self) -> bool:
        """True only when the source could supply explicit deletion signals.

        Without a deletion notice the answer is False -- the caller must not
        report "deletions are synchronised".
        """
        return not any("deletion" in item for item in self.limitations)


class ScreenpipeReconciler:
    """Reconcile source redaction/deletion marks against the stored Journal."""

    def __init__(self, client: Any, repo: Any, capabilities: Any = None) -> None:
        self.client = client
        self.repo = repo
        self.capabilities = capabilities

    def reconcile_record(
        self,
        external_id: str,
        *,
        redacted: bool | None = None,
        deleted_notice: bool | None = None,
        stable_id: bool = True,
    ) -> ReconcileReport:
        """Apply one explicit signal to one stored record.

        ``None`` means "no signal", which is not the same as a negative one: the
        record is left untouched.  A deletion is acted on only when
        ``deleted_notice is True`` -- never because the record was merely absent.
        """
        report = ReconcileReport()
        if not stable_id:
            report.unreconcilable_derived_ids.append(external_id)
            report.limitations.append(
                "derived ids cannot be reconciled reliably: a redaction rewrites "
                "the identity inputs, so the two versions cannot be matched"
            )
            return report

        if redacted:
            if self.repo.apply_source_redaction("screenpipe_rest", external_id):
                report.redactions_applied += 1

        if deleted_notice:
            # An explicit deletion notice is the only thing that authorises a
            # deletion.  The Journal keeps raw text immutable (I06); a deletion is
            # recorded through the existing privacy-deletion path, not by hiding
            # the row.
            report.deletions_confirmed += 1
            report.limitations.append(
                "deletion_notice observed; apply the Journal privacy-deletion path "
                "(I06 keeps raw_text immutable)"
            )

        if self.capabilities is not None:
            missing = self.capabilities.unknown_capabilities()
            if missing:
                report.limitations.append(
                    "source capabilities not observed: " + ", ".join(missing)
                )
        return report

    def note_absent_records(self, stored_ids: list[str], seen_ids: set[str]) -> ReconcileReport:
        """Record records that are stored but absent from the source result.

        This is *reporting only*.  Absence is not deletion, so nothing is removed
        and the caller is told the truth: these ids need an explicit signal.
        """
        report = ReconcileReport()
        report.absent_without_notice = [i for i in stored_ids if i not in seen_ids]
        if report.absent_without_notice:
            report.limitations.append(
                "records are absent from the source result, but absence is not a "
                "deletion notice; no deletion was performed"
            )
        if self.capabilities is None or self.capabilities.deletion_notice is not True:
            report.limitations.append(
                "no reliable deletion notice from the source; deletion sync is NOT "
                "complete"
            )
        return report
