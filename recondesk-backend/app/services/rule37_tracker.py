"""Rule 37 (180-day payment) compliance helpers for purchase records."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

PAID_LATE = "PAID_LATE"
OK = "OK"
OVERDUE_UNPAID = "OVERDUE_UNPAID"
WARNING_30_DAYS = "WARNING_30_DAYS"
WARNING_60_DAYS = "WARNING_60_DAYS"

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
CRITICAL = "CRITICAL"


def _stored_pr_amount_to_paise(val: object) -> int:
    """PR ``*_paise`` fields store true paise."""
    if val is None:
        return 0
    return int(val)


def _iso_payment_date(val: object) -> str | None:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val.isoformat()
    s = str(val).strip()
    if not s:
        return None
    if "T" in s:
        s = s[:10]
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def build_payment_records_from_pr(
    pr_rows: list[dict],
    pr_raw_by_id: dict[str, dict] | None = None,
) -> list[dict]:
    """Build Rule 37 ``payment_records`` from PR rows and optional ``record_data``.

    Payment metadata is read from ``pr_raw_by_id`` (``payment_status``,
    ``payment_date``, ``amount_paid_paise``).  Matcher rows supply invoice ids
    and taxable totals (already in paise).
    """
    raw_map = pr_raw_by_id or {}
    out: list[dict] = []

    for pr in pr_rows:
        rid = str(pr.get("id", ""))
        if not rid:
            continue
        raw = raw_map.get(rid, {})
        if not isinstance(raw, dict):
            raw = {}

        status = raw.get("payment_status")
        if isinstance(status, str):
            status = status.strip().lower()
        else:
            status = "unpaid"

        if status == "unpaid":
            continue

        pay_date = _iso_payment_date(raw.get("payment_date"))
        if status not in ("partially paid", "partial") and pay_date is None:
            continue

        amount_paise = 0
        raw_amt = raw.get("amount_paid_paise")
        if raw_amt is not None:
            amount_paise = _stored_pr_amount_to_paise(raw_amt)
        elif status == "paid":
            # If "paid" but no amount specified, assume full invoice value was paid
            inv_val = int(pr.get("invoice_value_paise") or 0)
            if inv_val <= 0:
                taxable = int(pr.get("taxable_amount_paise") or 0)
                if "igst_paise" in pr or "cgst_paise" in pr or "sgst_paise" in pr:
                    igst = int(pr.get("igst_paise") or 0)
                    cgst = int(pr.get("cgst_paise") or 0)
                    sgst = int(pr.get("sgst_paise") or 0)
                    tot_tax = igst + cgst + sgst
                else:
                    tot_tax = int(pr.get("total_tax_paise") or 0)
                inv_val = taxable + tot_tax
            amount_paise = inv_val
        else:
            continue

        if amount_paise <= 0:
            continue

        out.append(
            {
                "invoice_id": rid,
                "payment_date": pay_date,
                "amount_paise": amount_paise,
            }
        )

    return out


def _payment_row_amount_paise(p: dict) -> int:
    """Sum only explicit amounts — never substitute invoice value for a missing key."""
    if "amount_paise" in p:
        return int(p["amount_paise"])
    if "amount_paid_paise" in p:
        return int(p["amount_paid_paise"])
    return 0


def check_rule_37_compliance(
    pr_records: list[dict],
    payment_records: list[dict],
    today: date | None = None,
) -> list[dict]:
    """
    Assess Rule 37 payment timing and ITC at risk per purchase-register row.

    Payment rows link to PR rows via ``invoice_id`` matching ``pr_rec["id"]``.
    Uses ``taxable_amount_paise`` when present; otherwise ``invoice_value_paise``
    for the invoice base used in unpaid / partial-payment math.

    Partial payments reduce unpaid balance; ITC at risk follows the unpaid
    proportion except for PAID_LATE (full ITC at risk).
    """
    if today is None:
        today = date.today()

    payment_index: dict[str, list[dict]] = defaultdict(list)
    for p in payment_records:
        payment_index[p["invoice_id"]].append(p)

    results: list[dict] = []

    for pr_rec in pr_records:
        invoice_date_str = pr_rec.get("invoice_date")
        if not invoice_date_str:
            continue
        try:
            invoice_date = date.fromisoformat(invoice_date_str)
        except ValueError:
            continue
            
        deadline = invoice_date + timedelta(days=180)

        # Rule 37 payment_status filter: only Unpaid or Partially Paid
        payment_status = pr_rec.get("payment_status")
        if isinstance(payment_status, str):
            payment_status = payment_status.strip().lower()
        else:
            payment_status = "unpaid"
            
        if payment_status not in ("unpaid", "partially paid", "partial"):
            continue

        days_remaining = (deadline - today).days

        # Calculate reversal amount as igst + cgst + sgst
        if "igst_paise" in pr_rec or "cgst_paise" in pr_rec or "sgst_paise" in pr_rec:
            igst = int(pr_rec.get("igst_paise") or 0)
            cgst = int(pr_rec.get("cgst_paise") or 0)
            sgst = int(pr_rec.get("sgst_paise") or 0)
            total_tax_paise = igst + cgst + sgst
        else:
            total_tax_paise = int(pr_rec.get("total_tax_paise") or 0)

        itc_at_risk_paise = total_tax_paise

        inv_val = int(pr_rec.get("invoice_value_paise") or 0)
        if inv_val <= 0:
            taxable = int(pr_rec.get("taxable_amount_paise") or 0)
            inv_val = taxable + total_tax_paise
        total_invoice_value_paise = inv_val

        pr_id = str(pr_rec["id"])
        payments = payment_index.get(pr_id, [])
        total_paid_paise = sum(_payment_row_amount_paise(p) for p in payments)
        if total_paid_paise > total_invoice_value_paise:
            total_paid_paise = total_invoice_value_paise
        unpaid_paise = total_invoice_value_paise - total_paid_paise
        unpaid_paise = max(unpaid_paise, 0)

        # The Rule 37 trigger is: invoice_date + 180 days < today's date
        if days_remaining >= 0:
            continue

        status = OVERDUE_UNPAID
        urgency = CRITICAL
        action = "Reverse ITC immediately. Payment overdue beyond 180 days."

        results.append(
            {
                "pr_id": pr_id,
                "supplier_gstin": pr_rec.get("supplier_gstin", ""),
                "invoice_number": pr_rec.get("invoice_number_normalized", ""),
                "invoice_date": invoice_date_str,
                "deadline": deadline.isoformat(),
                "days_remaining": days_remaining,
                "total_invoice_value_paise": total_invoice_value_paise,
                "total_paid_paise": total_paid_paise,
                "unpaid_paise": unpaid_paise,
                "itc_at_risk_paise": itc_at_risk_paise,
                "status": status,
                "urgency": urgency,
                "action": action,
            }
        )

    return results
