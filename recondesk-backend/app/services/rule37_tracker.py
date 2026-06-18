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
            status = status.strip().lower() or None
        else:
            status = None

        if status == "unpaid":
            continue

        pay_date = _iso_payment_date(raw.get("payment_date"))
        if status not in ("paid", "partial") and pay_date is None:
            continue
        if pay_date is None:
            continue

        amount_paise = 0
        raw_amt = raw.get("amount_paid_paise")
        if raw_amt is not None:
            amount_paise = _stored_pr_amount_to_paise(raw_amt)
        elif status == "paid":
            amount_paise = int(pr.get("taxable_amount_paise") or 0)
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
        invoice_date = date.fromisoformat(pr_rec["invoice_date"])
        deadline = invoice_date + timedelta(days=180)

        # Rule 37 payment_status filter: only unpaid / unknown-status invoices
        # are candidates. A "paid" invoice is never a Rule 37 violation, and an
        # invoice settled within the 180-day window clears the requirement.
        payment_status = pr_rec.get("payment_status")
        if isinstance(payment_status, str):
            payment_status = payment_status.strip().lower() or None
        else:
            payment_status = None
        if payment_status == "paid":
            continue
        pay_date_iso = _iso_payment_date(pr_rec.get("payment_date"))
        if pay_date_iso is not None and date.fromisoformat(pay_date_iso) <= deadline:
            continue

        days_remaining = (deadline - today).days

        total_tax_paise = pr_rec.get("total_tax_paise", 0)
        if "taxable_amount_paise" in pr_rec:
            total_invoice_value_paise = int(pr_rec["taxable_amount_paise"] or 0)
        else:
            total_invoice_value_paise = int(pr_rec.get("invoice_value_paise") or 0)

        pr_id = str(pr_rec["id"])
        payments = payment_index.get(pr_id, [])
        # Important: sum actual payment amounts only; never default to invoice value
        total_paid_paise = sum(_payment_row_amount_paise(p) for p in payments)
        if total_paid_paise > total_invoice_value_paise:
            total_paid_paise = total_invoice_value_paise
        unpaid_paise = total_invoice_value_paise - total_paid_paise
        unpaid_paise = max(unpaid_paise, 0)
        unpaid_ratio = (
            unpaid_paise / total_invoice_value_paise if total_invoice_value_paise > 0 else 0.0
        )

        base_itc_at_risk = round(total_tax_paise * unpaid_ratio)

        is_fully_paid = unpaid_paise == 0
        has_partial_payment = total_paid_paise > 0 and unpaid_paise > 0

        if is_fully_paid:
            # Critical: payment presence ≠ full payment; use amount-based logic only
            if total_paid_paise == 0:
                status = OK
                urgency = LOW
                action = "No action required"
                itc_at_risk_paise = 0
            else:
                payment_dates = [
                    date.fromisoformat(p["payment_date"])
                    for p in payments
                    if p.get("payment_date")
                ]
                if not payment_dates:
                    status = OK
                    urgency = LOW
                    action = "No action required"
                    itc_at_risk_paise = 0
                else:
                    latest_payment_date = max(payment_dates)
                    if latest_payment_date > deadline:
                        status = PAID_LATE
                        urgency = HIGH
                        action = (
                            "ITC reversal required. Payment made after 180-day limit."
                        )
                        itc_at_risk_paise = total_tax_paise
                    else:
                        status = OK
                        urgency = LOW
                        action = "No action required"
                        itc_at_risk_paise = 0
        else:
            # Critical: unpaid invoices past 180 days must never return OK
            if has_partial_payment and days_remaining >= 0:
                status = OK
                urgency = LOW
                action = "No action required"
                itc_at_risk_paise = base_itc_at_risk
            elif days_remaining < 0:
                status = OVERDUE_UNPAID
                urgency = CRITICAL
                action = (
                    "Reverse ITC immediately. Payment overdue beyond 180 days."
                )
                itc_at_risk_paise = base_itc_at_risk
            elif days_remaining <= 30:
                status = WARNING_30_DAYS
                urgency = HIGH
                action = (
                    "Pay supplier within 30 days to avoid ITC reversal."
                )
                itc_at_risk_paise = base_itc_at_risk
            elif days_remaining <= 60:
                status = WARNING_60_DAYS
                urgency = MEDIUM
                action = "Pay supplier within 60 days."
                itc_at_risk_paise = base_itc_at_risk
            else:
                status = OK
                urgency = LOW
                action = "No immediate action required."
                itc_at_risk_paise = base_itc_at_risk

        results.append(
            {
                "pr_id": pr_id,
                "supplier_gstin": pr_rec["supplier_gstin"],
                "invoice_number": pr_rec["invoice_number_normalized"],
                "invoice_date": pr_rec["invoice_date"],
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
