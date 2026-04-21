import logging
import re

logger = logging.getLogger(__name__)

_CREDIT_NOTE_PREFIXES = ("CREDIT", "CRN", "CN", "CR")
_DEBIT_NOTE_PREFIXES = ("DEBIT", "DRN", "DN", "DR")


def classify_document(record: dict) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", record["invoice_number_normalized"].upper())

    if any(normalized.startswith(p) for p in _CREDIT_NOTE_PREFIXES):
        return "CREDIT_NOTE"
    if any(normalized.startswith(p) for p in _DEBIT_NOTE_PREFIXES):
        return "DEBIT_NOTE"
    if record["taxable_amount_paise"] < 0:
        return "CREDIT_NOTE"
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
