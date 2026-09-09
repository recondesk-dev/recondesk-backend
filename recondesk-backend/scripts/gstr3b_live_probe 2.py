#!/usr/bin/env python3
"""GSTR-3B live probe — two manually triggered stages (never continuous).

Confirm liability first, then Save only, then (separate run) Offset → File.

  # 0) Fresh OTP session (required — script will NOT reuse an expired row):
  python scripts/gstr3b_live_probe.py auth \\
      --gstin 27ISKPK1273H1ZF --username recondesk_gst

  # 1) Rank periods by real net tax on the portal (read-only):
  python scripts/gstr3b_live_probe.py discover \\
      --gstin 27ISKPK1273H1ZF

  # 2) Stage 1 — Save only. Stops after inner P. Does NOT offset/file.
  python scripts/gstr3b_live_probe.py stage1 \\
      --gstin 27ISKPK1273H1ZF \\
      --period 2026-0X \\
      --save-body scripts/gstr3b_probe_save_body.example.json

  # 3) Stage 2 — separate invocation. Prints offset-preview vs ledger,
  #    waits for typed go-ahead, then Offset → poll P → EVC → File.
  python scripts/gstr3b_live_probe.py stage2 \\
      --pan <SIGNATORY_PAN>

State file (default): /tmp/recondesk_gstr3b_probe_state.json
Never invents Rule 42/43 or liability — Stage 1 requires your save-body JSON.

Auth notes:
  - discover/stage1/stage2 load a stored filing_sessions row but refuse it when
    token_expires_at is past (skew buffer). Expired rows are marked expired.
  - Prefer ``auth`` (Generate OTP → Verify → insert) before each probe session.
  - Uniform HTTP 403 on Get Details usually means Sandbox rejected the taxpayer
    JWT (expired/invalid). GSTN AUTH/TEC codes normally arrive as HTTP 200
    envelopes with error.error_cd — a different shape.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Backend root on sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_GSTIN = "27ISKPK1273H1ZF"
DEFAULT_CLIENT_GSTIN_ID = "bf298560-cf88-4fd5-9900-1542139ded56"
DEFAULT_STATE = Path(
    os.environ.get(
        "GSTR3B_PROBE_STATE",
        "/tmp/recondesk_gstr3b_probe_state.json",
    )
)
OFFSET_CONFIRM_PREFIX = "OFFSET"
FILE_CONFIRM_PREFIX = "FILE"
# Refuse tokens this close to expiry (clock skew / slow multi-period discover).
TOKEN_SKEW = timedelta(minutes=2)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ROOT / ".env")


def _pp(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


def _money(n: int | float) -> str:
    return f"₹{n:,.2f}"


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _head_tx(row: dict[str, Any], head: str) -> int:
    nested = row.get(head)
    if isinstance(nested, dict):
        return _as_int(nested.get("tx"))
    return 0


def liability_from_details(details: dict[str, Any]) -> dict[str, Any]:
    """Sum net tax payable (IGST+CGST+SGST+CESS tx) from Get Details."""
    tx_pmt = details.get("tx_pmt") if isinstance(details.get("tx_pmt"), dict) else {}
    net_rows = tx_pmt.get("net_tax_pay") if isinstance(tx_pmt, dict) else None
    igst = cgst = sgst = cess = 0
    if isinstance(net_rows, list):
        for row in net_rows:
            if not isinstance(row, dict):
                continue
            igst += _head_tx(row, "igst")
            cgst += _head_tx(row, "cgst")
            sgst += _head_tx(row, "sgst")
            cess += _head_tx(row, "cess")
    else:
        # Fallback: sum proposed cash + ITC utilization (after Save).
        for row in tx_pmt.get("pdcash") or []:
            if not isinstance(row, dict):
                continue
            igst += _as_int(row.get("ipd"))
            cgst += _as_int(row.get("cpd"))
            sgst += _as_int(row.get("spd"))
            cess += _as_int(row.get("cspd"))
        pditc = tx_pmt.get("pditc") if isinstance(tx_pmt.get("pditc"), dict) else {}
        igst += (
            _as_int(pditc.get("i_pdi"))
            + _as_int(pditc.get("i_pdc"))
            + _as_int(pditc.get("i_pds"))
        )
        cgst += _as_int(pditc.get("c_pdi")) + _as_int(pditc.get("c_pdc"))
        sgst += _as_int(pditc.get("s_pdi")) + _as_int(pditc.get("s_pds"))
        cess += _as_int(pditc.get("cs_pdcs"))

    total = igst + cgst + sgst + cess
    return {
        "igst": igst,
        "cgst": cgst,
        "sgst": sgst,
        "cess": cess,
        "total": total,
    }


def cash_itc_from_offset(offset_body: dict[str, Any]) -> dict[str, Any]:
    cash = {"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "total": 0}
    for row in offset_body.get("pdcash") or []:
        if not isinstance(row, dict):
            continue
        cash["igst"] += _as_int(row.get("ipd"))
        cash["cgst"] += _as_int(row.get("cpd"))
        cash["sgst"] += _as_int(row.get("spd"))
        cash["cess"] += _as_int(row.get("cspd"))
    cash["total"] = cash["igst"] + cash["cgst"] + cash["sgst"] + cash["cess"]

    pditc = offset_body.get("pditc") if isinstance(offset_body.get("pditc"), dict) else {}
    itc = {
        "igst": (
            _as_int(pditc.get("i_pdi"))
            + _as_int(pditc.get("i_pdc"))
            + _as_int(pditc.get("i_pds"))
        ),
        "cgst": _as_int(pditc.get("c_pdi")) + _as_int(pditc.get("c_pdc")),
        "sgst": _as_int(pditc.get("s_pdi")) + _as_int(pditc.get("s_pds")),
        "cess": _as_int(pditc.get("cs_pdcs")),
    }
    itc["total"] = itc["igst"] + itc["cgst"] + itc["sgst"] + itc["cess"]
    return {"cash": cash, "itc": itc}


def ledger_balances(ledger: dict[str, Any]) -> dict[str, Any]:
    itc_bal = ledger.get("itc_bal") if isinstance(ledger.get("itc_bal"), dict) else {}
    cash_bal = ledger.get("cash_bal") if isinstance(ledger.get("cash_bal"), dict) else {}

    def _cash_tx(head: str) -> int:
        nested = cash_bal.get(head)
        if isinstance(nested, dict):
            return _as_int(nested.get("tx"))
        return 0

    return {
        "itc": {
            "igst": _as_int(itc_bal.get("igst_bal")),
            "cgst": _as_int(itc_bal.get("cgst_bal")),
            "sgst": _as_int(itc_bal.get("sgst_bal")),
            "cess": _as_int(itc_bal.get("cess_bal")),
        },
        "cash": {
            "igst": _cash_tx("igst"),
            "cgst": _cash_tx("cgst"),
            "sgst": _cash_tx("sgst"),
            "cess": _cash_tx("cess"),
        },
    }


def default_periods(*, months: int = 12) -> list[str]:
    """Most recent N calendar months ending this month (YYYY-MM)."""
    today = date.today()
    y, m = today.year, today.month
    out: list[str] = []
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"State file missing: {path}\nRun stage1 first.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(_pp(payload) + "\n", encoding="utf-8")
    print(f"\nState written → {path}")


def require_confirm(expected: str, *, prompt: str) -> None:
    print()
    print(prompt)
    print(f'  Type exactly: {expected}')
    print("  Or Ctrl-C to abort.")
    try:
        got = input("> ").strip()
    except EOFError as exc:
        raise SystemExit("No confirmation received — aborted.") from exc
    if got != expected:
        raise SystemExit(f"Confirmation mismatch (got {got!r}) — aborted. Nothing sent.")


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _mark_session_expired(sb, session_id: str) -> None:
    from app.filing import filing_store

    now = datetime.now(timezone.utc).isoformat()
    try:
        sb.table(filing_store.SESSIONS).update(
            {"status": "expired", "updated_at": now}
        ).eq("id", session_id).execute()
    except Exception as exc:  # noqa: BLE001 — probe helper, non-fatal
        print(f"(warn) could not mark session expired: {exc}")


def resolve_token(
    sb,
    *,
    gstin: str,
    session_id: str | None,
    allow_expired: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Load a stored taxpayer token — refuse expired rows unless allow_expired.

    This probe does **not** generate OTP here. Use ``auth`` for a fresh session.
    Earlier bug: status=active rows past token_expires_at were reused → HTTP 403.
    """
    from app.filing import filing_store

    if session_id:
        row = filing_store.get_session_by_id(sb, session_id)
        if not row:
            raise SystemExit(f"filing_sessions id not found: {session_id}")
    else:
        # Prefer not-yet-expired active sessions (same filter as filing_store
        # get_active_session, but firm-agnostic for the probe).
        now_iso = datetime.now(timezone.utc).isoformat()
        res = (
            sb.table(filing_store.SESSIONS)
            .select("*")
            .eq("gstin", gstin.strip().upper())
            .eq("status", "active")
            .gt("token_expires_at", now_iso)
            .order("token_expires_at", desc=True)
            .limit(1)
            .execute()
        )
        row = res.data[0] if res.data else None
        if not row:
            # Surface the latest active-but-expired row for diagnosis.
            stale = (
                sb.table(filing_store.SESSIONS)
                .select("id,gstin,status,token_expires_at,created_at")
                .eq("gstin", gstin.strip().upper())
                .eq("status", "active")
                .order("token_expires_at", desc=True)
                .limit(1)
                .execute()
            )
            if stale.data:
                s = stale.data[0]
                _mark_session_expired(sb, str(s["id"]))
                raise SystemExit(
                    f"Stored session is EXPIRED (not a fresh OTP).\n"
                    f"  session_id={s.get('id')}\n"
                    f"  token_expires_at={s.get('token_expires_at')}\n"
                    f"  now={now_iso}\n"
                    f"Marked that row status=expired. Re-auth:\n"
                    f"  python scripts/gstr3b_live_probe.py auth "
                    f"--gstin {gstin} --username <GST_PORTAL_USERNAME>"
                )
            raise SystemExit(
                f"No active filing_sessions for {gstin}.\n"
                f"  python scripts/gstr3b_live_probe.py auth "
                f"--gstin {gstin} --username <GST_PORTAL_USERNAME>"
            )

    expires = _parse_ts(row.get("token_expires_at"))
    now = datetime.now(timezone.utc)
    if expires is None:
        raise SystemExit(
            f"Session {row.get('id')} has unparseable token_expires_at="
            f"{row.get('token_expires_at')!r} — run auth for a fresh OTP."
        )
    remaining = expires - now
    if remaining <= TOKEN_SKEW and not allow_expired:
        _mark_session_expired(sb, str(row["id"]))
        raise SystemExit(
            f"Stored session expired or within skew buffer — refusing reuse.\n"
            f"  session_id={row.get('id')}\n"
            f"  token_expires_at={expires.isoformat()}\n"
            f"  now={now.isoformat()}\n"
            f"  remaining={remaining}\n"
            f"This is NOT a fresh Generate OTP → Verify. Run:\n"
            f"  python scripts/gstr3b_live_probe.py auth "
            f"--gstin {gstin} --username <GST_PORTAL_USERNAME>"
        )

    token = str(row.get("session_token") or "").strip()
    if not token:
        raise SystemExit("Session row has empty session_token")
    print(
        f"Using stored session_id={row.get('id')} gstin={row.get('gstin')} "
        f"expires={expires.isoformat()} "
        f"(remaining ~{int(remaining.total_seconds())}s) "
        f"— NOT a new OTP; run `auth` if you want a fresh login."
    )
    return token, row


def cmd_auth(args: argparse.Namespace) -> None:
    """Generate OTP → verify → persist filing_sessions (fresh taxpayer token)."""
    from app.database import get_supabase
    from app.filing import filing_store
    from app.filing.sandbox_filing_client import FilingClientError, get_filing_client

    gstin = args.gstin.strip().upper()
    username = args.username.strip()
    client_gstin_id = args.client_gstin_id

    print("\n=== AUTH — fresh Generate OTP → Verify (not reusing store) ===")
    print(f"GSTIN={gstin} username={username}")

    sb = get_supabase()
    # Resolve firm_id from client row (firm_owner_id / assigned_to → user_profiles.id).
    client = (
        sb.table("client_gstins")
        .select("id,gstin,firm_owner_id,assigned_to")
        .eq("id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not client.data:
        raise SystemExit(f"client_gstins id not found: {client_gstin_id}")
    crow = client.data[0]
    if str(crow.get("gstin") or "").strip().upper() != gstin:
        raise SystemExit(
            f"client_gstin_id GSTIN {crow.get('gstin')} != --gstin {gstin}"
        )
    firm_id = str(
        crow.get("firm_owner_id") or crow.get("assigned_to") or ""
    ).strip()
    if not firm_id:
        # Fallback: any prior session's firm_id for this GSTIN.
        prior = (
            sb.table(filing_store.SESSIONS)
            .select("firm_id")
            .eq("gstin", gstin)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        firm_id = str((prior.data or [{}])[0].get("firm_id") or "").strip()
    if not firm_id:
        raise SystemExit(
            "Cannot resolve firm_id for filing_sessions insert. "
            "Ensure client_gstins has firm_owner_id/assigned_to, "
            "or create one session via the UI once."
        )

    with get_filing_client() as client_api:
        try:
            envelope = client_api.generate_otp(username=username, gstin=gstin)
        except FilingClientError as exc:
            raise SystemExit(
                f"Generate OTP failed: {exc}\n"
                "If this is AUTH/API-access related, re-check GST portal "
                "Manage API Access (Enable API Request = Yes, duration not expired)."
            ) from exc
        print("OTP sent. Sandbox envelope (scrubbed fields only):")
        print(
            _pp(
                {
                    "transaction_id": envelope.get("transaction_id"),
                    "code": envelope.get("code"),
                    "status_cd": (envelope.get("data") or {}).get("status_cd")
                    if isinstance(envelope.get("data"), dict)
                    else None,
                }
            )
        )
        try:
            otp = input("Enter GSTN OTP (not logged): ").strip()
        except EOFError as exc:
            raise SystemExit("No OTP — auth aborted.") from exc
        if not otp:
            raise SystemExit("Empty OTP — auth aborted.")
        try:
            session = client_api.verify_otp(
                username=username, gstin=gstin, otp=otp,
            )
        except FilingClientError as exc:
            raise SystemExit(
                f"Verify OTP failed: {exc}\n"
                "AUTH4033 Invalid Session / similar GSTN codes usually mean "
                "API Access not enabled, OTP stale, or portal session issues — "
                "not the same as bare HTTP 403 on later Get Details."
            ) from exc

    row = filing_store.create_session(
        sb,
        firm_id=firm_id,
        gstin=gstin,
        username=username,
        session=session,
        client_gstin_id=client_gstin_id,
    )
    print("\nFresh session stored:")
    print(f"  session_id={row.get('id')}")
    print(f"  token_expires_at={row.get('token_expires_at')}")
    print(f"  session_expires_at={row.get('session_expires_at')}")
    print("\nNext: python scripts/gstr3b_live_probe.py discover --gstin", gstin)


def cmd_discover(args: argparse.Namespace) -> None:
    from app.database import get_supabase
    from app.filing.sandbox_filing_client import (
        FilingAuthError,
        FilingClientError,
        get_filing_client,
    )

    sb = get_supabase()
    token, session_row = resolve_token(
        sb, gstin=args.gstin, session_id=args.session_id,
    )
    periods = args.periods or default_periods(months=args.months)

    print(f"\n=== Discover liability (read-only Get Details) for {args.gstin} ===")
    print(f"Periods: {', '.join(periods)}\n")

    rows: list[dict[str, Any]] = []
    with get_filing_client() as client:
        for period in periods:
            try:
                result = client.get_gstr3b_details(token, period=period)
                details = result.data if isinstance(result.data, dict) else {}
                liab = liability_from_details(details)
                rows.append(
                    {
                        "period": period,
                        "ok": True,
                        "liability": liab,
                        "error": None,
                    }
                )
                print(
                    f"  {period}  total={_money(liab['total'])}  "
                    f"(IGST {_money(liab['igst'])} CGST {_money(liab['cgst'])} "
                    f"SGST {_money(liab['sgst'])} CESS {_money(liab['cess'])})"
                )
            except FilingAuthError as exc:
                # Uniform 403 across periods = taxpayer JWT rejected by Sandbox.
                raise SystemExit(
                    f"\nAuth failure on Get Details for {period}: {exc}\n"
                    f"session_id={session_row.get('id')} "
                    f"token_expires_at={session_row.get('token_expires_at')}\n"
                    "Bare HTTP 401/403 is Sandbox rejecting the Authorization "
                    "token (expired/invalid JWT) — typical for a stale stored "
                    "session. GSTN AUTH/TEC codes usually arrive as HTTP 200 "
                    "with error.error_cd instead.\n"
                    "If a *fresh* OTP session still 403s, also re-check GST "
                    "portal Manage API Access (30-day window).\n"
                    f"  python scripts/gstr3b_live_probe.py auth "
                    f"--gstin {args.gstin} --username <GST_PORTAL_USERNAME>"
                ) from exc
            except FilingClientError as exc:
                rows.append(
                    {
                        "period": period,
                        "ok": False,
                        "liability": None,
                        "error": str(exc),
                    }
                )
                print(f"  {period}  SKIP — {exc}")

    ok_rows = [r for r in rows if r["ok"] and r["liability"] is not None]
    if not ok_rows:
        raise SystemExit(
            "\nNo period returned usable Get Details. "
            "Check OTP session / API access / period list."
        )

    best = min(ok_rows, key=lambda r: r["liability"]["total"])
    liab = best["liability"]
    print("\n" + "=" * 60)
    print("SMALLEST REAL LIABILITY (from portal Get Details)")
    print("=" * 60)
    print(f"  GSTIN:    {args.gstin}")
    print(f"  Period:   {best['period']}")
    print(f"  Total:    {_money(liab['total'])}")
    print(f"  Breakdown IGST={_money(liab['igst'])} CGST={_money(liab['cgst'])} "
          f"SGST={_money(liab['sgst'])} CESS={_money(liab['cess'])}")
    print()
    print("Review this amount before agreeing to Stage 2 Offset.")
    print("Stage 1 does NOT move money — it only Saves figures.")
    print("Stage 2 Offset will allocate ITC/cash against this liability.")
    print()
    print("Next:")
    print(
        f"  python scripts/gstr3b_live_probe.py stage1 "
        f"--gstin {args.gstin} --period {best['period']} "
        f"--save-body <YOUR_CONFIRMED_SAVE.json>"
    )


def cmd_stage1(args: argparse.Namespace) -> None:
    from app.database import get_supabase
    from app.filing import filing_store
    from app.filing.sandbox_filing_client import (
        FilingClientError,
        get_filing_client,
        period_to_fp,
    )

    save_path = Path(args.save_body)
    if not save_path.is_file():
        raise SystemExit(f"save-body not found: {save_path}")
    save_body = json.loads(save_path.read_text(encoding="utf-8"))
    if not isinstance(save_body, dict):
        raise SystemExit("save-body must be a JSON object")

    gstin = args.gstin.strip().upper()
    period = args.period.strip()
    save_body.setdefault("gstin", gstin)
    save_body.setdefault("ret_period", period_to_fp(period))

    print("\n=== STAGE 1 — Save only (will STOP after inner P) ===")
    print(f"GSTIN={gstin} period={period}")
    print("Save body you are about to POST:")
    print(_pp(save_body))
    require_confirm(
        f"SAVE {period}",
        prompt="Confirm Stage 1 Save (does NOT Offset/File):",
    )

    sb = get_supabase()
    token, session_row = resolve_token(sb, gstin=gstin, session_id=args.session_id)
    firm_id = str(session_row.get("firm_id") or "")
    if not firm_id:
        raise SystemExit("Session has no firm_id")

    try:
        filing_store.assert_gstr3b_save_allowed(sb, gstin=gstin, period=period)
    except filing_store.Gstr3bPeriodLockedError as exc:
        raise SystemExit(
            f"Period locked after prior Offset — cannot Save: {exc}"
        ) from exc

    run = filing_store.create_run(
        sb,
        firm_id=firm_id,
        gstin=gstin,
        period=period,
        return_type=filing_store.RETURN_TYPE_GSTR3B,
        filing_session_id=str(session_row["id"]),
        client_gstin_id=args.client_gstin_id,
        save_payload=save_body,
        status="draft",
    )
    run_id = str(run["id"])
    print(f"Created filing_runs.id={run_id}")

    with get_filing_client() as client:
        try:
            result = client.save_gstr3b(
                token, period=period, save_body=save_body, sb=sb,
            )
        except FilingClientError as exc:
            filing_store.mark_run_failed(
                sb,
                run_id,
                error_code=getattr(exc, "error_cd", None),
                error_message=str(exc),
                raw_response=getattr(exc, "envelope", None),
            )
            raise SystemExit(f"Save failed: {exc}") from exc

        ref = result.reference_id
        if not ref:
            raise SystemExit(f"Save returned no reference_id:\n{_pp(result.envelope)}")

        filing_store.update_run(
            sb,
            run_id,
            status="save_pending",
            reference_id=ref,
            raw_response=result.envelope,
            clear_error=True,
        )
        print(f"Save accepted for processing. reference_id={ref}")
        print("Polling Return Status for inner P …")

        polled = client.wait_for_return_status(
            token,
            period=period,
            reference_id=ref,
            poll_interval_sec=args.poll_interval,
            max_attempts=args.poll_attempts,
        )
        info = polled.return_status
        updated = filing_store.apply_save_status_to_run(
            sb, run_id, return_status=info, envelope=polled.envelope,
        )
        print(
            f"Poll done: gstn_status_cd={getattr(info, 'gstn_status_cd', None)} "
            f"run_status={updated.get('status')} "
            f"error={getattr(info, 'error_cd', None)} "
            f"{getattr(info, 'error_message', None) or ''}"
        )
        if not (info and info.is_success):
            raise SystemExit("Stage 1 aborted — Save did not reach inner P.")

        # Re-fetch portal details so we print what GSTN actually holds.
        details = client.get_gstr3b_details(token, period=period)
        details_data = details.data if isinstance(details.data, dict) else {}
        liab = liability_from_details(details_data)

    state = {
        "stage": "stage1_complete",
        "gstin": gstin,
        "period": period,
        "run_id": run_id,
        "session_id": str(session_row["id"]),
        "client_gstin_id": args.client_gstin_id,
        "firm_id": firm_id,
        "save_reference_id": ref,
        "run_status": updated.get("status"),
        "save_body": save_body,
        "portal_details_after_save": details_data,
        "liability_after_save": liab,
    }
    save_state(Path(args.state), state)

    print("\n" + "=" * 60)
    print("STAGE 1 COMPLETE — STOPPING HERE")
    print("=" * 60)
    print(f"  run_id:            {run_id}")
    print(f"  save_reference_id: {ref}")
    print(f"  run_status:        {updated.get('status')}")
    print(f"  liability now:     {_money(liab['total'])} "
          f"(IGST {_money(liab['igst'])} CGST {_money(liab['cgst'])} "
          f"SGST {_money(liab['sgst'])} CESS {_money(liab['cess'])})")
    print("\nSaved figures (save_body posted):")
    print(_pp(save_body))
    print("\nPortal Get Details after Save (truncated keys):")
    print(
        _pp(
            {
                "gstin": details_data.get("gstin"),
                "ret_period": details_data.get("ret_period"),
                "sup_details": details_data.get("sup_details"),
                "itc_elg": details_data.get("itc_elg"),
                "tx_pmt": details_data.get("tx_pmt"),
            }
        )
    )
    print("\n*** Offset / EVC / File were NOT run. ***")
    print("Review the figures above. Only then invoke Stage 2:")
    print(
        f"  python scripts/gstr3b_live_probe.py stage2 "
        f"--pan <SIGNATORY_PAN> --state {args.state}"
    )


def cmd_stage2(args: argparse.Namespace) -> None:
    from app.database import get_supabase
    from app.filing import filing_store
    from app.filing.gstr3b_offset import build_gstr3b_offset_body
    from app.filing.sandbox_filing_client import FilingClientError, get_filing_client

    state_path = Path(args.state)
    state = load_state(state_path)
    if state.get("stage") not in ("stage1_complete", "stage2_offset_complete"):
        raise SystemExit(
            f"Unexpected state.stage={state.get('stage')!r}. "
            "Run stage1 to completion first."
        )

    gstin = str(state["gstin"])
    period = str(state["period"])
    run_id = str(state["run_id"])
    pan = args.pan.strip().upper()

    print("\n=== STAGE 2 — Offset preview (nothing posted yet) ===")
    print(f"GSTIN={gstin} period={period} run_id={run_id}")

    sb = get_supabase()
    token, _ = resolve_token(
        sb, gstin=gstin, session_id=args.session_id or state.get("session_id"),
    )

    with get_filing_client() as client:
        details = client.get_gstr3b_details(token, period=period)
        ledger = client.get_ledger_balance(token, period=period)
        details_data = details.data if isinstance(details.data, dict) else {}
        ledger_data = ledger.data if isinstance(ledger.data, dict) else {}
        try:
            offset_body = build_gstr3b_offset_body(details_data, ledger_data)
        except Exception as exc:
            raise SystemExit(f"offset-preview build failed: {exc}") from exc

        liab = liability_from_details(details_data)
        moved = cash_itc_from_offset(offset_body)
        bal = ledger_balances(ledger_data)

        print("\n--- Liability (portal net tax) ---")
        print(f"  total {_money(liab['total'])}  "
              f"IGST {_money(liab['igst'])} CGST {_money(liab['cgst'])} "
              f"SGST {_money(liab['sgst'])} CESS {_money(liab['cess'])}")

        print("\n--- Exact {pdcash, pditc} that would be POSTed ---")
        print(_pp(offset_body))
        print("\n--- Summarised movement ---")
        print(
            f"  Cash to apply: {_money(moved['cash']['total'])} "
            f"(IGST {_money(moved['cash']['igst'])} "
            f"CGST {_money(moved['cash']['cgst'])} "
            f"SGST {_money(moved['cash']['sgst'])} "
            f"CESS {_money(moved['cash']['cess'])})"
        )
        print(
            f"  ITC to apply:  {_money(moved['itc']['total'])} "
            f"(IGST {_money(moved['itc']['igst'])} "
            f"CGST {_money(moved['itc']['cgst'])} "
            f"SGST {_money(moved['itc']['sgst'])} "
            f"CESS {_money(moved['itc']['cess'])})"
        )

        print("\n--- Real ledger balance (available) ---")
        print(
            f"  Cash: IGST {_money(bal['cash']['igst'])} "
            f"CGST {_money(bal['cash']['cgst'])} "
            f"SGST {_money(bal['cash']['sgst'])} "
            f"CESS {_money(bal['cash']['cess'])}"
        )
        print(
            f"  ITC:  IGST {_money(bal['itc']['igst'])} "
            f"CGST {_money(bal['itc']['cgst'])} "
            f"SGST {_money(bal['itc']['sgst'])} "
            f"CESS {_money(bal['itc']['cess'])}"
        )

        if args.preview_only:
            print("\n--preview-only set. Stopping before Offset.")
            return

        require_confirm(
            f"{OFFSET_CONFIRM_PREFIX} {period}",
            prompt=(
                "This will POST Offset Liability to GSTN and permanently "
                "gate further Saves for this period after inner P.\n"
                "Confirm Offset:"
            ),
        )

        print("\n=== STAGE 2a — Offset Liability ===")
        try:
            filing_store.assert_gstr3b_offset_allowed(
                sb, gstin=gstin, period=period,
            )
            offset_result = client.offset_gstr3b_liability(
                token,
                period=period,
                gstin=gstin,
                offset_body=offset_body,
                sb=sb,
            )
        except FilingClientError as exc:
            filing_store.mark_run_failed(
                sb,
                run_id,
                error_code=getattr(exc, "error_cd", None),
                error_message=str(exc),
                raw_response=getattr(exc, "envelope", None),
            )
            raise SystemExit(f"Offset failed: {exc}") from exc
        except filing_store.Gstr3bPeriodLockedError as exc:
            raise SystemExit(f"Period locked: {exc}") from exc

        oref = offset_result.reference_id
        if not oref:
            raise SystemExit(
                f"Offset returned no reference_id:\n{_pp(offset_result.envelope)}"
            )
        filing_store.update_run(
            sb,
            run_id,
            status="offset_pending",
            reference_id=oref,
            raw_response=offset_result.envelope,
            offset_payload=offset_body,
            clear_error=True,
        )
        print(f"Offset accepted. reference_id={oref}")
        print("Polling Return Status for inner P …")

        polled = client.wait_for_return_status(
            token,
            period=period,
            reference_id=oref,
            poll_interval_sec=args.poll_interval,
            max_attempts=args.poll_attempts,
        )
        info = polled.return_status
        details_after = client.get_gstr3b_details(token, period=period)
        tx_pmt = None
        if isinstance(details_after.data, dict):
            tx_pmt = details_after.data.get("tx_pmt") or details_after.data
        updated = filing_store.apply_offset_status_to_run(
            sb,
            run_id,
            return_status=info,
            envelope=polled.envelope,
            offset_payload=offset_body,
            tx_pmt_snapshot=tx_pmt if isinstance(tx_pmt, dict) else None,
        )
        print(
            f"Offset poll: gstn_status_cd={getattr(info, 'gstn_status_cd', None)} "
            f"run_status={updated.get('status')}"
        )
        if not (info and info.is_success):
            raise SystemExit("Offset did not reach inner P — File aborted.")

        state["stage"] = "stage2_offset_complete"
        state["offset_reference_id"] = oref
        state["offset_payload"] = offset_body
        state["run_status"] = updated.get("status")
        save_state(state_path, state)

        print("\n=== STAGE 2b — EVC + File ===")
        print(f"Generating EVC OTP for PAN {pan[:5]}***** …")
        try:
            client.generate_evc_otp_gstr3b(token, pan=pan)
        except FilingClientError as exc:
            raise SystemExit(f"EVC OTP generate failed: {exc}") from exc
        filing_store.update_run(sb, run_id, status="evc_pending", clear_error=True)
        print("EVC OTP sent to registered mobile/email.")

        try:
            otp = input("Enter EVC OTP (not logged): ").strip()
        except EOFError as exc:
            raise SystemExit("No OTP — File aborted.") from exc
        if not otp:
            raise SystemExit("Empty OTP — File aborted.")

        require_confirm(
            f"{FILE_CONFIRM_PREFIX} {period}",
            prompt="Final confirmation to FILE GSTR-3B on GSTN:",
        )

        file_body = (
            dict(details_after.data)
            if isinstance(details_after.data, dict)
            else {}
        )
        try:
            filed = client.file_gstr3b(
                token,
                period=period,
                pan=pan,
                otp=otp,
                file_body=file_body,
            )
        except FilingClientError as exc:
            filing_store.mark_run_failed(
                sb,
                run_id,
                error_code=getattr(exc, "error_cd", None),
                error_message=str(exc),
                raw_response=getattr(exc, "envelope", None),
            )
            raise SystemExit(f"File failed: {exc}") from exc

        filing_store.update_run(
            sb,
            run_id,
            status="filed",
            ack_number=filed.ack_number,
            raw_response=filed.envelope,
            clear_error=True,
        )
        state["stage"] = "stage2_filed"
        state["ack_number"] = filed.ack_number
        state["run_status"] = "filed"
        save_state(state_path, state)

        print("\n" + "=" * 60)
        print("STAGE 2 COMPLETE — FILED")
        print("=" * 60)
        print(f"  ack_number: {filed.ack_number}")
        print(f"  run_id:     {run_id}")
        print(f"  period:     {period}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="GSTR-3B live probe (discover / stage1 Save / stage2 Offset+File)",
    )
    p.add_argument(
        "--state",
        default=str(DEFAULT_STATE),
        help=f"Probe state JSON (default {DEFAULT_STATE})",
    )
    p.add_argument("--session-id", default=None, help="Optional filing_sessions.id")
    p.add_argument(
        "--poll-interval", type=float, default=2.0, help="Return Status poll seconds",
    )
    p.add_argument(
        "--poll-attempts", type=int, default=45, help="Max Return Status polls",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser(
        "auth",
        help="Fresh Generate OTP → Verify → store filing_sessions (required if expired)",
    )
    a.add_argument("--gstin", default=DEFAULT_GSTIN)
    a.add_argument("--username", required=True, help="GST portal username")
    a.add_argument("--client-gstin-id", default=DEFAULT_CLIENT_GSTIN_ID)
    a.set_defaults(func=cmd_auth)

    d = sub.add_parser("discover", help="Rank periods by portal net liability (read-only)")
    d.add_argument("--gstin", default=DEFAULT_GSTIN)
    d.add_argument(
        "--months", type=int, default=12, help="How many recent months to scan",
    )
    d.add_argument(
        "--periods",
        nargs="*",
        help="Explicit YYYY-MM list (overrides --months)",
    )
    d.set_defaults(func=cmd_discover)

    s1 = sub.add_parser("stage1", help="Save only → poll inner P → STOP")
    s1.add_argument("--gstin", default=DEFAULT_GSTIN)
    s1.add_argument("--period", required=True, help="YYYY-MM")
    s1.add_argument(
        "--save-body",
        required=True,
        help="JSON file of CA-confirmed Save body (never invented by this script)",
    )
    s1.add_argument("--client-gstin-id", default=DEFAULT_CLIENT_GSTIN_ID)
    s1.set_defaults(func=cmd_stage1)

    s2 = sub.add_parser(
        "stage2",
        help="offset-preview → confirm → Offset → EVC → File",
    )
    s2.add_argument("--pan", required=True, help="Authorized signatory PAN for EVC")
    s2.add_argument(
        "--preview-only",
        action="store_true",
        help="Print {pdcash,pditc} vs ledger and exit (no Offset)",
    )
    s2.set_defaults(func=cmd_stage2)

    return p


def main(argv: list[str] | None = None) -> None:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
