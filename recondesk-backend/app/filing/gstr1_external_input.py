"""Period/table-level gaps that Sales Register cannot fill.

Two distinct filing UX channels — do not conflate:

* ``PendingReviewInvoice`` (in ``gstr1_filing_mapper``): per-row. SR has
  enough fields that a human can choose (inv_typ, exp_typ conflict, etc.).
* ``NeedsExternalInput`` (this module): period/table-level. Required GSTN
  fields are absent from SR entirely — no row-level decision fixes it. The
  CA must supply a separate artifact (HSN schedule, nil split worksheet,
  document series register, advances schedule).

HSN / NIL / DOC_ISSUE / AT-TXPD mappers should emit ``NeedsExternalInput`` when
the table cannot be built from SR, not dump those cases into
``pending_review``.

AT/TXPD note
------------
Coverage on repo sample + typical synthetic SRs: **0 advance rows**. When an
``ADVANCES`` label does appear, SR still is not a Table 11 schedule (no AT vs
TXPD distinction). ``map_sales_register_to_gstr1_at_txpd`` is envelope-only —
never invents ``at[]`` / ``txpd[]`` Save fragments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Canonical GSTR-1 Save section keys (Sandbox / GSTN).
TABLE_HSN = "hsn"
TABLE_NIL = "nil"
TABLE_DOC_ISSUE = "doc_issue"
TABLE_AT = "at"
TABLE_TXPD = "txpd"

EXTERNAL_INPUT_TABLES: frozenset[str] = frozenset({
    TABLE_HSN,
    TABLE_NIL,
    TABLE_DOC_ISSUE,
    TABLE_AT,
    TABLE_TXPD,
})


@dataclass(frozen=True)
class NeedsExternalInput:
    """One table the filing run cannot populate from Sales Register alone.

    This is **not** a per-invoice review item. ``filing_period`` + ``table``
    identify the gap; ``missing_fields`` names what a separate CA input must
    provide.
    """

    table: str
    filing_period: str  # YYYY-MM
    reason: str
    message: str
    missing_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.table not in EXTERNAL_INPUT_TABLES:
            raise ValueError(
                f"NeedsExternalInput.table must be one of {sorted(EXTERNAL_INPUT_TABLES)}; "
                f"got {self.table!r}"
            )
        period = (self.filing_period or "").strip()
        if len(period) != 7 or period[4] != "-" or not (
            period[:4].isdigit() and period[5:].isdigit()
        ):
            raise ValueError(
                f"NeedsExternalInput.filing_period must be YYYY-MM; got {self.filing_period!r}"
            )


@dataclass
class FilingDataGaps:
    """Collected period/table gaps for one filing run (alongside Save fragments)."""

    needs_external_input: list[NeedsExternalInput] = field(default_factory=list)

    @property
    def external_input_count(self) -> int:
        return len(self.needs_external_input)

    def tables_blocked(self) -> set[str]:
        return {g.table for g in self.needs_external_input}

    def add(self, gap: NeedsExternalInput) -> None:
        self.needs_external_input.append(gap)


def hsn_unavailable_from_sr(
    filing_period: str,
    *,
    reason: str = "sr_lacks_hsn_uqc_qty",
    message: Optional[str] = None,
) -> NeedsExternalInput:
    """Table 12 cannot be filled: SR has at most an HSN string, no UQC/qty."""
    return NeedsExternalInput(
        table=TABLE_HSN,
        filing_period=filing_period,
        reason=reason,
        message=message
        or (
            "HSN summary needs HSN code, UQC, and quantity. Sales Register "
            "typically lacks UQC/qty (and often HSN). Upload an HSN schedule."
        ),
        missing_fields=("hsn", "uqc", "qty"),
    )


def nil_split_unavailable_from_sr(
    filing_period: str,
    *,
    reason: str = "sr_lumps_nil_exempt_non_gst",
    message: Optional[str] = None,
) -> NeedsExternalInput:
    """Table 8 cannot be split: SR collapses nil/exempt/non-GST into one bucket."""
    return NeedsExternalInput(
        table=TABLE_NIL,
        filing_period=filing_period,
        reason=reason,
        message=message
        or (
            "Nil-rated table needs nil / exempt / non-GST split. Sales Register "
            "usually bundles these into one NIL_RATED label. Upload a nil split."
        ),
        missing_fields=("nil_amt", "expt_amt", "ngsup_amt"),
    )


def doc_issue_unavailable_from_sr(
    filing_period: str,
    *,
    reason: str = "sr_has_no_document_series",
    message: Optional[str] = None,
) -> NeedsExternalInput:
    """Table 13 is never derived from SR line items."""
    return NeedsExternalInput(
        table=TABLE_DOC_ISSUE,
        filing_period=filing_period,
        reason=reason,
        message=message
        or (
            "Documents Issued needs series, from/to numbers, and cancel counts. "
            "Sales Register does not carry these. Upload a document series register."
        ),
        missing_fields=("doc_num", "from", "to", "totnum", "cancel", "net_issue"),
    )


def advances_unavailable_from_sr(
    filing_period: str,
    *,
    table: str = TABLE_AT,
    reason: str = "sr_lacks_advance_schedule",
    message: Optional[str] = None,
) -> NeedsExternalInput:
    """Table 11 AT/TXPD when books do not structure advances for filing."""
    if table not in {TABLE_AT, TABLE_TXPD}:
        raise ValueError(f"advances helper only for at/txpd; got {table!r}")
    return NeedsExternalInput(
        table=table,
        filing_period=filing_period,
        reason=reason,
        message=message
        or (
            "Advances (AT/TXPD) need rate/POS advance and adjustment schedules. "
            "Sales Register rarely carries this structure. Upload an advances schedule."
        ),
        missing_fields=("pos", "rt", "ad_amt", "iamt", "camt", "samt"),
    )
