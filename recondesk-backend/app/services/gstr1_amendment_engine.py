"""GSTR-1 Amendment Processing Engine.

Resolves Table 9A (B2BA), 9B (CDNR), and 9C (CDNA) amendments back to source
Sales Register documents and prior-period filed GSTR-1 returns.

Features:
- Deterministic resolver: GSTIN + original document number + date -> GSTIN + doc -> doc
- Strict normalized matching (never fuzzy rescues invalid references)
- Full duplicate-chain analysis: chronological sequencing, terminal successorship,
  single source accounting, and MULTIPLE_AMENDMENTS_SAME_ORIGINAL review flag
- Invalid link handling: routes unresolvable amendment references to
  AMENDMENT_ORIGINAL_NOT_FOUND review items
- Document-type aware delta calculations (Credit Notes, Debit Notes, Invoices)
- Produces canonical records for export and UI presentation
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Mapping, Sequence

from app.models.canonical_amendment import CanonicalAmendment
from app.rules.gstr1_mismatch_rules import (
    MismatchResult,
    MismatchSeverity,
    MismatchType,
    _safe_int,
    _rs,
)
from app.services.matcher import normalise_inv_no, normalize_invoice

logger = logging.getLogger(__name__)


def _is_credit_note_type(doc_type_or_ntty: str | None) -> bool:
    s = str(doc_type_or_ntty or "").strip().upper()
    return s in ("C", "CR", "CREDIT", "CREDIT_NOTE", "C_N")


def _is_debit_note_type(doc_type_or_ntty: str | None) -> bool:
    s = str(doc_type_or_ntty or "").strip().upper()
    return s in ("D", "DR", "DEBIT", "DEBIT_NOTE", "D_N")


def _norm_date_str(d: str) -> str:
    s = str(d or "").strip()[:10]
    if len(s) == 10:
        if s[2] == "-" and s[5] == "-":
            # DD-MM-YYYY -> YYYY-MM-DD
            return f"{s[6:]}-{s[3:5]}-{s[:2]}"
        if s[4] == "-" and s[7] == "-":
            return s
    return s


def _extract_amendment_original_keys(amendment: Mapping[str, Any]) -> dict[str, str]:
    """Extract and normalize candidate lookup keys from an amendment record."""
    section = str(amendment.get("section") or "").lower().strip()
    is_cdn = section in ("cdnr", "cdnra", "cdna", "cdnur", "cdnura", "cdnua")

    orig_num_raw = (
        (amendment.get("ont_num") if is_cdn else amendment.get("oinum"))
        or amendment.get("original_invoice_number_raw")
        or amendment.get("original_invoice_number")
        or amendment.get("oinum")
        or amendment.get("ont_num")
        or ""
    )
    orig_num_raw = str(orig_num_raw).strip()

    orig_date = str(
        (amendment.get("ont_dt") if is_cdn else amendment.get("oidt"))
        or amendment.get("original_invoice_date")
        or amendment.get("original_invoice_date_raw")
        or amendment.get("oidt")
        or amendment.get("ont_dt")
        or ""
    ).strip()
    if len(orig_date) > 10:
        orig_date = orig_date[:10]
    norm_orig_date = _norm_date_str(orig_date)

    norm_orig = normalize_invoice(orig_num_raw) if orig_num_raw else ""
    alphanumeric_orig = normalise_inv_no(orig_num_raw) if orig_num_raw else ""

    gstin = str(
        amendment.get("recipient_gstin")
        or amendment.get("ctin")
        or amendment.get("gstin")
        or ""
    ).strip().upper()

    ntty = str(amendment.get("ntty") or amendment.get("doc_type") or "").strip().upper()

    return {
        "raw_num": orig_num_raw,
        "norm_num": norm_orig,
        "alnum_num": alphanumeric_orig,
        "date": norm_orig_date or orig_date,
        "raw_date": orig_date,
        "gstin": gstin,
        "ntty": ntty,
        "section": section,
        "is_cdn": "true" if is_cdn else "false",
    }


def _index_records_for_amendment_lookup(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build multi-tier lookup indices over source or prior records."""
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for rec in records:
        r_dict = rec  # Preserve original reference for identity tracking
        inv_raw = str(
            r_dict.get("invoice_number_raw")
            or r_dict.get("invoice_number")
            or r_dict.get("inum")
            or r_dict.get("nt_num")
            or ""
        ).strip()
        norm_inv = normalize_invoice(inv_raw) if inv_raw else ""
        alnum_inv = normalise_inv_no(inv_raw) if inv_raw else ""

        gstin = str(
            r_dict.get("gstin")
            or r_dict.get("recipient_gstin")
            or r_dict.get("ctin")
            or ""
        ).strip().upper()

        dt = str(
            r_dict.get("invoice_date")
            or r_dict.get("invoice_date_norm")
            or r_dict.get("dt")
            or ""
        ).strip()[:10]

        doc_type = str(
            r_dict.get("document_type")
            or r_dict.get("doc_type")
            or r_dict.get("invoice_type")
            or ""
        ).strip().upper()

        is_cn = _is_credit_note_type(doc_type) or bool(r_dict.get("is_credit_note"))
        is_dn = _is_debit_note_type(doc_type) or bool(r_dict.get("is_debit_note"))
        ntty_key = "C" if is_cn else ("D" if is_dn else "INV")

        dates_to_index = set(filter(None, [dt, _norm_date_str(dt)]))

        for key_num in set(filter(None, [norm_inv, alnum_inv])):
            # Tier 1: gstin + num + date + type
            if gstin:
                for d_val in dates_to_index:
                    index[f"GNDT::{gstin}::{key_num}::{d_val}::{ntty_key}"].append(r_dict)
                    index[f"GNDT::{gstin}::{key_num}::{d_val}"].append(r_dict)

            # Tier 2: gstin + num + type
            if gstin:
                index[f"GNT::{gstin}::{key_num}::{ntty_key}"].append(r_dict)
                index[f"GN::{gstin}::{key_num}"].append(r_dict)

            # Tier 3: num + type
            index[f"NT::{key_num}::{ntty_key}"].append(r_dict)
            index[f"N::{key_num}"].append(r_dict)

    return index


def resolve_amendment_original(
    amendment: Mapping[str, Any],
    sales_register_records: Sequence[Mapping[str, Any]] | None = None,
    prior_period_records: Sequence[Mapping[str, Any]] | None = None,
    *,
    sr_index: dict[str, list[dict[str, Any]]] | None = None,
    prior_index: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Deterministically resolve an amendment's original document.

    Checks Sales Register first, then Prior GSTR-1.
    Precedence:
      1. (GSTIN, Normalized Document Number, Date, Note Type)
      2. (GSTIN, Normalized Document Number, Note Type / Generic)
      3. (Normalized Document Number, Note Type / Generic)

    Never fuzzy rescues invalid invoice numbers.
    """
    keys = _extract_amendment_original_keys(amendment)
    norm_num = keys["norm_num"]
    alnum_num = keys["alnum_num"]
    gstin = keys["gstin"]
    dt = keys["date"]
    ntty = "C" if _is_credit_note_type(keys["ntty"]) else ("D" if _is_debit_note_type(keys["ntty"]) else "INV")

    if not norm_num and not alnum_num:
        return None, None

    if sr_index is None and sales_register_records:
        sr_index = _index_records_for_amendment_lookup(sales_register_records)
    if prior_index is None and prior_period_records:
        prior_index = _index_records_for_amendment_lookup(prior_period_records)

    def _query(idx: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
        for num in set(filter(None, [norm_num, alnum_num])):
            # 1. GSTIN + Doc + Date + Type
            if gstin and dt:
                res = idx.get(f"GNDT::{gstin}::{num}::{dt}::{ntty}")
                if res:
                    return res[0]
                res = idx.get(f"GNDT::{gstin}::{num}::{dt}")
                if res:
                    return res[0]

            # 2. GSTIN + Doc + Type
            if gstin:
                res = idx.get(f"GNT::{gstin}::{num}::{ntty}")
                if res:
                    return res[0]
                res = idx.get(f"GN::{gstin}::{num}")
                if res:
                    return res[0]

            # 3. Doc + Type
            res = idx.get(f"NT::{num}::{ntty}")
            if res:
                return res[0]
            res = idx.get(f"N::{num}")
            if res:
                return res[0]

        return None

    # Try Sales Register first
    if sr_index:
        match = _query(sr_index)
        if match:
            return match, "SALES_REGISTER"

    # Try Prior GSTR-1 second
    if prior_index:
        match = _query(prior_index)
        if match:
            return match, "PRIOR_GSTR1"

    return None, None


def _extract_paise_field(rec: Mapping[str, Any] | None, *field_names: str) -> int:
    if not rec:
        return 0
    for name in field_names:
        p = rec.get(f"{name}_paise")
        if p is not None:
            return _safe_int(p)
    for name in field_names:
        val = rec.get(name)
        if val is not None:
            try:
                return round(float(val) * 100)
            except (ValueError, TypeError):
                pass
    return 0


def build_canonical_amendment(
    amendment_rec: Mapping[str, Any],
    original_rec: Mapping[str, Any] | None,
    original_source: str | None,
    filing_period: str | None = None,
    *,
    chain_id: str | None = None,
    chain_position: int = 1,
    is_latest_effective_amendment: bool = True,
) -> CanonicalAmendment:
    """Build CanonicalAmendment with exact integer paise and rupee deltas.

    Amendment delta semantics
    -------------------------
    - For resolved amendments (original_found=True): delta = amended_signed - original_signed
    - Debit note sign: positive (adds to liability)
    - Credit note sign: negative (reduces liability)
    - Zero-economic amendments (number/date only): all deltas are zero
    - Unresolved amendments (original_found=False): delta = 0 for all fields
      (the amendment is flagged via mismatch result; it is NOT silently counted)
    """
    sec = str(amendment_rec.get("section") or "").lower().strip()

    # ── Determine document type ──────────────────────────────────────────────
    # Priority: explicit ntty/doc_type on amendment → source record document_type
    # → invoice number prefix for debit notes (portal sometimes omits ntty on DNs)
    ntty = str(amendment_rec.get("ntty") or amendment_rec.get("doc_type") or "").strip().upper()
    orig_doc_type = str((original_rec.get("document_type") if original_rec else "") or "").strip().upper()

    # Check debit note first (in case ntty is ambiguous)
    is_dn = (
        _is_debit_note_type(ntty)
        or _is_debit_note_type(orig_doc_type)
        or bool(amendment_rec.get("is_debit_note"))
        or bool(original_rec and original_rec.get("is_debit_note"))
    )
    # Fallback: portal sometimes omits ntty on DN amendments — infer from invoice prefix
    if not is_dn and not _is_credit_note_type(ntty):
        inv_raw = str(
            amendment_rec.get("invoice_number_raw")
            or amendment_rec.get("invoice_number")
            or amendment_rec.get("inum")
            or amendment_rec.get("nt_num")
            or ""
        ).strip().upper()
        if inv_raw[:3] in ("DN/", "DR/") or inv_raw[:3] in ("DN-", "DR-"):
            is_dn = True

    is_cn = False
    if not is_dn:
        is_cn = (
            _is_credit_note_type(ntty)
            or _is_credit_note_type(orig_doc_type)
            or bool(amendment_rec.get("is_credit_note"))
            or bool(original_rec and original_rec.get("is_credit_note"))
            or sec in ("cdnr", "cdnra", "cdna", "cdnur", "cdnura")
        )

    doc_type = "CREDIT_NOTE" if is_cn else ("DEBIT_NOTE" if is_dn else "INVOICE")

    # ── Document identities ───────────────────────────────────────────────────
    amended_inv = str(
        amendment_rec.get("invoice_number_raw")
        or amendment_rec.get("invoice_number")
        or amendment_rec.get("inum")
        or amendment_rec.get("nt_num")
        or ""
    ).strip()

    amended_dt = str(
        amendment_rec.get("invoice_date")
        or amendment_rec.get("invoice_date_norm")
        or amendment_rec.get("idt")
        or amendment_rec.get("nt_dt")
        or ""
    ).strip()[:10]

    orig_keys = _extract_amendment_original_keys(amendment_rec)
    orig_inv = orig_keys["raw_num"] or (
        str(original_rec.get("invoice_number_raw") or original_rec.get("invoice_number") or "")
        if original_rec
        else None
    )
    orig_dt = orig_keys["date"] or (
        str(original_rec.get("invoice_date") or original_rec.get("invoice_date_norm") or "")[:10]
        if original_rec
        else None
    )

    recipient_gstin = (
        orig_keys["gstin"]
        or (str(original_rec.get("recipient_gstin") or original_rec.get("gstin") or "") if original_rec else None)
    )

    # ── Signed paise values ───────────────────────────────────────────────────
    # For credit notes, economic sign is negative (reduction in liability).
    # In portal GSTR-1 JSON, CDN taxable amounts are reported as positive integers
    # with ntty='C'.  The sign is applied here via amend_mult.
    amend_mult = -1 if is_cn else 1
    amend_tx_paise = _extract_paise_field(amendment_rec, "taxable_amount", "txval", "taxable")
    amend_igst_paise = _extract_paise_field(amendment_rec, "igst", "iamt")
    amend_cgst_paise = _extract_paise_field(amendment_rec, "cgst", "camt")
    amend_sgst_paise = _extract_paise_field(amendment_rec, "sgst", "samt")
    amend_cess_paise = _extract_paise_field(amendment_rec, "cess", "csamt")

    if original_rec:
        # Sales Register credit notes carry negative amounts; portal amounts are positive.
        # abs() normalises then applies orig_mult to get a consistent signed value.
        orig_mult = -1 if is_cn else 1
        orig_raw_tx = _extract_paise_field(original_rec, "taxable_amount", "txval", "taxable")
        orig_tx_paise = abs(orig_raw_tx) * orig_mult
        orig_igst_paise = abs(_extract_paise_field(original_rec, "igst", "iamt")) * orig_mult
        orig_cgst_paise = abs(_extract_paise_field(original_rec, "cgst", "camt")) * orig_mult
        orig_sgst_paise = abs(_extract_paise_field(original_rec, "sgst", "samt")) * orig_mult
        orig_cess_paise = abs(_extract_paise_field(original_rec, "cess", "csamt")) * orig_mult
    else:
        # Unresolved amendment: original not found — delta is zero to avoid
        # silently inflating GSTR-3B liability.  The mismatch result handles review.
        orig_tx_paise = 0
        orig_igst_paise = 0
        orig_cgst_paise = 0
        orig_sgst_paise = 0
        orig_cess_paise = 0

    effective_amend_tx = amend_tx_paise * amend_mult
    effective_amend_igst = amend_igst_paise * amend_mult
    effective_amend_cgst = amend_cgst_paise * amend_mult
    effective_amend_sgst = amend_sgst_paise * amend_mult
    effective_amend_cess = amend_cess_paise * amend_mult

    delta_tx_paise = effective_amend_tx - orig_tx_paise
    delta_igst_paise = effective_amend_igst - orig_igst_paise
    delta_cgst_paise = effective_amend_cgst - orig_cgst_paise
    delta_sgst_paise = effective_amend_sgst - orig_sgst_paise
    delta_cess_paise = effective_amend_cess - orig_cess_paise

    # ── Amendment type classification ─────────────────────────────────────────
    amendment_type = "NO_CHANGE"
    if orig_inv and amended_inv and normalize_invoice(orig_inv) != normalize_invoice(amended_inv):
        amendment_type = "INVOICE_NUMBER_AMENDMENT"
    elif orig_dt and amended_dt and orig_dt != amended_dt:
        amendment_type = "DATE_AMENDMENT"
    elif delta_tx_paise != 0 or delta_igst_paise != 0 or delta_cgst_paise != 0 or delta_sgst_paise != 0:
        amendment_type = "VALUE_AMENDMENT"

    source_period = (
        str(original_rec.get("filing_period") or original_rec.get("fp") or "")
        if original_rec
        else None
    )

    # ── Zero-rated classification ─────────────────────────────────────────────
    # Determine whether this amendment belongs to GSTR-3B Table 3.1(b) (zero-rated)
    # rather than 3.1(a) (outward taxable supplies).
    # Check amended record first; fall back to source record.
    from app.reconciliation.gstr1_vs_3b import map_gstr1_supply_to_gstr3b_bucket, GSTR3BBucket
    _zero_rated_bucket = GSTR3BBucket.TABLE_3_1_B_ZERO_RATED
    is_zero_rated = (
        map_gstr1_supply_to_gstr3b_bucket(amendment_rec) == _zero_rated_bucket
        or (bool(original_rec) and map_gstr1_supply_to_gstr3b_bucket(original_rec) == _zero_rated_bucket)
    )

    return CanonicalAmendment(
        document_type=doc_type,
        recipient_gstin=recipient_gstin,
        original_invoice_number=orig_inv,
        original_invoice_date=orig_dt,
        amended_invoice_number=amended_inv,
        amended_invoice_date=amended_dt,
        original_taxable=round(orig_tx_paise / 100.0, 2),
        amended_taxable=round(effective_amend_tx / 100.0, 2),
        delta_taxable=round(delta_tx_paise / 100.0, 2),
        original_igst=round(orig_igst_paise / 100.0, 2),
        amended_igst=round(effective_amend_igst / 100.0, 2),
        delta_igst=round(delta_igst_paise / 100.0, 2),
        original_cgst=round(orig_cgst_paise / 100.0, 2),
        amended_cgst=round(effective_amend_cgst / 100.0, 2),
        delta_cgst=round(delta_cgst_paise / 100.0, 2),
        original_sgst=round(orig_sgst_paise / 100.0, 2),
        amended_sgst=round(effective_amend_sgst / 100.0, 2),
        delta_sgst=round(delta_sgst_paise / 100.0, 2),
        original_cess=round(orig_cess_paise / 100.0, 2),
        amended_cess=round(effective_amend_cess / 100.0, 2),
        delta_cess=round(delta_cess_paise / 100.0, 2),
        original_taxable_paise=orig_tx_paise,
        amended_taxable_paise=effective_amend_tx,
        delta_taxable_paise=delta_tx_paise,
        original_igst_paise=orig_igst_paise,
        amended_igst_paise=effective_amend_igst,
        delta_igst_paise=delta_igst_paise,
        original_cgst_paise=orig_cgst_paise,
        amended_cgst_paise=effective_amend_cgst,
        delta_cgst_paise=delta_cgst_paise,
        original_sgst_paise=orig_sgst_paise,
        amended_sgst_paise=effective_amend_sgst,
        delta_sgst_paise=delta_sgst_paise,
        original_cess_paise=orig_cess_paise,
        amended_cess_paise=effective_amend_cess,
        delta_cess_paise=delta_cess_paise,
        amendment_type=amendment_type,
        source_period=source_period,
        filing_period=filing_period,
        original_found=original_rec is not None,
        original_source=original_source,
        chain_id=chain_id,
        chain_position=chain_position,
        is_latest_effective_amendment=is_latest_effective_amendment,
        source_record=dict(original_rec) if original_rec else None,
        amendment_record=dict(amendment_rec),
        is_zero_rated=is_zero_rated,
    )


def process_gstr1_amendments(
    current_amendment_records: Sequence[Mapping[str, Any]],
    sr_records: Sequence[Mapping[str, Any]],
    prior_gstr1_records: Sequence[Mapping[str, Any]] | None = None,
    filing_period: str | None = None,
) -> dict[str, Any]:
    """Process all current-period GSTR-1 amendment records.

    Returns:
    - canonical_amendments: list of CanonicalAmendment
    - accounted_sr_ids: set of int(id(sr_rec)) accounted by valid amendments
    - accounted_sr_records: list of SR records accounted by amendments
    - mismatches: list of MismatchResult (wrong links, duplicate chains, diffs)
    - chains_summary: list of chain metadata dicts
    """
    sr_index = _index_records_for_amendment_lookup(sr_records)
    prior_index = (
        _index_records_for_amendment_lookup(prior_gstr1_records)
        if prior_gstr1_records
        else None
    )

    # Step 1: Resolve each amendment
    resolved_pairs: list[dict[str, Any]] = []
    for idx, amend in enumerate(current_amendment_records):
        orig_rec, orig_source = resolve_amendment_original(
            amend,
            sales_register_records=sr_records,
            prior_period_records=prior_gstr1_records,
            sr_index=sr_index,
            prior_index=prior_index,
        )
        keys = _extract_amendment_original_keys(amend)
        chain_key = f"{keys['gstin']}::{keys['norm_num']}" if keys["gstin"] else keys["norm_num"]
        if not chain_key:
            chain_key = f"__unknown_amend_{idx}"

        resolved_pairs.append({
            "index": idx,
            "amend": amend,
            "orig_rec": orig_rec,
            "orig_source": orig_source,
            "chain_key": chain_key,
            "keys": keys,
        })

    # Step 2: Group by chain_id to handle duplicate amendment chains
    by_chain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in resolved_pairs:
        by_chain[pair["chain_key"]].append(pair)

    canonical_amendments: list[CanonicalAmendment] = []
    accounted_sr_ids: set[int] = set()
    accounted_sr_records: list[dict[str, Any]] = []
    mismatch_results: list[MismatchResult] = []
    chains_summary: list[dict[str, Any]] = []

    for chain_k, items in by_chain.items():
        # Sort items chronologically / by document date then index
        def _sort_k(it: dict[str, Any]) -> tuple[str, str, int]:
            rec = it["amend"]
            dt = str(rec.get("invoice_date") or rec.get("idt") or rec.get("nt_dt") or "")[:10]
            fp = str(rec.get("filing_period") or rec.get("fp") or "")
            return (fp, dt, it["index"])

        items.sort(key=_sort_k)
        has_multiple = len(items) > 1

        for pos_0, it in enumerate(items):
            is_latest = (pos_0 == len(items) - 1)
            pos_1 = pos_0 + 1
            amend = it["amend"]
            orig_rec = it["orig_rec"]
            orig_source = it["orig_source"]

            c_amend = build_canonical_amendment(
                amendment_rec=amend,
                original_rec=orig_rec,
                original_source=orig_source,
                chain_id=chain_k,
                chain_position=pos_1,
                is_latest_effective_amendment=is_latest,
                filing_period=filing_period,
            )
            canonical_amendments.append(c_amend)

            if orig_rec and orig_source == "SALES_REGISTER":
                sr_id = id(orig_rec)
                if sr_id not in accounted_sr_ids:
                    accounted_sr_ids.add(sr_id)
                    accounted_sr_records.append(orig_rec)

        # Emit warning for duplicate amendment chain
        first_it = items[0]
        keys = first_it["keys"]
        orig_doc_name = keys["raw_num"] or keys["norm_num"] or chain_k

        if has_multiple:
            winning_amend = items[-1]["amend"]
            winning_num = str(
                winning_amend.get("invoice_number_raw")
                or winning_amend.get("invoice_number")
                or winning_amend.get("inum")
                or winning_amend.get("nt_num")
                or ""
            ).strip()

            mismatch_results.append(
                MismatchResult(
                    mismatch_type=MismatchType.AMENDMENT_REQUIRED,
                    severity=MismatchSeverity.MEDIUM,
                    decision_what=(
                        f"REVIEW REQUIRED — MULTIPLE AMENDMENTS FOR ORIGINAL {orig_doc_name}: "
                        f"Found {len(items)} amendments in current return referencing the same original document."
                    ),
                    decision_why=(
                        f"GSTR-1 Table 9 contains {len(items)} amendments referencing original document "
                        f"'{orig_doc_name}'. The latest amendment '{winning_num}' is treated as the terminal effective "
                        f"record. Earlier amendments in the chain remain audit history."
                    ),
                    decision_next=(
                        "Verify whether multiple amendments were filed in error and ensure books reflect "
                        f"the terminal amendment '{winning_num}'."
                    ),
                    rule_id="G1M_011_MULTIPLE_AMENDMENTS",
                    details={
                        "chain_id": chain_k,
                        "original_invoice_number": orig_doc_name,
                        "amendments_count": len(items),
                        "latest_amendment_invoice": winning_num,
                        "issue_type": "multiple_amendments_same_original",
                        "requires_review": True,
                    },
                )
            )

        # Check for wrong original link on unresolvable amendments
        for it in items:
            if not it["orig_rec"]:
                amend = it["amend"]
                sec_name = str(amend.get("section") or "B2BA").upper()
                inv_disp = str(
                    amend.get("invoice_number_raw")
                    or amend.get("invoice_number")
                    or amend.get("inum")
                    or amend.get("nt_num")
                    or ""
                ).strip()

                mismatch_results.append(
                    MismatchResult(
                        mismatch_type=MismatchType.AMENDMENT_REQUIRED,
                        severity=MismatchSeverity.HIGH,
                        decision_what=(
                            f"REVIEW REQUIRED — UNMATCHED / INVALID {sec_name} AMENDMENT: "
                            f"GSTR-1 references original document '{orig_doc_name}' which cannot be located in books or prior filings."
                        ),
                        decision_why=(
                            f"GSTR-1 contains a {sec_name} amendment referencing original document '{orig_doc_name}' "
                            f"which could not be linked to any valid record in the Sales Register or prior filed returns. "
                            f"Table 9 amendment records must correspond to a valid prior document."
                        ),
                        decision_next=(
                            f"Verify original document reference '{orig_doc_name}' against books and prior GSTR-1 filings. "
                            f"If an invalid document number was referenced, file an amended correction."
                        ),
                        rule_id="G1M_011_UNMATCHED_AMENDMENT",
                        details={
                            "invoice_number": inv_disp,
                            "original_invoice_number": orig_doc_name,
                            "amendment_table": sec_name,
                            "issue_type": "unmatched_amendment",
                            "requires_review": True,
                            "taxable_value": _safe_int(amend.get("taxable_amount_paise")),
                            "igst": _safe_int(amend.get("igst_paise")),
                            "cgst": _safe_int(amend.get("cgst_paise")),
                            "sgst": _safe_int(amend.get("sgst_paise")),
                        },
                    )
                )

        chains_summary.append({
            "chain_id": chain_k,
            "original_invoice_number": orig_doc_name,
            "count": len(items),
            "is_duplicate_chain": has_multiple,
            "has_resolved_original": items[0]["orig_rec"] is not None,
            "original_source": items[0]["orig_source"],
        })

    return {
        "canonical_amendments": canonical_amendments,
        "accounted_sr_ids": accounted_sr_ids,
        "accounted_sr_records": accounted_sr_records,
        "mismatches": mismatch_results,
        "chains_summary": chains_summary,
    }
