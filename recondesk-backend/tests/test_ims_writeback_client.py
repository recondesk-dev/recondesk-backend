"""Regression tests for IMS writeback gaps: idempotency + dual-status poll.

These would fail if confirm_ims_actions re-called save on a duplicate, or
returned confirmed without polling check_invoice_status.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from app.ims.ims_action_store import InMemoryImsActionStore
from app.ims.ims_writeback_client import (
    UNCLEAR_MESSAGE,
    ConfirmedInvoiceAction,
    confirm_ims_actions,
    outcome_from_poll,
)
from app.services.sandbox_gst_client import (
    IMSCheckStatusResponse,
    IMSSaveStatusResponse,
)


GSTIN = "27AAAAA0000A1Z5"
PERIOD = "2024-11"


def _payload(inum: str = "INV-1") -> dict[str, Any]:
    return {
        "stin": "29BBBBB0000B1Z5",
        "inum": inum,
        "inv_typ": "R",
        "srcform": "R1",
        "rtnprd": "112024",
        "idt": "05-11-2024",
        "val": 1000,
        "pos": "27",
        "txval": 100,
        "iamt": 0,
        "camt": 9,
        "samt": 9,
        "cess": 0,
        "prev_status": "N",
    }


def _action(
    invoice_id: str,
    *,
    chosen: str = "accept",
    recommended: str | None = "accept",
    inum: str | None = None,
) -> ConfirmedInvoiceAction:
    return ConfirmedInvoiceAction(
        invoice_id=invoice_id,
        chosen_action=chosen,  # type: ignore[arg-type]
        recommended_action=recommended,
        section="b2b",
        writeback_payload=_payload(inum or invoice_id),
    )


@dataclass
class FakeSandbox:
    """Records save calls; returns scripted poll sequence per reference_id."""

    save_calls: list[dict[str, Any]] = field(default_factory=list)
    poll_calls: list[str] = field(default_factory=list)
    # reference_id -> list of check responses (popped in order; last repeats)
    poll_scripts: dict[str, list[IMSCheckStatusResponse]] = field(default_factory=dict)
    next_ref_seq: int = 0

    def save_invoice_status(
        self,
        gstin: str,
        invoice_data: dict[str, list[dict]],
        action: str,
        remarks: Optional[str] = None,
    ) -> IMSSaveStatusResponse:
        self.next_ref_seq += 1
        ref = f"REF-{self.next_ref_seq}"
        self.save_calls.append(
            {
                "gstin": gstin,
                "invoice_data": invoice_data,
                "action": action,
                "remarks": remarks,
                "reference_id": ref,
            }
        )
        return IMSSaveStatusResponse(
            reference_id=ref,
            transaction_id=f"TXN-{self.next_ref_seq}",
            raw_payload={},
        )

    def check_invoice_status(self, reference_id: str) -> IMSCheckStatusResponse:
        self.poll_calls.append(reference_id)
        script = self.poll_scripts.get(reference_id) or []
        if not script:
            # Default: immediately success — tests that care override this.
            return IMSCheckStatusResponse(
                status_cd="P",
                trans_type_cd="SAV",
                processed_count=1,
                error_count=0,
            )
        if len(script) == 1:
            return script[0]
        return script.pop(0)


def _ip() -> IMSCheckStatusResponse:
    return IMSCheckStatusResponse(
        status_cd="IP",
        trans_type_cd="SAV",
        processed_count=0,
        error_count=0,
    )


def _ok() -> IMSCheckStatusResponse:
    return IMSCheckStatusResponse(
        status_cd="P",
        trans_type_cd="SAV",
        processed_count=1,
        error_count=0,
    )


def _err() -> IMSCheckStatusResponse:
    return IMSCheckStatusResponse(
        status_cd="PE",
        trans_type_cd="SAV",
        processed_count=0,
        error_count=1,
        error_message="schema",
    )


def test_duplicate_submission_does_not_call_save_twice():
    """GAP 1: second confirm for same invoice/period/gstin must skip Sandbox save."""
    store = InMemoryImsActionStore()
    sandbox = FakeSandbox()
    # First save → poll IP then P
    # We don't know ref until after save; wire after first confirm via side effect.

    sleeps: list[float] = []

    def sleep_fn(s: float) -> None:
        sleeps.append(s)

    # Patch poll script dynamically: after save, set script for that ref.
    original_save = sandbox.save_invoice_status

    def save_and_script(*args, **kwargs):
        resp = original_save(*args, **kwargs)
        sandbox.poll_scripts[resp.reference_id] = [_ip(), _ok()]
        return resp

    sandbox.save_invoice_status = save_and_script  # type: ignore[method-assign]

    action = _action("pm:INV-1")
    first = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[action],
        store=store,
        client=sandbox,
        poll_interval_s=0.0,
        max_polls=5,
        sleep_fn=sleep_fn,
    )
    assert len(sandbox.save_calls) == 1
    assert first.invoice_results[0].outcome == "confirmed"
    assert first.invoice_results[0].reused_existing is False
    assert first.confirmed_count == 1

    # Second attempt — identical invoice — must NOT save again.
    second = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[action],
        store=store,
        client=sandbox,
        poll_interval_s=0.0,
        max_polls=5,
        sleep_fn=sleep_fn,
    )
    assert len(sandbox.save_calls) == 1, (
        "duplicate submit called save_invoice_status again — idempotency broken"
    )
    assert second.reused_count == 1
    assert second.invoice_results[0].reused_existing is True
    assert second.invoice_results[0].outcome == "confirmed"
    assert second.invoice_results[0].reference_id == first.invoice_results[0].reference_id


def test_failed_submission_allows_retry_save():
    """Failed status is not idempotent — a retry may call save again."""
    store = InMemoryImsActionStore()
    sandbox = FakeSandbox()
    sleeps: list[float] = []

    original_save = sandbox.save_invoice_status

    def save_fail(*args, **kwargs):
        resp = original_save(*args, **kwargs)
        sandbox.poll_scripts[resp.reference_id] = [_err()]
        return resp

    def save_ok(*args, **kwargs):
        resp = original_save(*args, **kwargs)
        sandbox.poll_scripts[resp.reference_id] = [_ok()]
        return resp

    sandbox.save_invoice_status = save_fail  # type: ignore[method-assign]
    first = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[_action("pm:FAIL-1")],
        store=store,
        client=sandbox,
        poll_interval_s=0.0,
        max_polls=3,
        sleep_fn=lambda s: sleeps.append(s),
    )
    assert first.failed_count == 1
    assert len(sandbox.save_calls) == 1

    sandbox.save_invoice_status = save_ok  # type: ignore[method-assign]
    second = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[_action("pm:FAIL-1")],
        store=store,
        client=sandbox,
        poll_interval_s=0.0,
        max_polls=3,
        sleep_fn=lambda s: sleeps.append(s),
    )
    assert len(sandbox.save_calls) == 2, "failed rows must be retriable"
    assert second.confirmed_count == 1
    assert second.reused_count == 0


def test_confirm_polls_inner_status_before_confirmed():
    """GAP 2: confirmed requires check_invoice_status → status_cd P, not save alone."""
    store = InMemoryImsActionStore()
    sandbox = FakeSandbox()
    poll_count_at_return: list[int] = []

    original_save = sandbox.save_invoice_status

    def save_then_script(*args, **kwargs):
        resp = original_save(*args, **kwargs)
        # Stay IP for several polls then succeed — proves we waited.
        sandbox.poll_scripts[resp.reference_id] = [_ip(), _ip(), _ok()]
        return resp

    sandbox.save_invoice_status = save_then_script  # type: ignore[method-assign]

    result = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[_action("pm:POLL-1")],
        store=store,
        client=sandbox,
        poll_interval_s=0.0,
        max_polls=10,
        sleep_fn=lambda _s: None,
    )
    # Must have polled more than once (IP, IP, P).
    assert len(sandbox.poll_calls) >= 3, (
        f"expected multi-poll before confirmed, got {sandbox.poll_calls!r}"
    )
    assert result.invoice_results[0].outcome == "confirmed"
    assert result.invoice_results[0].status_cd == "P"
    # Critical: outcome_from_poll on outer-only would wrongly skip this —
    # we assert save alone is insufficient by requiring poll_calls > 0.
    assert sandbox.poll_calls[0] == sandbox.save_calls[0]["reference_id"]


def test_confirm_does_not_mark_confirmed_on_save_reference_alone():
    """If poll never completes, outcome is unclear — never confirmed."""
    store = InMemoryImsActionStore()
    sandbox = FakeSandbox()

    original_save = sandbox.save_invoice_status

    def save_stuck(*args, **kwargs):
        resp = original_save(*args, **kwargs)
        sandbox.poll_scripts[resp.reference_id] = [_ip()]  # always IP (repeats last)
        return resp

    sandbox.save_invoice_status = save_stuck  # type: ignore[method-assign]

    result = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[_action("pm:STUCK-1")],
        store=store,
        client=sandbox,
        poll_interval_s=0.0,
        max_polls=3,
        sleep_fn=lambda _s: None,
    )
    assert result.confirmed_count == 0
    assert result.unclear_count == 1
    assert result.invoice_results[0].outcome == "unclear"
    assert UNCLEAR_MESSAGE in (result.invoice_results[0].error_message or "")
    # Stored as unclear (non-failed) so duplicate won't re-fire save blindly.
    assert store.find_non_failed(
        invoice_id="pm:STUCK-1", period=PERIOD, gstin=GSTIN
    )["status"] == "unclear"


def test_multi_action_batch_tracks_per_invoice_reference_ids():
    """Multi-action batches must not discard all but the last reference_id."""
    store = InMemoryImsActionStore()
    sandbox = FakeSandbox()

    original_save = sandbox.save_invoice_status

    def save_ok(*args, **kwargs):
        resp = original_save(*args, **kwargs)
        sandbox.poll_scripts[resp.reference_id] = [_ok()]
        return resp

    sandbox.save_invoice_status = save_ok  # type: ignore[method-assign]

    actions = [
        _action("pm:A1", chosen="accept", recommended="accept", inum="A1"),
        _action("pm:R1", chosen="reject", recommended="reject", inum="R1"),
    ]
    result = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=actions,
        store=store,
        client=sandbox,
        poll_interval_s=0.0,
        max_polls=3,
        sleep_fn=lambda _s: None,
    )
    assert len(sandbox.save_calls) == 2  # accept group + reject group
    assert len(result.reference_ids) == 2
    assert len({r.reference_id for r in result.invoice_results}) == 2
    by_id = {r.invoice_id: r for r in result.invoice_results}
    assert by_id["pm:A1"].reference_id != by_id["pm:R1"].reference_id
    assert by_id["pm:A1"].outcome == "confirmed"
    assert by_id["pm:R1"].outcome == "confirmed"


def test_outcome_from_poll_never_confirms_incomplete():
    pending = IMSCheckStatusResponse(
        status_cd="IP", trans_type_cd="SAV", processed_count=0, error_count=0
    )
    assert outcome_from_poll(pending) == "pending"
    ok = IMSCheckStatusResponse(
        status_cd="P", trans_type_cd="SAV", processed_count=1, error_count=0
    )
    assert outcome_from_poll(ok) == "confirmed"


def test_try_claim_only_one_winner_under_concurrent_contention():
    """Store-level: two threads claim the same key; exactly one wins."""
    store = InMemoryImsActionStore()
    barrier = threading.Barrier(2)
    results: list[dict | None] = [None, None]
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            barrier.wait(timeout=5)
            results[idx] = store.try_claim_submission(
                invoice_id="pm:RACE-CLAIM",
                period=PERIOD,
                gstin=GSTIN,
                chosen_action="accept",
            )
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    t0 = threading.Thread(target=worker, args=(0,))
    t1 = threading.Thread(target=worker, args=(1,))
    t0.start()
    t1.start()
    t0.join(timeout=10)
    t1.join(timeout=10)
    assert not errors, f"claim workers raised: {errors!r}"
    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1, f"expected exactly one claim winner, got {results!r}"
    assert len(losers) == 1
    assert winners[0]["status"] == "claiming"


def test_concurrent_confirm_calls_save_invoice_status_exactly_once():
    """End-to-end race: two confirms for the same invoice must hit Sandbox once.

    Uses a Barrier so both threads enter confirm_ims_actions before either
    finishes its claim — this is the audit race window, not sequential retries.
    """
    store = InMemoryImsActionStore()
    sandbox = FakeSandbox()
    barrier = threading.Barrier(2)
    original_save = sandbox.save_invoice_status
    save_lock = threading.Lock()

    def save_and_script(*args, **kwargs):
        # Hold the barrier-sync'd race open briefly inside save so a broken
        # claim-after-save design would still be detectable as 2 calls.
        with save_lock:
            resp = original_save(*args, **kwargs)
            sandbox.poll_scripts[resp.reference_id] = [_ok()]
            return resp

    sandbox.save_invoice_status = save_and_script  # type: ignore[method-assign]

    action = _action("pm:RACE-CONFIRM")
    outcomes: list[Any] = []
    errors: list[BaseException] = []

    def run_confirm() -> None:
        try:
            barrier.wait(timeout=5)
            outcomes.append(
                confirm_ims_actions(
                    access_token="tok",
                    buyer_gstin=GSTIN,
                    period=PERIOD,
                    actions=[action],
                    store=store,
                    client=sandbox,
                    poll_interval_s=0.0,
                    max_polls=3,
                    sleep_fn=lambda _s: None,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(run_confirm), pool.submit(run_confirm)]
        for f in futs:
            f.result(timeout=15)

    assert not errors, f"confirm workers raised: {errors!r}"
    assert len(outcomes) == 2
    assert len(sandbox.save_calls) == 1, (
        f"concurrent confirms called save {len(sandbox.save_calls)} times — "
        f"atomic claim failed. calls={sandbox.save_calls!r}"
    )
    reused_flags = sorted(o.invoice_results[0].reused_existing for o in outcomes)
    assert reused_flags == [False, True], (
        f"expected one fresh confirm and one reuse, got {[o.invoice_results[0] for o in outcomes]!r}"
    )
    confirmed = sum(1 for o in outcomes if o.invoice_results[0].outcome == "confirmed")
    # Winner confirmed; loser may show pending/confirmed depending on timing of
    # find_non_failed after winner finished — both must not have re-saved.
    assert confirmed >= 1


def test_sandbox_exception_marks_claim_failed_for_retry():
    """If save throws after claim, status becomes failed so a later claim can retry."""
    store = InMemoryImsActionStore()

    class BoomSandbox(FakeSandbox):
        def save_invoice_status(self, *args, **kwargs):
            raise RuntimeError("sandbox down")

    boom = BoomSandbox()
    first = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[_action("pm:BOOM-1")],
        store=store,
        client=boom,
        poll_interval_s=0.0,
        max_polls=2,
        sleep_fn=lambda _s: None,
    )
    assert first.failed_count == 1
    assert first.invoice_results[0].outcome == "failed"
    row = store.rows[("pm:BOOM-1", PERIOD, GSTIN)]
    assert row["status"] == "failed"
    assert store.find_non_failed(
        invoice_id="pm:BOOM-1", period=PERIOD, gstin=GSTIN
    ) is None

    # Retry after failure must be able to claim again and call save.
    ok_box = FakeSandbox()
    original = ok_box.save_invoice_status

    def save_ok(*a, **k):
        resp = original(*a, **k)
        ok_box.poll_scripts[resp.reference_id] = [_ok()]
        return resp

    ok_box.save_invoice_status = save_ok  # type: ignore[method-assign]
    second = confirm_ims_actions(
        access_token="tok",
        buyer_gstin=GSTIN,
        period=PERIOD,
        actions=[_action("pm:BOOM-1")],
        store=store,
        client=ok_box,
        poll_interval_s=0.0,
        max_polls=3,
        sleep_fn=lambda _s: None,
    )
    assert len(ok_box.save_calls) == 1
    assert second.confirmed_count == 1
    assert second.reused_count == 0
