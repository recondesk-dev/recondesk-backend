"""Phase 2 — confirmed IMS writeback to GSTN via Sandbox.

Called only after explicit CA confirmation from the Action panel.
Never invoked on page load, hover, or recommendation load.

Maps CA-facing ``hold`` → GSTN ``pending``. Dual-status polling:
outer Sandbox accept of the request is not success — poll until
``IMSCheckStatusResponse.is_complete``, then map via ``has_errors``.

Idempotency: ``ims_action_submissions`` keyed by (invoice_id, period, gstin)
blocks a second ``save_invoice_status`` when a non-failed row already exists.

Phase 4 hook: after a confirmed success, callers should trigger
post-action GSTR-2B / IMS overlay refresh — see
``phase4_post_action_2b_sync_pending`` on ``ConfirmWritebackResult``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal, Optional, Sequence

from app.ims.ims_action_store import (
    ImsActionStore,
    normalize_gstin,
    normalize_period,
)
from app.services.sandbox_gst_client import (
    IMS_ACTIONS,
    IMSCheckStatusResponse,
    IMSSaveStatusResponse,
    SandboxClientError,
    make_sandbox_client,
)

_log = logging.getLogger(__name__)

CaAction = Literal["accept", "reject", "hold"]
GstnAction = Literal["accept", "reject", "pending"]
SubmitMode = Literal["confirm_recommendation", "override"]
InvoiceOutcome = Literal["confirmed", "failed", "unclear", "pending"]

# Fields required (or strongly expected) on each IMS save entry.
_WRITEBACK_KEYS = (
    "stin",
    "inum",
    "inv_typ",
    "srcform",
    "rtnprd",
    "idt",
    "val",
    "pos",
    "txval",
    "iamt",
    "camt",
    "samt",
    "cess",
    "prev_status",
)

DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_MAX_POLLS = 45

UNCLEAR_MESSAGE = (
    "Unclear — verify manually on the GST portal. "
    "Sandbox accepted the request but GSTN inner status did not resolve "
    "to confirmed or failed within the poll window."
)


def ca_action_to_gstn(action: str) -> GstnAction:
    """Map CA UI action to Sandbox/GSTN action code family."""
    a = (action or "").strip().lower()
    if a == "hold":
        return "pending"
    if a in IMS_ACTIONS:
        return a  # type: ignore[return-value]
    raise ValueError(f"Invalid IMS action {action!r}; expected accept|reject|hold")


def is_override(
    recommended_action: str | None,
    chosen_action: str,
) -> bool:
    """True when the CA disagrees with ReconDesk's recommendation."""
    if not recommended_action:
        return True
    return (
        recommended_action.strip().lower() != chosen_action.strip().lower()
    )


@dataclass(frozen=True)
class ConfirmedInvoiceAction:
    """One invoice the CA has explicitly confirmed."""

    invoice_id: str
    chosen_action: CaAction
    recommended_action: Optional[str] = None
    section: str = "b2b"
    writeback_payload: Optional[dict[str, Any]] = None
    remarks: Optional[str] = None

    @property
    def overridden(self) -> bool:
        return is_override(self.recommended_action, self.chosen_action)

    @property
    def submit_mode(self) -> SubmitMode:
        return "override" if self.overridden else "confirm_recommendation"


@dataclass
class InvoiceWritebackResult:
    """Per-invoice terminal (or unclear) outcome after confirm+poll."""

    invoice_id: str
    chosen_action: CaAction
    outcome: InvoiceOutcome
    reference_id: Optional[str] = None
    transaction_id: Optional[str] = None
    status_cd: Optional[str] = None
    error_message: Optional[str] = None
    reused_existing: bool = False
    submit_mode: SubmitMode = "confirm_recommendation"
    recommended_action: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConfirmWritebackResult:
    """Result of posting confirmed actions after dual-status resolution.

    ``reference_id`` is retained for backward compatibility (first new save
    ref, else first reused). Prefer ``invoice_results`` / ``reference_ids``.
    """

    invoice_results: list[InvoiceWritebackResult]
    invoice_count: int
    confirmed_count: int
    failed_count: int
    unclear_count: int
    reused_count: int
    action_groups: dict[str, int]
    override_count: int
    override_invoice_ids: list[str] = field(default_factory=list)
    reference_ids: list[str] = field(default_factory=list)
    reference_id: Optional[str] = None
    transaction_id: Optional[str] = None
    # PHASE 4 HOOK — after poll confirms GSTN inner success, refresh 2B/IMS
    phase4_post_action_2b_sync_pending: bool = True

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["invoice_results"] = [r.as_dict() for r in self.invoice_results]
        return d


@dataclass
class PollWritebackResult:
    """Dual-status poll outcome for a prior confirm."""

    reference_id: str
    status_cd: str
    is_complete: bool
    has_errors: bool
    processed_count: int
    error_count: int
    error_code: str = ""
    error_message: str = ""
    error_report: dict[str, Any] = field(default_factory=dict)
    outcome: Literal["pending", "confirmed", "failed", "unclear"] = "pending"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def outcome_from_poll(
    poll: IMSCheckStatusResponse,
) -> Literal["pending", "confirmed", "failed"]:
    """Map Sandbox check-status to UI writeback state.

    Success requires complete + no errors. Outer request acceptance alone
    never yields ``confirmed``.
    """
    if not poll.is_complete:
        return "pending"
    if poll.has_errors:
        return "failed"
    if poll.status_cd == "P":
        return "confirmed"
    return "failed"


def build_invoice_data_by_action(
    actions: Sequence[ConfirmedInvoiceAction],
) -> dict[GstnAction, dict[str, list[dict[str, Any]]]]:
    """Group writeback payloads by GSTN action and section."""
    grouped: dict[GstnAction, dict[str, list[dict[str, Any]]]] = {
        "accept": {},
        "reject": {},
        "pending": {},
    }
    for item in actions:
        gstn_action = ca_action_to_gstn(item.chosen_action)
        payload = _normalize_writeback_payload(item)
        section = (item.section or "b2b").strip().lower() or "b2b"
        grouped[gstn_action].setdefault(section, []).append(payload)
    return grouped


def confirm_ims_actions(
    *,
    access_token: str,
    buyer_gstin: str,
    period: str,
    actions: Sequence[ConfirmedInvoiceAction],
    store: ImsActionStore,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    max_polls: int = DEFAULT_MAX_POLLS,
    sleep_fn: Callable[[float], None] = time.sleep,
    client: Any = None,
    run_id: str | None = None,
) -> ConfirmWritebackResult:
    """Post confirmed actions, poll GSTN inner status, persist per invoice.

    Idempotency: ``store.try_claim_submission`` atomically claims
    (invoice_id, period, gstin) *before* any Sandbox call. Claim losers
    reuse the existing row and never call ``save_invoice_status``.

    Dual-status: ``save_invoice_status`` alone never marks ``confirmed``.
    Each new save group is polled via ``check_invoice_status`` until
    complete, failed, or timeout → ``unclear``.
    """
    if not actions:
        raise ValueError("No confirmed IMS actions to write back")

    period_n = normalize_period(period)
    gstin_n = normalize_gstin(buyer_gstin)
    sandbox = client if client is not None else make_sandbox_client(access_token=access_token)

    invoice_results: list[InvoiceWritebackResult] = []
    to_submit: list[ConfirmedInvoiceAction] = []
    reused_count = 0

    # ── Atomic claim BEFORE Sandbox (replaces find_non_failed as the gate) ─
    for item in actions:
        claimed = store.try_claim_submission(
            invoice_id=item.invoice_id,
            period=period_n,
            gstin=gstin_n,
            chosen_action=item.chosen_action,
            recommended_action=item.recommended_action,
            submit_mode=item.submit_mode,
            run_id=run_id,
        )
        if claimed is None:
            # Another writer owns a non-failed row — skip Sandbox entirely.
            existing = store.find_non_failed(
                invoice_id=item.invoice_id,
                period=period_n,
                gstin=gstin_n,
            ) or {}
            reused_count += 1
            stored_outcome = str(existing.get("status") or "pending")
            if stored_outcome == "claiming":
                stored_outcome = "pending"
            if stored_outcome not in ("confirmed", "failed", "unclear", "pending"):
                stored_outcome = "unclear"
            invoice_results.append(
                InvoiceWritebackResult(
                    invoice_id=item.invoice_id,
                    chosen_action=item.chosen_action,
                    outcome=stored_outcome,  # type: ignore[arg-type]
                    reference_id=existing.get("reference_id"),
                    transaction_id=existing.get("transaction_id"),
                    status_cd=existing.get("status_cd"),
                    error_message=existing.get("error_message"),
                    reused_existing=True,
                    submit_mode=item.submit_mode,
                    recommended_action=item.recommended_action,
                )
            )
            _log.info(
                "IMS writeback claim lost invoice_id=%s status=%s reference_id=%s",
                item.invoice_id,
                stored_outcome,
                existing.get("reference_id"),
            )
            continue
        to_submit.append(item)

    override_ids = [a.invoice_id for a in actions if a.overridden]
    action_groups: dict[str, int] = {}
    reference_ids: list[str] = []
    first_ref: Optional[str] = None
    first_txn: Optional[str] = None

    if to_submit:
        # Preserve invoice order within each GSTN action group.
        grouped_actions: dict[GstnAction, list[ConfirmedInvoiceAction]] = {
            "accept": [],
            "reject": [],
            "pending": [],
        }
        for item in to_submit:
            grouped_actions[ca_action_to_gstn(item.chosen_action)].append(item)

        for gstn_action, group_items in grouped_actions.items():
            if not group_items:
                continue

            invoice_data: dict[str, list[dict]] = {}
            for item in group_items:
                section = (item.section or "b2b").strip().lower() or "b2b"
                invoice_data.setdefault(section, []).append(
                    _normalize_writeback_payload(item)
                )

            remarks = None
            for a in group_items:
                if a.remarks:
                    remarks = a.remarks
                    break

            action_groups[gstn_action] = len(group_items)

            for a in group_items:
                _log.info(
                    "IMS writeback item invoice_id=%s mode=%s recommended=%s chosen=%s",
                    a.invoice_id,
                    a.submit_mode,
                    a.recommended_action,
                    a.chosen_action,
                )

            try:
                save_resp: IMSSaveStatusResponse = sandbox.save_invoice_status(
                    gstin=gstin_n,
                    invoice_data=invoice_data,
                    action=gstn_action,
                    remarks=remarks,
                )
            except Exception as exc:
                # Claim must not stay "claiming" forever — free the key for retry.
                err_text = str(exc)
                _log.exception(
                    "IMS save_invoice_status failed gstin=%s action=%s err=%s",
                    gstin_n,
                    gstn_action,
                    err_text,
                )
                for a in group_items:
                    store.upsert_submission(
                        {
                            "invoice_id": a.invoice_id,
                            "gstin": gstin_n,
                            "period": period_n,
                            "chosen_action": a.chosen_action,
                            "recommended_action": a.recommended_action,
                            "submit_mode": a.submit_mode,
                            "status": "failed",
                            "error_message": err_text,
                            "run_id": run_id,
                        }
                    )
                    invoice_results.append(
                        InvoiceWritebackResult(
                            invoice_id=a.invoice_id,
                            chosen_action=a.chosen_action,
                            outcome="failed",
                            error_message=err_text,
                            reused_existing=False,
                            submit_mode=a.submit_mode,
                            recommended_action=a.recommended_action,
                        )
                    )
                continue

            ref = save_resp.reference_id
            txn = save_resp.transaction_id
            if ref:
                reference_ids.append(ref)
            if first_ref is None:
                first_ref = ref or None
                first_txn = txn or None

            # Promote claiming → pending once Sandbox accepted the request.
            for a in group_items:
                store.upsert_submission(
                    {
                        "invoice_id": a.invoice_id,
                        "gstin": gstin_n,
                        "period": period_n,
                        "chosen_action": a.chosen_action,
                        "recommended_action": a.recommended_action,
                        "submit_mode": a.submit_mode,
                        "status": "pending",
                        "reference_id": ref,
                        "transaction_id": txn,
                        "run_id": run_id,
                    }
                )

            # ── Dual-status poll before returning confirmed ───────────────
            poll = _poll_until_resolved(
                sandbox=sandbox,
                reference_id=ref,
                interval_s=poll_interval_s,
                max_polls=max_polls,
                sleep_fn=sleep_fn,
            )
            group_outcome = poll.outcome
            if group_outcome == "pending":
                # Timed out without complete — distinct unclear state.
                group_outcome = "unclear"

            err_msg = poll.error_message or None
            if group_outcome == "unclear":
                err_msg = UNCLEAR_MESSAGE

            for a in group_items:
                store.upsert_submission(
                    {
                        "invoice_id": a.invoice_id,
                        "gstin": gstin_n,
                        "period": period_n,
                        "chosen_action": a.chosen_action,
                        "recommended_action": a.recommended_action,
                        "submit_mode": a.submit_mode,
                        "status": group_outcome,
                        "reference_id": ref,
                        "transaction_id": txn,
                        "status_cd": poll.status_cd,
                        "error_code": poll.error_code or None,
                        "error_message": err_msg,
                        "raw_poll": {
                            "status_cd": poll.status_cd,
                            "is_complete": poll.is_complete,
                            "has_errors": poll.has_errors,
                            "processed_count": poll.processed_count,
                            "error_count": poll.error_count,
                            "error_report": poll.error_report,
                        },
                        "run_id": run_id,
                    }
                )
                invoice_results.append(
                    InvoiceWritebackResult(
                        invoice_id=a.invoice_id,
                        chosen_action=a.chosen_action,
                        outcome=group_outcome,  # type: ignore[arg-type]
                        reference_id=ref,
                        transaction_id=txn,
                        status_cd=poll.status_cd,
                        error_message=err_msg,
                        reused_existing=False,
                        submit_mode=a.submit_mode,
                        recommended_action=a.recommended_action,
                    )
                )

    # Preserve input order in results
    by_id = {r.invoice_id: r for r in invoice_results}
    ordered = [by_id[a.invoice_id] for a in actions if a.invoice_id in by_id]

    confirmed_count = sum(1 for r in ordered if r.outcome == "confirmed")
    failed_count = sum(1 for r in ordered if r.outcome == "failed")
    unclear_count = sum(1 for r in ordered if r.outcome == "unclear")

    if first_ref is None:
        for r in ordered:
            if r.reference_id:
                first_ref = r.reference_id
                first_txn = r.transaction_id
                break

    return ConfirmWritebackResult(
        invoice_results=ordered,
        invoice_count=len(ordered),
        confirmed_count=confirmed_count,
        failed_count=failed_count,
        unclear_count=unclear_count,
        reused_count=reused_count,
        action_groups=action_groups,
        override_count=len(override_ids),
        override_invoice_ids=override_ids,
        reference_ids=reference_ids,
        reference_id=first_ref,
        transaction_id=first_txn,
        phase4_post_action_2b_sync_pending=confirmed_count > 0,
    )


def _poll_until_resolved(
    *,
    sandbox: Any,
    reference_id: str,
    interval_s: float,
    max_polls: int,
    sleep_fn: Callable[[float], None],
) -> PollWritebackResult:
    """Poll check_invoice_status until complete/failed or timeout → pending."""
    if not reference_id:
        return PollWritebackResult(
            reference_id="",
            status_cd="",
            is_complete=False,
            has_errors=True,
            processed_count=0,
            error_count=0,
            error_message="save_invoice_status returned empty reference_id",
            outcome="failed",
        )

    last = poll_ims_writeback_with_client(sandbox, reference_id)
    for i in range(max(0, max_polls - 1)):
        if last.outcome in ("confirmed", "failed"):
            return last
        sleep_fn(interval_s)
        last = poll_ims_writeback_with_client(sandbox, reference_id)
        _log.info(
            "IMS writeback poll reference_id=%s status_cd=%s outcome=%s iter=%d",
            reference_id,
            last.status_cd,
            last.outcome,
            i + 1,
        )
    # Still pending after max polls — caller maps to unclear.
    return last


def poll_ims_writeback_with_client(
    client: Any,
    reference_id: str,
) -> PollWritebackResult:
    check = client.check_invoice_status(reference_id)
    outcome = outcome_from_poll(check)
    return PollWritebackResult(
        reference_id=reference_id,
        status_cd=check.status_cd,
        is_complete=check.is_complete,
        has_errors=check.has_errors,
        processed_count=check.processed_count,
        error_count=check.error_count,
        error_code=check.error_code,
        error_message=check.error_message,
        error_report=check.error_report or {},
        outcome=outcome,
    )


def poll_ims_writeback(
    *,
    access_token: str,
    reference_id: str,
) -> PollWritebackResult:
    """Single poll of dual-status result for a prior confirm."""
    client = make_sandbox_client(access_token=access_token)
    return poll_ims_writeback_with_client(client, reference_id)


def poll_until_complete(
    *,
    access_token: str,
    reference_id: str,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
    max_polls: int = DEFAULT_MAX_POLLS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> PollWritebackResult:
    """Blocking poll loop — prefer FE-driven single polls for long waits."""
    client = make_sandbox_client(access_token=access_token)
    last = _poll_until_resolved(
        sandbox=client,
        reference_id=reference_id,
        interval_s=interval_s,
        max_polls=max_polls,
        sleep_fn=sleep_fn,
    )
    if last.outcome == "pending":
        last.outcome = "unclear"
        if not last.error_message:
            last.error_message = UNCLEAR_MESSAGE
    return last


def _normalize_writeback_payload(item: ConfirmedInvoiceAction) -> dict[str, Any]:
    raw = item.writeback_payload
    if not isinstance(raw, dict) or not raw:
        raise ValueError(
            f"Invoice {item.invoice_id} missing writeback_payload — "
            "reload recommendations after GSTN IMS fetch"
        )
    out: dict[str, Any] = {}
    for key in _WRITEBACK_KEYS:
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    if "stin" not in out and raw.get("supplier_gstin"):
        out["stin"] = raw["supplier_gstin"]
    if "inum" not in out and raw.get("invoice_number"):
        out["inum"] = raw["invoice_number"]
    if "idt" not in out and raw.get("invoice_date"):
        out["idt"] = raw["invoice_date"]
    if "prev_status" not in out:
        out["prev_status"] = raw.get("prev_status") or raw.get("action") or "N"
    for required in ("stin", "inum"):
        if not out.get(required):
            raise ValueError(
                f"Invoice {item.invoice_id} writeback_payload missing {required}"
            )
    for num_key in ("val", "txval", "iamt", "camt", "samt", "cess"):
        if num_key not in out:
            out[num_key] = 0
    if "inv_typ" not in out:
        out["inv_typ"] = "R"
    if "srcform" not in out:
        out["srcform"] = "R1"
    return out
