# Phase 5.7 REM-01 — Disposition Record-ID Mismatch Audit Report

**Date**: 2026-09-20  
**Target Run ID**: `e04d2e4f-d316-4836-bbd8-cde22dc658b8`  
**Reported Error**:
```json
{
  "detail": "record not found in this run: rr:003e437b-6697-47fe-a07a-3846def231cf"
}
```
**Trigger Action**: Clicking **"Mark as Acted"** (or **"Mark as Ignored"**) on a Review Required record drawer/card.  
**Trigger Endpoint**: `PATCH /api/reconcile/records/bulk-update`  
**Investigation Scope**: Read-only audit of frontend event handlers, API contracts, backend validation logic, and database persistence layers.

---

## 1. Executive Summary & Exact Root Cause

### 1.1 The Primary Root Cause (The Immediate Blocker)
The error `record not found in this run: rr:003e437b-6697-47fe-a07a-3846def231cf` is caused by a **missing prefix handler in the backend validation function `_assert_record_ids_in_run`** in `recondesk-backend/app/routers/reconciliation_api.py`.

Specifically:
1. When a CA views the **Review Required** tab, the frontend requests `GET /api/reconcile/runs/{run_id}/matched?review_required=true`.
2. The backend generates API row identifiers tagged with the prefix `rr:`:
   ```python
   # reconciliation_api.py:3708
   rid_str = f"rr:{gid or pid}"
   ```
   For the record in question, `rid_str` was `"rr:003e437b-6697-47fe-a07a-3846def231cf"`.
3. When the CA opens the record drawer and clicks **"Mark as Acted"**, the frontend sends:
   ```json
   PATCH /api/reconcile/records/bulk-update
   {
     "run_id": "e04d2e4f-d316-4836-bbd8-cde22dc658b8",
     "record_ids": ["rr:003e437b-6697-47fe-a07a-3846def231cf"],
     "decision_status": "acted"
   }
   ```
4. The backend handler `reconcile_records_bulk_update` (`reconciliation_api.py:5668`) passes `record_ids` to `_assert_record_ids_in_run(sb, rid, ids)`.
5. In `_assert_record_ids_in_run` (`reconciliation_api.py:4077-4137`):
   ```python
   valid: set[str] = set()
   if any(x.startswith("mi:") for x in wanted): ...
   if any(x.startswith("wr:") for x in wanted): ...
   if any(x.startswith("pm:") for x in wanted): ...
   if any(x.startswith("r37:") for x in wanted): ...
   if any(x.startswith("s175:") or x.startswith("s175-db:") for x in wanted): ...

   missing = sorted(x for x in wanted if x not in valid)
   if missing:
       raise HTTPException(
           status_code=status.HTTP_404_NOT_FOUND,
           detail=f"record not found in this run: {missing[0]}",
       )
   ```
6. **Notice that `_assert_record_ids_in_run` contains no check for `x.startswith("rr:")`!**
   Because there is no branch for `rr:`, `valid` remains empty for this ID.
7. Consequently, `missing` evaluates to `["rr:003e437b-6697-47fe-a07a-3846def231cf"]`, and the backend raises `HTTP 404: record not found in this run: rr:003e437b-6697-47fe-a07a-3846def231cf`.

---

### 1.2 The Secondary Root Cause (Immediate Follow-up Defect)
In addition to the 404 validation failure, static analysis revealed a secondary defect in `_build_matched_pair_records`:
- In `_build_missed_itc_records` (line 3271) and `_build_wrongful_risk_records` (line 3362), `_decision_statuses_for_run(sb, rid)` is loaded and used to populate `api_row["decision_status"]`.
- In `_build_matched_pair_records` (line 3850), `"decision_status": "pending"` is **hardcoded to `"pending"`**.
- Therefore, even if `_assert_record_ids_in_run` were bypassed and the decision status were successfully inserted into `mismatch_notes`, when the frontend's SWR revalidates by calling `GET /matched?review_required=true`, the backend would **still return `"decision_status": "pending"`**, causing the UI status to immediately revert back to "pending".

---

## 2. Expected vs. Actual ID

| Property | Value / Analysis |
|---|---|
| **Actual ID Sent by Frontend** | `rr:003e437b-6697-47fe-a07a-3846def231cf` |
| **Origin of Actual ID** | Emitted by backend `_build_matched_pair_records` (`reconciliation_api.py:3708, 3824`) when `fetch_review_required=True`. |
| **Expected ID in `_assert_record_ids_in_run`** | The function only checked prefixes: `mi:`, `wr:`, `pm:`, `r37:`, `s175:`, `s175-db:`. It failed to include `rr:`. |
| **Prefix Definition in System** | `_RECORD_ID_PREFIXES` in `reconciliation_api.py:2097-2105` explicitly lists `"rr:"` as an official API record-type prefix. |
| **DB Storage Format** | In `_upsert_decision_status` (`reconciliation_api.py:2813`), `_db_record_id(record_id)` strips the prefix, storing the bare UUID `003e437b-6697-47fe-a07a-3846def231cf` in `mismatch_notes.record_id`. |
| **Identifier Classification** | `rr:<UUID>` is a **reconciliation outcome record identifier** for a Review Required record. It is **NOT** a work-item ID (`itc_work_items.id`) and **NOT** an exception disposition ID (`reconciliation_exception_dispositions.id`). |
| **Underlying Entity** | `003e437b-6697-47fe-a07a-3846def231cf` is the UUID of an invoice document in run `e04d2e4f-d316-4836-bbd8-cde22dc658b8` (originating from GSTR-2B `gstr_id` or PR `id` within `payload["engine"]["duplicates"]` or `payload["engine"]["review_required_typo"]`). |
| **Run Membership Verification** | The record **genuinely belongs** to run `e04d2e4f-d316-4836-bbd8-cde22dc658b8`. It was loaded by the frontend from that exact run's matched endpoint. The backend only claimed "not found" because it did not query review-required records when assembling the `valid` set. |

---

## 3. End-to-End Execution Trace

### 3.1 Trace: Backend Response → Frontend Card → Decision Drawer
```
1. Frontend SWR Hook (results/page.tsx:1962-1977)
   GET /api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/matched?review_required=true...
       │
2. Backend Endpoint (reconciliation_api.py:6158)
   reconcile_run_matched_bucket()
       │
3. Cache/Builder Layer (reconciliation_api.py:4349, 3641)
   _cached_matched_pairs(fetch_review_required=True)
   -> _build_matched_pair_records(fetch_review_required=True)
       │
4. API ID Generation (reconciliation_api.py:3708, 3824)
   rid_str = f"rr:{gid or pid}"  --> "rr:003e437b-6697-47fe-a07a-3846def231cf"
   api_row = {"id": rid_str, ...}
       │
5. Frontend Card Rendering (results/page.tsx:5357-5372)
   <DecisionInvoiceCard
       key={row.id}
       onOpen={() => setActiveRecord(row)}
   />
   --> Sets activeRecord.id = "rr:003e437b-6697-47fe-a07a-3846def231cf"
       │
6. User Click in Drawer (results/page.tsx:6283)
   <button onClick={() => void runSingleDecision(activeRecord.id, "acted")}>
       Mark as Acted
   </button>
       │
7. Handler Dispatch (results/page.tsx:2308-2319)
   PATCH /api/reconcile/records/bulk-update
   Body: {"run_id": "...", "record_ids": ["rr:003e437b-6697-47fe-a07a-3846def231cf"], "decision_status": "acted"}
       │
8. Backend Dispatch (reconciliation_api.py:5639, 5668)
   reconcile_records_bulk_update()
   -> _assert_record_ids_in_run(sb, rid, ids)
       │
9. FAILURE (reconciliation_api.py:4088-4136)
   - Checks mi:, wr:, pm:, r37:, s175:
   - "rr:" branch is MISSING
   - valid = set()
   - missing = ["rr:003e437b-6697-47fe-a07a-3846def231cf"]
   - Raises HTTP 404: "record not found in this run: rr:003e437b-6697-47fe-a07a-3846def231cf"
```

---

## 4. Affected Flows (Individual vs. Bulk)

| Workflow | Handler | Endpoint Called | Affected? | Error Details |
|---|---|---|---|---|
| **Individual "Mark as Acted"** (Drawer) | `runSingleDecision` (`page.tsx:2297`) | `PATCH /api/reconcile/records/bulk-update` | **YES** | 404 "record not found in this run: rr:..." |
| **Individual "Mark as Ignored"** (Drawer) | `runSingleDecision` (`page.tsx:2297`) | `PATCH /api/reconcile/records/bulk-update` | **YES** | 404 "record not found in this run: rr:..." |
| **Bulk "Mark as Acted"** (Toolbar) | `runBulkDecision` (`page.tsx:2166`) | `PATCH /api/reconcile/records/bulk-update` | **YES** (if applied to `rr:` rows) | 404 "record not found in this run: rr:..." |
| **Bulk "Mark as Ignored"** (Toolbar) | `runBulkDecision` (`page.tsx:2166`) | `PATCH /api/reconcile/records/bulk-update` | **YES** (if applied to `rr:` rows) | 404 "record not found in this run: rr:..." |
| **Missed ITC Dispositions** (`mi:`) | `runSingleDecision` / `runBulkDecision` | `PATCH /api/reconcile/records/bulk-update` | NO | Validated by `_build_missed_itc_records` |
| **Wrongful Risk Dispositions** (`wr:`) | `runSingleDecision` / `runBulkDecision` | `PATCH /api/reconcile/records/bulk-update` | NO | Validated by `_build_wrongful_risk_records` |
| **Matched Dispositions** (`pm:`) | `runSingleDecision` | `PATCH /api/reconcile/records/bulk-update` | NO (Validation passes, but display status reverts due to Bug 1.2) | Validation succeeds via `_build_matched_pair_records` |

Both individual and bulk updates for Review Required records funnel through `PATCH /api/reconcile/records/bulk-update`, making this defect 100% reproducible on all Review Required disposition attempts.

---

## 5. Exact Files and Functions Involved

### 5.1 Backend (`recondesk-backend`)

1. **`app/routers/reconciliation_api.py`**:
   - `_RECORD_ID_PREFIXES` (lines 2097–2105): Correctly lists `"rr:"`.
   - `_db_record_id` (lines 2119–2125): Correctly strips `"rr:"`.
   - `_lookup_by_record_id` (lines 2159–2166): Correctly resolves both tagged and bare IDs.
   - `_upsert_decision_status` (lines 2800–2855): Correctly uses `_db_record_id` to store bare UUID in `mismatch_notes.record_id`.
   - **`_build_matched_pair_records`** (lines 3622–3880):
     - Line 3708: tags review required rows with `f"rr:{gid or pid}"`.
     - Line 3850: **BUG**: hardcodes `"decision_status": "pending"`.
   - **`_assert_record_ids_in_run`** (lines 4077–4137):
     - **BUG**: omits check for `any(x.startswith("rr:") for x in wanted)` and does not query review-required records into `valid`.
   - `reconcile_records_bulk_update` (lines 5635–5678): calls `_assert_record_ids_in_run(sb, rid, ids)`.

### 5.2 Frontend (`recondesk-frontend`)

1. **`app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx`**:
   - `reviewRequiredKey` (lines 1962–1968): constructs SWR cache key requesting review required records.
   - `DecisionInvoiceCard` (line 5357): renders each item with `key={row.id}` and `onOpen={() => setActiveRecord(row)}`.
   - Decision buttons (lines 6283 & 6293): trigger `runSingleDecision(activeRecord.id, "acted")` and `runSingleDecision(activeRecord.id, "ignored")`.
   - `runSingleDecision` (lines 2297–2355): sends `record_ids: [recordId]` to `PATCH /api/reconcile/records/bulk-update`.
   - `runBulkDecision` (lines 2166–2278): sends `record_ids: ids` to `PATCH /api/reconcile/records/bulk-update`.

---

## 6. Smallest Safe Fix

The fix requires changes in **only one backend file**: `recondesk-backend/app/routers/reconciliation_api.py`.  
Zero frontend changes, zero database schema changes, and zero migrations are needed.

### 6.1 Fix Part A: Add `rr:` Support to `_assert_record_ids_in_run`
In `reconciliation_api.py` around line 4120, add the branch for `rr:`:

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
            )
        )
```

*(Optional defensive enhancement: if `wanted` contains bare UUIDs without prefixes, check `_db_record_id(x)` against the set of bare IDs in the run).*

### 6.2 Fix Part B: Hydrate `decision_status` in `_build_matched_pair_records`
In `reconciliation_api.py`:
1. In `_build_matched_pair_records` (around line 3634), load run decision statuses:
   ```python
   decision_statuses = _decision_statuses_for_run(sb, rid)
   ```
2. Around line 3850, replace the hardcoded `"pending"` with:
   ```python
   "decision_status": _lookup_by_record_id(decision_statuses, rid_str, "pending"),
   ```

### 6.3 Code Diff Preview
```diff
--- a/recondesk-backend/app/routers/reconciliation_api.py
+++ b/recondesk-backend/app/routers/reconciliation_api.py
@@ -3632,6 +3632,7 @@ def _build_matched_pair_records(
     gstr_db = ro.load_gstr_map(sb, rid)
     pr_db = ro.load_pr_map(sb, rid)
+    decision_statuses = _decision_statuses_for_run(sb, rid)
 
     all_outcome_rows = (
         precomputed_outcome_rows
@@ -3847,7 +3848,7 @@ def _build_matched_pair_records(
                 "decision_next": d_next
                 if d_next
                 else (str(getattr(orow, "decision_next", "")) if orow else None),
-                "decision_status": "pending",
+                "decision_status": _lookup_by_record_id(decision_statuses, rid_str, "pending"),
                 "decision_type": None,
                 "notes_count": int(_lookup_by_record_id(note_counts, rid_str, 0)),
                 "gstr2b_data": gd2,
@@ -4117,6 +4118,17 @@ def _assert_record_ids_in_run(sb, rid: str, record_ids: list[str]) -> None:
                 note_counts=notes,
             )
         )
+    if any(x.startswith("rr:") for x in wanted):
+        valid.update(
+            str(row.get("id") or "")
+            for row, _ in _build_matched_pair_records(
+                sb,
+                rid=rid,
+                payload=p,
+                note_counts=notes,
+                fetch_review_required=True,
+            )
+        )
     if any(x.startswith("r37:") for x in wanted):
         valid.update(
             str(row.get("id") or "")
```

---

## 7. Data Migration Assessment

- **Is a data migration required?**
  **NO.**
- **Reasoning**:
  1. The table `mismatch_notes` already contains all necessary columns: `id`, `run_id`, `record_id` (UUID), `note` (TEXT), `note_type` (TEXT), `severity`, `user_id`, `created_at`.
  2. `_upsert_decision_status` strips `"rr:"` before inserting via `_db_record_id`, so any record written will have a valid UUID in `mismatch_notes.record_id`.
  3. Because the previous validation failed with a 404, no malformed, orphaned, or partial rows were created in production.
  4. No schema changes or table migrations are required.

---

## 8. Recommended Regression Tests

Add the following unit and integration tests in `recondesk-backend/tests/`:

1. **`test_assert_record_ids_in_run_review_required`**:
   - Create a mock reconciliation payload with an engine `review_required_typo` / `duplicates` entry.
   - Verify that `_assert_record_ids_in_run(sb, rid, ["rr:<valid_uuid>"])` succeeds without raising `HTTPException`.
2. **`test_assert_record_ids_in_run_rejects_unrelated_rr`**:
   - Verify that `_assert_record_ids_in_run(sb, rid, ["rr:<random_unrelated_uuid>"])` raises `HTTPException(404)`.
3. **`test_bulk_update_review_required_endpoint`**:
   - Call `PATCH /api/reconcile/records/bulk-update` with `record_ids: ["rr:<valid_uuid>"]`, `decision_status: "acted"`.
   - Assert HTTP 200 and `updated_count: 1`.
   - Assert `mismatch_notes` contains a row with `record_id = "<valid_uuid>"` and `note = "acted"`.
4. **`test_matched_review_required_returns_persisted_decision_status`**:
   - After updating status to `"acted"`, call `GET /api/reconcile/runs/{run_id}/matched?review_required=true`.
   - Verify that the target row has `"decision_status": "acted"` (not `"pending"`).
5. **`test_bulk_update_mixed_id_prefixes`**:
   - Call `PATCH /api/reconcile/records/bulk-update` with a batch containing `mi:<uuid>`, `wr:<uuid>`, and `rr:<uuid>`.
   - Verify all are validated and updated in a single transaction/batch.

---

## 9. Production Safety Confirmation

- This investigation was conducted in **strict audit-only mode**.
- **Zero** production or staging databases were accessed or modified.
- **Zero** application code, configuration files, schemas, or migrations were altered.
- **Zero** git commits or pushes were executed.
- The diagnosis is fully static and evidence-based, referencing verified repository source code lines.
