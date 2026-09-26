import logging
import re

logger = logging.getLogger(__name__)

_CREDIT_NOTE_PREFIXES = ("CREDITNOTE", "CREDIT_NOTE", "CRN", "CDN")
_DEBIT_NOTE_PREFIXES = ("DEBITNOTE", "DEBIT_NOTE", "DRN", "DBN")

_RE_FISCAL_SERIES = re.compile(
    r"^[A-Z0-9]{1,5}[/-](?:20\d\d|19\d\d|\d{2}-\d{2})[/-]", re.IGNORECASE
)
_RE_CN_NOTE = re.compile(r"^(?:CN|CRN|CDN)[-_/\s]\d+$|^(?:CREDIT)[-_/\s]", re.IGNORECASE)
_RE_DN_NOTE = re.compile(r"^(?:DN|DRN|DBN)[-_/\s]\d+$|^(?:DEBIT)[-_/\s]", re.IGNORECASE)


def classify_document(record: dict) -> str:
    # Explicit document type / invoice type if present on record
    doc = str(
        record.get("doc_type")
        or record.get("document_type")
        or record.get("invoice_type")
        or ""
    ).strip().upper()
    if doc in ("INVOICE", "TAX_INVOICE", "INV"):
        if not (
            record.get("is_credit_note")
            or record.get("is_debit_note")
            or record.get("pr_note_quarantine")
            or (record.get("taxable_amount_paise") or 0) < 0
        ):
            return "INVOICE"
    if doc in ("CREDIT_NOTE", "CRN", "CREDIT"):
        return "CREDIT_NOTE"
    if doc in ("DEBIT_NOTE", "DRN", "DBN", "DEBIT"):
        return "DEBIT_NOTE"

    taxable = record.get("taxable_amount_paise") or 0
    if taxable < 0:
        return "CREDIT_NOTE"

    raw = str(
        record.get("invoice_number_raw")
        or record.get("invoice_number")
        or ""
    ).strip()
    if _RE_FISCAL_SERIES.match(raw) and taxable >= 0:
        return "INVOICE"

    inv_val = str(record.get("invoice_number_normalized") or raw).upper()
    normalized = re.sub(r"[^A-Z0-9]", "", inv_val)

    if any(normalized.startswith(p) for p in _CREDIT_NOTE_PREFIXES) or _RE_CN_NOTE.match(raw):
        return "CREDIT_NOTE"
    if any(normalized.startswith(p) for p in _DEBIT_NOTE_PREFIXES) or _RE_DN_NOTE.match(raw):
        return "DEBIT_NOTE"
    return "INVOICE"



def net_itc_after_credit_notes(
    matched_invoices: list[dict],
    credit_notes: list[dict],
) -> dict:
    invoice_map = {inv["id"]: inv["total_tax_paise"] for inv in matched_invoices}
    net: dict = {inv["id"]: inv["total_tax_paise"] for inv in matched_invoices}

    for credit_note in credit_notes:
        ref_id = credit_note.get("reference_invoice_id")
        cn_amount = abs(credit_note["total_tax_paise"])

        if ref_id is None or ref_id not in invoice_map:
            logger.warning(
                "Credit note references unknown invoice %s -- skipping", ref_id
            )
            continue

        if cn_amount > invoice_map[ref_id]:
            logger.warning(
                "Credit note %s exceeds invoice ITC -- possible data error",
                ref_id,
            )

        net[ref_id] -= cn_amount

    net_itc_paise = sum(net.values())

    if net_itc_paise < 0:
        logger.warning(
            "Net ITC is negative (%s paise) -- ITC may be overclaimed",
            net_itc_paise,
        )

    return {
        "net_itc_paise": net_itc_paise,
        "breakdown": net,
    }
