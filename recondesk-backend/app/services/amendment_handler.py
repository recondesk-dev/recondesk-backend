from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from app.services.matcher import normalize_invoice
from app.services.normalizer import normalize_gstin

logger = logging.getLogger(__name__)


@dataclass
class AmendmentResult:
    type: str  # CANCELLED | UPWARD_REVISION | DOWNWARD_REVISION | NO_CHANGE | AMENDMENT_WITHOUT_ORIGINAL
    original_itc_paise: int
    new_itc_paise: int
    itc_change_paise: int  # = new_itc_paise - original_itc_paise
    action_required: str
    description: str
    urgency: str  # LOW | MEDIUM | HIGH | CRITICAL


@dataclass
class EffectiveGstrStats:
    raw_count: int = 0
    amendment_count: int = 0
    chains_count: int = 0
    superseded_count: int = 0
    effective_count: int = 0


@dataclass
class EffectiveGstrResult:
    effective_records: list[dict[str, Any]]
    superseded_records: list[dict[str, Any]]
    amendment_chains: list[dict[str, Any]]
    stats: EffectiveGstrStats


def process_amendment(
    original_record: Optional[dict[str, Any]],
    amended_record: Optional[dict[str, Any]],
) -> AmendmentResult:
    """Compare an original GSTR invoice with its amended counterpart and compute the ITC delta."""
    if original_record is None and amended_record is None:
        raise ValueError("Both original_record and amended_record cannot be None")

    if original_record is None and amended_record is not None:
        new_itc_paise = int(amended_record.get("total_tax_paise") or 0)
        return AmendmentResult(
            type="AMENDMENT_WITHOUT_ORIGINAL",
            original_itc_paise=0,
            new_itc_paise=new_itc_paise,
            itc_change_paise=new_itc_paise,
            action_required="Verify against prior period original invoice",
            description="Amended invoice received without prior original in current filing",
            urgency="MEDIUM",
        )

    original_itc_paise = int((original_record or {}).get("total_tax_paise") or 0)

    if amended_record is None:
        amendment_type = "CANCELLED"
        new_itc_paise = 0
        itc_change_paise = 0 - original_itc_paise
    else:
        new_itc_paise = int(amended_record.get("total_tax_paise") or 0)
        itc_change_paise = new_itc_paise - original_itc_paise
        if itc_change_paise > 0:
            amendment_type = "UPWARD_REVISION"
        elif itc_change_paise < 0:
            amendment_type = "DOWNWARD_REVISION"
        else:
            amendment_type = "NO_CHANGE"

    if amendment_type == "CANCELLED":
        urgency = "CRITICAL"
        action_required = f"Reverse full ITC of Rs{original_itc_paise // 100}"
        description = "Supplier has cancelled this invoice"
    elif amendment_type == "DOWNWARD_REVISION":
        urgency = "HIGH"
        action_required = f"Reverse excess ITC of Rs{abs(itc_change_paise) // 100}"
        description = "Supplier revised invoice downward"
    elif amendment_type == "UPWARD_REVISION":
        urgency = "LOW"
        action_required = f"Claim additional ITC of Rs{itc_change_paise // 100}"
        description = "Supplier revised invoice upward"
    else:
        urgency = "LOW"
        action_required = "No action required"
        description = "No ITC change after amendment"

    return AmendmentResult(
        type=amendment_type,
        original_itc_paise=original_itc_paise,
        new_itc_paise=new_itc_paise,
        itc_change_paise=itc_change_paise,
        action_required=action_required,
        description=description,
        urgency=urgency,
    )


def _is_amendment_record(rec: dict[str, Any]) -> bool:
    if rec.get("is_amendment"):
        return True
    sec = str(rec.get("section") or "").strip().lower()
    return sec in ("b2ba", "cdnra", "b2cla", "b2csa", "expa")


def _normalized_inum(rec: dict[str, Any]) -> str:
    raw = (
        rec.get("invoice_number_normalized")
        or rec.get("invoice_number")
        or rec.get("invoice_number_raw")
        or ""
    )
    return normalize_invoice(str(raw).strip()) if raw else ""


def _normalized_oinum(rec: dict[str, Any]) -> str:
    raw = (
        rec.get("original_invoice_number")
        or rec.get("original_invoice_number_raw")
        or rec.get("oinum")
        or rec.get("ont_num")
        or rec.get("ointnum")
        or ""
    )
    return normalize_invoice(str(raw).strip()) if raw else ""


def _period_sort_key(rec: dict[str, Any]) -> str:
    """Format supprd / period into a comparable YYYYMM string."""
    prd = str(rec.get("supprd") or rec.get("period") or "").strip().replace("-", "").replace("/", "")
    if len(prd) == 6 and prd.isdigit():
        if prd.startswith(("20", "19")):
            return prd  # YYYYMM
        return f"{prd[2:]}{prd[:2]}"  # MMYYYY -> YYYYMM
    return prd


def _date_sort_key(rec: dict[str, Any]) -> str:
    dt = str(rec.get("invoice_date") or rec.get("invoice_date_norm") or rec.get("dt") or "").strip()
    return dt[:10] if len(dt) >= 10 else dt


def build_effective_gstr_records(
    gstr_records: Sequence[dict[str, Any]],
) -> EffectiveGstrResult:
    """Sequences and resolves GSTR-2B amendment relationships into effective records.

    Algorithm:
      1. Partition records by supplier_gstin.
      2. Deduplicate identical duplicate amendment records.
      3. For each supplier, construct a directed lineage graph based on structural
         amendment references (oinum/inum).
      4. Traverse components to identify chains. In an explicit chain
         (Original <- Amend 1 <- Amend 2), structural terminal successorship
         determines the effective record.
      5. When sibling amendments reference the same root original, apply deterministic
         tie-breaking: return period -> document date -> source order.
      6. Separate records into effective_records and superseded_records.
      7. Enrich effective records with amendment metadata and transition metrics.
    """
    raw_count = len(gstr_records)
    if raw_count == 0:
        return EffectiveGstrResult(
            effective_records=[],
            superseded_records=[],
            amendment_chains=[],
            stats=EffectiveGstrStats(),
        )

    # Fast check: If no record in the entire dataset is an amendment, return unchanged
    has_any_amendment = any(_is_amendment_record(r) for r in gstr_records)
    if not has_any_amendment:
        return EffectiveGstrResult(
            effective_records=list(gstr_records),
            superseded_records=[],
            amendment_chains=[],
            stats=EffectiveGstrStats(
                raw_count=raw_count,
                amendment_count=0,
                chains_count=0,
                superseded_count=0,
                effective_count=raw_count,
            ),
        )

    # Group by supplier GSTIN
    by_supplier: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for idx, r in enumerate(gstr_records):
        sup = str(r.get("supplier_gstin") or "").strip()
        by_supplier[sup].append((idx, r))

    effective_indices: set[int] = set()
    superseded_records: list[dict[str, Any]] = []
    amendment_chains_summary: list[dict[str, Any]] = []
    total_amendments_count = 0
    total_chains_count = 0

    for sup_gstin, indexed_records in by_supplier.items():
        # Step A: Deduplicate identical amendment entries within the supplier
        seen_amend_keys: dict[tuple, int] = {}
        active_records: list[tuple[int, dict[str, Any]]] = []

        for idx, rec in indexed_records:
            is_amend = _is_amendment_record(rec)
            if is_amend:
                total_amendments_count += 1
                dedup_key = (
                    _normalized_inum(rec),
                    _normalized_oinum(rec),
                    int(rec.get("total_tax_paise") or 0),
                    _date_sort_key(rec),
                    _period_sort_key(rec),
                    str(rec.get("section") or "").strip().lower(),
                )
                if dedup_key in seen_amend_keys:
                    # Duplicate identical amendment row — supersede immediately
                    dup_rec = dict(rec)
                    dup_rec["superseded_reason"] = "DUPLICATE_AMENDMENT_INPUT"
                    superseded_records.append(dup_rec)
                    continue
                seen_amend_keys[dedup_key] = idx

            active_records.append((idx, rec))

        # Step B: Build connected components (lineage clusters) for this supplier
        # Union-Find over normalized invoice keys
        parent: dict[str, str] = {}

        def find(k: str) -> str:
            if k not in parent:
                parent[k] = k
            if parent[k] != k:
                parent[k] = find(parent[k])
            return parent[k]

        def union(k1: str, k2: str) -> None:
            r1, r2 = find(k1), find(k2)
            if r1 != r2:
                parent[r1] = r2

        for _, rec in active_records:
            curr_key = _normalized_inum(rec)
            if not curr_key:
                continue
            find(curr_key)
            if _is_amendment_record(rec):
                orig_key = _normalized_oinum(rec)
                if orig_key and orig_key != curr_key:
                    find(orig_key)
                    union(curr_key, orig_key)

        # Group records by component root
        components: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        for idx, rec in active_records:
            curr_key = _normalized_inum(rec)
            if curr_key:
                root_k = find(curr_key)
                components[root_k].append((idx, rec))
            else:
                # Fallback for record without invoice number
                components[f"__no_inv_{idx}"].append((idx, rec))

        # Step C: Resolve each component
        for root_key, comp_records in components.items():
            amend_entries = [(i, r) for i, r in comp_records if _is_amendment_record(r)]
            orig_entries = [(i, r) for i, r in comp_records if not _is_amendment_record(r)]

            if not amend_entries:
                # No amendments in this cluster — all original entries are effective
                for i, r in comp_records:
                    effective_indices.add(i)
                continue

            # Amendment chain exists!
            total_chains_count += 1

            # Build directed graph within the amendments to evaluate terminal successors
            # Node: amendment index i. Edge: i -> j if i amends j's inum.
            # target j is amended by i => j is NOT terminal.
            amended_by_another: set[int] = set()
            amend_inum_map: dict[str, list[int]] = defaultdict(list)
            for i, r in amend_entries:
                curr_inv = _normalized_inum(r)
                if curr_inv:
                    amend_inum_map[curr_inv].append(i)

            for i, r in amend_entries:
                target_oinum = _normalized_oinum(r)
                if target_oinum and target_oinum in amend_inum_map:
                    for prior_idx in amend_inum_map[target_oinum]:
                        if prior_idx != i:
                            # prior_idx is amended by i
                            amended_by_another.add(prior_idx)

            # Terminal amendments are those not superseded by any other amendment
            terminal_amends = [(i, r) for i, r in amend_entries if i not in amended_by_another]
            if not terminal_amends:
                terminal_amends = list(amend_entries)

            # If multiple terminal candidates (sibling root-referencing amendments),
            # apply deterministic tie-breaking:
            # 1. Period (YYYYMM) descending
            # 2. Document date descending
            # 3. Input sequence index descending (later in file wins)
            def _tie_break_key(item: tuple[int, dict[str, Any]]) -> tuple[str, str, int]:
                idx_val, r_val = item
                return (_period_sort_key(r_val), _date_sort_key(r_val), idx_val)

            terminal_amends.sort(key=_tie_break_key, reverse=True)
            winning_idx, winning_rec = terminal_amends[0]

            effective_indices.add(winning_idx)

            # All non-amendment original records in the cluster are superseded
            # All other amendments in the cluster are superseded
            all_superseded_in_cluster: list[tuple[int, dict[str, Any]]] = []
            for i, r in comp_records:
                if i != winning_idx:
                    all_superseded_in_cluster.append((i, r))
                    r_sup = dict(r)
                    r_sup["superseded_by_id"] = winning_rec.get("id")
                    r_sup["superseded_by_invoice"] = winning_rec.get("invoice_number")
                    superseded_records.append(r_sup)

            # Identify original record for delta computation
            orig_root = orig_entries[0][1] if orig_entries else None
            amend_res = process_amendment(orig_root, winning_rec)

            # Enrich the winning effective record in-place in gstr_records
            all_inums = {_normalized_inum(r) for _, r in comp_records if _normalized_inum(r)}
            winning_rec["is_effective_amendment"] = True
            winning_rec["amendment_result"] = amend_res
            winning_rec["amendment_type"] = amend_res.type
            winning_rec["itc_change_paise"] = amend_res.itc_change_paise
            winning_rec["original_record_id"] = str(orig_root.get("id") or "") if orig_root else None
            winning_rec["superseded_record_ids"] = [
                str(r.get("id") or "") for _, r in all_superseded_in_cluster if r.get("id")
            ]
            winning_rec["lineage_invoices"] = list(all_inums)

            amendment_chains_summary.append({
                "effective_id": winning_rec.get("id"),
                "effective_invoice": winning_rec.get("invoice_number"),
                "original_invoice": _normalized_oinum(winning_rec) or winning_rec.get("invoice_number"),
                "has_local_original": orig_root is not None,
                "superseded_ids": winning_rec["superseded_record_ids"],
                "classification": amend_res.type,
                "itc_delta_paise": amend_res.itc_change_paise,
            })

    effective_records = [r for idx, r in enumerate(gstr_records) if idx in effective_indices]

    stats = EffectiveGstrStats(
        raw_count=raw_count,
        amendment_count=total_amendments_count,
        chains_count=total_chains_count,
        superseded_count=len(superseded_records),
        effective_count=len(effective_records),
    )

    logger.info(
        "[AMENDMENT] Raw GSTR records: %d | Amendments detected: %d | "
        "Chains: %d | Superseded records removed: %d | Effective GSTR records: %d",
        stats.raw_count,
        stats.amendment_count,
        stats.chains_count,
        stats.superseded_count,
        stats.effective_count,
    )

    return EffectiveGstrResult(
        effective_records=effective_records,
        superseded_records=superseded_records,
        amendment_chains=amendment_chains_summary,
        stats=stats,
    )
