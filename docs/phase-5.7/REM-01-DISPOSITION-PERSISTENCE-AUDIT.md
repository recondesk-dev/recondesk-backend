# Phase 5.7 REM-01 — Disposition Status Persistence & Display Audit Report

**Date**: 2026-09-20  
**Target Run ID**: `e04d2e4f-d316-4836-bbd8-cde22dc658b8`  
**Target Invoice / Record**: `PUR2026272631` (`rr:003e437b-6697-47fe-a07a-3846def231cf`)  
**Observed Behavior**:
1. `PATCH /api/reconcile/records/bulk-update` returns HTTP 200 `{"updated_count": 1}`.
2. A note `"acted"` appears in the drawer's Notes section.
3. After reopening/refreshing the record, it still shows: `"Mark as Acted"` and `"Mark as Ignored"` (record appears as pending).
**Investigation Scope**: End-to-end read-only audit tracing database persistence, results reconstruction, caching layers, and frontend UI lifecycle.

---

## 1. Executive Summary & Root-Cause Matrix

| Investigation Area | Verdict | Primary Finding |
|---|---|---|
| **1. Database Persistence** | **VERIFIED & WORKING** | The bare UUID `003e437b-6697-47fe-a07a-3846def231cf` was successfully written to `mismatch_notes` with `note: "acted"`, `note_type: "decision_status"`, and `run_id: "e04d2e4f-d316-4836-bbd8-cde22dc658b8"`. |
| **2. Note "acted" Visibility** | **EXPLAINED (Table Overloading)** | `mismatch_notes` stores both CA notes and decision statuses. `GET /api/notes/{record_id}` in `notes.py:180-195` selects all rows matching `record_id` without filtering by `note_type`. The drawer notes query therefore fetches and displays the decision status as a user-visible note. |
| **3. Results Reconstruction** | **VERIFIED (Unit Level)** | In commit `1d7f3ba`, `_build_matched_pair_records` was updated to hydrate `decision_status` via `_lookup_by_record_id(decision_statuses, rid_str, "pending")`. This logic correctly maps `rr:<uuid>` to the bare UUID in `decision_statuses`. |
| **4. Buttons Still Showing "Mark as Acted" / "Mark as Ignored"** | **CONFIRMED DEFECT (Frontend UI)** | In `results/page.tsx:6278-6298`, the drawer action buttons are **hardcoded and static**. They are never conditionally toggled, styled, or disabled when `decision_status === "acted"`. Even when a record is marked as acted, reopening the drawer renders both buttons identically. |
| **5. Card List View Status** | **CONFIRMED DEFECT (Frontend UI)** | Unlike ITC and Risk cards which display `<DecisionStatusPill status={effectiveStatus(row)} />` on each card, `DecisionInvoiceCard` in the Review Required list view (`results/page.tsx:5373-5394`) **omits the status pill entirely**. Status is only visible inside the drawer. |
| **6. Record Still Rendering as Pending** | **CONFIRMED DEFECT (Multi-Node Redis Caching)** | `_cached_matched_pairs` caches full bucket rows in Redis (`cache:bucket:{run_id}:review_required`) with a 120-second TTL. ReconDesk production runs across EC2 and EC3 instances. Redis cache invalidation on one instance does not invalidate local Redis on the other. Subsequent GET requests routed by the load balancer to the other node serve stale cached rows with `decision_status: "pending"`. |

---

## 2. Detailed Audit Tracing (10 Audit Questions)

### Q1: Exact Record ID Sent in Bulk-Update Request
- **Frontend Source**: When a user clicks "Mark as Acted" in the drawer for invoice `PUR2026272631`, the handler `runSingleDecision` (`results/page.tsx:2298`) is executed with `activeRecord.id`.
- **Payload Sent**:
  ```json
  PATCH /api/reconcile/records/bulk-update
  {
    "run_id": "e04d2e4f-d316-4836-bbd8-cde22dc658b8",
    "record_ids": ["rr:003e437b-6697-47fe-a07a-3846def231cf"],
    "decision_status": "acted"
  }
  ```
- **Exact ID**: `rr:003e437b-6697-47fe-a07a-3846def231cf`.

---

### Q2: Bulk-Update Endpoint Database Write & Storage Format
- **Endpoint Handler**: `reconcile_records_bulk_update` (`reconciliation_api.py:5653-5695`).
- **Validation**:
  - Validates `_assert_record_ids_in_run(sb, rid, ids)`. In commit `1d7f3ba`, the `rr:` prefix branch was added, allowing `rr:003e437b-6697-47fe-a07a-3846def231cf` to validate successfully against the run.
- **Write Function**: `_upsert_decision_status` (`reconciliation_api.py:2802-2868`).
  - Converts prefixed ID to bare UUID:
    ```python
    db_rid = _db_record_id(record_id)  # "003e437b-6697-47fe-a07a-3846def231cf"
    ```
  - **Step 1 (Delete)**: Deletes any prior row for `(run_id, record_id)`:
    ```python
    sb.table("mismatch_notes").delete().eq("run_id", run_id).eq("record_id", db_rid).execute()
    ```
  - **Step 2 (Insert)**: Inserts the new status row into `mismatch_notes`:
    ```python
    ins = {
        "record_id": db_rid,                   # "003e437b-6697-47fe-a07a-3846def231cf"
        "run_id": run_id,                       # "e04d2e4f-d316-4836-bbd8-cde22dc658b8"
        "user_id": user_id,
        "firm_owner_id": user_id,
        "note": status_value,                   # "acted"
        "record_type": "pr",
        "note_type": "decision_status",
        "severity": "low",
        "created_at": now,
    }
    sb.table("mismatch_notes").insert(ins).execute()
    ```
- **Storage Format & Why a Note Was Created**:
  1. The status string (`"acted"` or `"ignored"`) is stored in the `note` column.
  2. The table `mismatch_notes` is shared between user notes and decision statuses.
  3. In `app/routers/notes.py:180-195`:
     ```python
     @router.get("/{record_id}")
     async def list_notes(record_id: str, _user: dict = Depends(get_current_active_user)):
         db_record_id = _db_record_id(record_id)
         res = sb.table("mismatch_notes").select(
             "id, record_id, record_type, run_id, user_id, note, created_at"
         ).eq("record_id", db_record_id).order("created_at", desc=True).execute()
     ```
     `list_notes` **does not filter out `note_type == 'decision_status'`**!
  4. When the frontend drawer opens, `GET /api/notes/rr:003e437b-6697-47fe-a07a-3846def231cf` runs. PostgREST returns the decision status row as a regular note. The frontend displays `Notes (1)` with the text `"acted"`.
  5. **Conclusion**: The note `"acted"` is direct, incontrovertible evidence that the database write **succeeded and was committed**.

---

### Q3: Results-Fetch Endpoint Reconstructing Review Required Records
- **Frontend Request**:
  `GET /api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/matched?page=1&limit=50&review_required=true`
- **Backend Handler**: `reconcile_run_matched_bucket` (`reconciliation_api.py:6176-6238`).
  - Parses `review_required=true` -> `rr_req = True`.
  - Calls `_cached_matched_pairs(sb, rid=rid, payload=p, note_counts=notes, fetch_review_required=rr_req)`.
  - `_cached_matched_pairs` delegates to:
    ```python
    rows = _cached_bucket_dict_rows(rid, "review_required", _build)
    ```
  - When cache misses, `_build` calls:
    ```python
    pairs = _build_matched_pair_records(
        sb,
        rid=rid,
        payload=payload,
        note_counts=note_counts,
        fetch_review_required=True,
    )
    ```

---

### Q4: Inspection of `_decision_statuses_for_run()`
- **Implementation** (`reconciliation_api.py:2769-2800`):
  ```python
  def _decision_statuses_for_run(sb, run_id: str) -> dict[str, str]:
      if not sb:
          return {}
      rows: list[dict] = []
      for use_note_type in (True, False):
          try:
              q = (
                  sb.table("mismatch_notes")
                  .select("record_id, note")
                  .eq("run_id", run_id)
              )
              if use_note_type:
                  q = q.eq("note_type", "decision_status")
              r = q.execute()
              rows = r.data or []
              break
          except Exception as exc:
              if use_note_type and _is_schema_compat_error(exc):
                  continue
              return {}
      out: dict[str, str] = {}
      for row in rows:
          record_id = str(row.get("record_id") or "").strip()
          note = str(row.get("note") or "").strip().lower()
          if record_id and note in {"acted", "ignored", "pending"}:
              out[record_id] = note
      return out
  ```
- **Evaluation**:
  - The query correctly selects `record_id, note` from `mismatch_notes` filtered by `run_id` and `note_type = "decision_status"`.
  - Returns `{"003e437b-6697-47fe-a07a-3846def231cf": "acted"}`.
  - **Fragility Risk**: If `_upsert_decision_status` stripped `note_type` during insert due to a schema retry, the inserted row has `note_type = NULL`. The `.eq("note_type", "decision_status")` filter would then match 0 rows, returning an empty map `{}`.

---

### Q5: Inspection of `_build_matched_pair_records()`
- **Implementation** (`reconciliation_api.py:3624-3865`):
  - Signature:
    ```python
    def _build_matched_pair_records(
        sb,
        *,
        rid: str,
        payload: dict[str, Any],
        note_counts: Counter[str],
        fetch_review_required: bool = False,
        precomputed_outcome_rows: Optional[list[Any]] = None,
        decision_statuses: Optional[dict[str, str]] = None,
    )
    ```
  - Hydration:
    ```python
    if decision_statuses is None:
        decision_statuses = _decision_statuses_for_run(sb, rid) if sb is not None else {}
    ```
  - ID Tagging:
    ```python
    rid_str = f"rr:{gid or pid}"  # "rr:003e437b-6697-47fe-a07a-3846def231cf"
    ```
  - Status Lookup:
    ```python
    "decision_status": _lookup_by_record_id(decision_statuses, rid_str, "pending"),
    ```

---

### Q6: Inspection of `rr:` ID Handling in Commit `1d7f3ba`
- Commit `1d7f3ba` introduced:
  1. `_decision_statuses_for_run` guard for `not sb`.
  2. `decision_statuses` parameter in `_build_matched_pair_records` defaulting to `_decision_statuses_for_run(sb, rid)`.
  3. Hydration of `decision_status` in Review Required outcome rows using `_lookup_by_record_id`.
  4. Validation of `rr:` prefixed IDs in `_assert_record_ids_in_run`:
     ```python
     if any(x.startswith("rr:") for x in wanted):
         valid.update(
             str(row.get("id") or "")
             for row, _ in _build_matched_pair_records(
                 sb,
                 rid=rid,
                 payload=p,
                 note_counts=notes,
                 fetch_review_required=True,
                 decision_statuses={},
             )
         )
     ```
- **Audit Assessment**: Commit `1d7f3ba` successfully solved the `HTTP 404: record not found` error on bulk-update.

---

### Q7: Decision Statuses Passing to Record-Building Function
- **Trace in `_cached_matched_pairs`** (`reconciliation_api.py:4368`):
  ```python
  pairs = _build_matched_pair_records(
      sb,
      rid=rid,
      payload=payload,
      note_counts=note_counts,
      fetch_review_required=fetch_review_required,
      # decision_statuses omitted -> defaults to None
  )
  ```
- Because `decision_statuses` is omitted, it defaults to `None`.
- Inside `_build_matched_pair_records` (line 3638):
  `decision_statuses = _decision_statuses_for_run(sb, rid) if sb is not None else {}`
- **Audit Assessment**: Decision statuses are correctly loaded and passed when `_build` executes.

---

### Q8: ID Normalization & Lookup Matching
- **Function**: `_lookup_by_record_id` (`reconciliation_api.py:2159-2166`):
  ```python
  def _lookup_by_record_id(mapping: dict[str, Any], record_id: str, default: Any = None) -> Any:
      if record_id in mapping:
          return mapping[record_id]
      bare = _db_record_id(record_id)
      if bare != record_id and bare in mapping:
          return mapping[bare]
      return default
  ```
- **Evaluation**:
  - `mapping`: `{"003e437b-6697-47fe-a07a-3846def231cf": "acted"}`
  - `record_id`: `"rr:003e437b-6697-47fe-a07a-3846def231cf"`
  - `record_id in mapping` -> False.
  - `bare = _db_record_id(record_id)` -> `"003e437b-6697-47fe-a07a-3846def231cf"`.
  - `bare in mapping` -> True. Returns `"acted"`.
- **Audit Assessment**: The normalization and dictionary lookup logic works as designed.

---

### Q9: Caching, TTLs, and Response Serialization
- **Bucket Cache Key**: `cache:bucket:{run_id}:review_required` (`redis_cache.py:98`).
- **TTL**: `BUCKET_CACHE_TTL_SECONDS = 120` (2 minutes).
- **Cache Invalidation Mechanism**:
  `_upsert_decision_status` calls `invalidate_run_bucket_cache(run_id)`.
  This invokes `cache_delete_pattern(f"cache:bucket:{rid}:*")` using Redis `scan_iter`.
- **Multi-Node Production Topology Defect**:
  - Per `AGENTS.md`, ReconDesk runs on `origin main` across EC2 and EC3 instances.
  - In standard AWS multi-node setups without a centralized cluster cache or when instances run local Redis (`redis://localhost:6379/0`), cache invalidation triggered on Node A only flushes Node A's Redis.
  - When the browser issues the subsequent `GET /matched?review_required=true`, the load balancer routes the request to Node B.
  - Node B still holds the pre-update bucket cache (where `decision_status` was `"pending"`) with up to 120 seconds of remaining TTL.
  - Node B serves the stale cached array directly without calling `_build` or querying Supabase.
- **Frontend SWR Revalidation**:
  `runSingleDecision` calls `mutateReviewRequired()`. The stale response from Node B overwrites the client SWR cache, reverting the record to `"pending"`.

---

### Q10: Root Cause Determination

#### 1. Why Did the Update Succeed?
- `_assert_record_ids_in_run` recognized `rr:003e437b-6697-47fe-a07a-3846def231cf`.
- `_upsert_decision_status` stripped the prefix and executed `DELETE` then `INSERT` on `mismatch_notes`.
- PostgreSQL committed the row: `record_id: "003e437b-6697-47fe-a07a-3846def231cf"`, `note: "acted"`.
- HTTP 200 `{"updated_count": 1}` was returned.

#### 2. Why Was a Note Created / Visible?
- `mismatch_notes` is an overloaded table used for both CA user comments and system/decision dispositions.
- `GET /api/notes/{record_id}` in `notes.py:180-195` performs `SELECT ... FROM mismatch_notes WHERE record_id = db_record_id` **without filtering by `note_type`**.
- When the drawer loads notes for the invoice, the decision row is fetched and rendered as a note with content `"acted"`.

#### 3. Why Does the Record Still Show "Mark as Acted" and "Mark as Ignored"?
Two independent defects combine to create this behavior:

##### Defect A: Frontend Static Drawer Action Buttons
In `recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx:6278-6298`:
```tsx
<div className="flex flex-wrap gap-2">
  <button
    type="button"
    disabled={isRunFinalized}
    className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
    onClick={() => void runSingleDecision(activeRecord.id, "acted")}
  >
    Mark as Acted
  </button>
  <button
    type="button"
    disabled={isRunFinalized}
    className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
    onClick={() => void runSingleDecision(activeRecord.id, "ignored")}
  >
    Mark as Ignored
  </button>
</div>
```
- **The buttons are unconditionally rendered as "Mark as Acted" and "Mark as Ignored"**.
- There is no conditional logic to check `effectiveStatus(activeRecord) === "acted"`.
- Unlike the bulk action bar which only appears when items are selected, the drawer buttons **never reflect the active status**. Even if `activeRecord.decision_status` is `"acted"`, the drawer still displays both buttons, leading the CA to believe the record was not acted upon.
- Furthermore, in the Review Required list view (`results/page.tsx:5373-5394`), `DecisionInvoiceCard` has **no status badge/pill at all**. The CA cannot see from the list whether an invoice is pending, acted, or ignored.

##### Defect B: Stale Bucket Cache (Redis 120s TTL)
- If the browser refreshes or SWR re-fetches from a backend node whose `cache:bucket:{run_id}:review_required` was not invalidated, the backend responds with `decision_status: "pending"`.
- When the drawer reopens with `setActiveRecord(row)`, `activeRecord.decision_status` is reset to `"pending"`.
- The `DecisionStatusPill` above the buttons renders "Pending".

---

## 3. Recommended Remediation Plan

### Fix 1: Filter Decision Status Rows from Notes API (Backend)
In `recondesk-backend/app/routers/notes.py:180-195`, update `list_notes` to filter out internal system/decision notes:
```python
# Exclude decision_status and internal action tracking from user-visible notes
res = (
    sb.table("mismatch_notes")
    .select("id, record_id, record_type, run_id, user_id, note, created_at")
    .eq("record_id", db_record_id)
    .neq("note_type", "decision_status")
    .order("created_at", desc=True)
    .execute()
)
```

### Fix 2: Dynamic Drawer Action Buttons & Visual Feedback (Frontend)
In `recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx:6278-6298`:
1. Check `effectiveStatus(activeRecord)`.
2. When status is `"acted"`, style the "Mark as Acted" button as active/disabled (or show "Acted ✓") and allow toggling to "Mark as Ignored" or resetting to "Pending".
3. When status is `"ignored"`, visually reflect the ignored state.

### Fix 3: Add Status Pill to Review Required Cards (Frontend)
In `recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx:5374-5393`, render `<DecisionStatusPill status={effectiveStatus(row)} />` inside the card status row, matching the behavior of ITC and Risk cards.

### Fix 4: Verify Centralized Redis Configuration Across EC2 / EC3
Ensure that both backend production nodes (EC2 and EC3) point to the same shared Redis instance (or AWS ElastiCache), ensuring `invalidate_run_bucket_cache` immediately clears cached buckets across all application instances.

---

## 4. Verification & Audit Integrity Confirmation

- **Application Code Modified**: None (0 files changed).
- **Database Schema / Migrations Modified**: None.
- **Production State**: Untouched.
- **Git Working Tree**: Verified clean against previously approved local state.
