# Phase 5.7 — Production 404 Audit: `GET /api/einvoice-recon/results/{run_id}`

**Date**: 2026-09-21  
**Target Request**: `GET /api/einvoice-recon/results/e04d2e4f-d316-4836-bbd8-cde22dc658b8`  
**Backend Response**:
```json
{
  "detail": "No E-Invoice reconciliation results found for run_id: e04d2e4f-d316-4836-bbd8-cde22dc658b8"
}
```
**Context**: Observed in browser network logs during verification of REM-01 disposition updates on GSTR-2B reconciliation run `e04d2e4f-d316-4836-bbd8-cde22dc658b8`.  
**Scope & Constraints**: Strictly audit-only. No code, configuration, or infrastructure modified.

---

## 1. Executive Summary & Verdict

| Question / Dimension | Finding | Verdict |
|---|---|---|
| **1. Initiating Component** | `ResultsPage` in `recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx:2123-2135` via `useSWR`. | **Frontend SWR Hook** |
| **2. Why Called for this Run** | `results/page.tsx` executes an unconditioned speculative fetch on mount for every run to populate an optional badge counter on the secondary "e-Invoice Check" tab (`tabCounts.einvoice`). | **Unconditioned Speculative Lookup** |
| **3. Nature of Request** | An **unnecessary request (Category b)** stemming from an **architectural data-model mismatch (Category c)**. GSTR-2B `reconciliation_runs` IDs do not exist in the standalone `einvoice_recon_results` table. | **Defect / Unnecessary Request** |
| **4. Impact on GSTR-2B Recon** | **Zero impact**. SWR isolates errors; GSTR-2B summaries, matched, itc, risk, review-required buckets are completely separate. | **No Functional Impact** |
| **5. Impact on Dispositions** | **Zero impact**. `PATCH /api/reconcile/records/bulk-update` completed with HTTP 200 in 3.22s as shown in network logs. | **No Functional Impact** |
| **6. Impact on Table 4 & Finalize**| **Zero impact**. GSTR-3B Table 4 and run finalization endpoints use independent APIs. | **No Functional Impact** |
| **7. Fix Required?** | Non-critical, but **strongly recommended** to eliminate redundant 404 errors, network noise, and SWR retry overhead on page load. | **Recommended Cleanup** |

---

## 2. Exact Initiating Component & Hook

### Initiating Location
- **Component**: `ResultsPage` (`recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx`)
- **Lines**: 2123–2136
- **Hook Code**:
  ```typescript
  // recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx:2123-2136
  const einvoiceResKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/einvoice-recon/results/${runId}`, authToken] as const)
        : null,
    [authReady, runId, authToken]
  );

  const { data: einvoiceResData } = useSWR<{
    summary?: { total_records?: number };
  }>(einvoiceResKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });
  ```

### Call Chain
1. User navigates to `/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/results`.
2. `ResultsPage` mounts. `authReady` is `true` and `runId` is `"e04d2e4f-d316-4836-bbd8-cde22dc658b8"`.
3. `useMemo` builds the tuple `["/api/einvoice-recon/results/e04d2e4f-d316-4836-bbd8-cde22dc658b8", "<jwt>"]`.
4. `useSWR` fires `authJsonFetcher` (`results/page.tsx:731`).
5. `authJsonFetcher` calls `apiFetch("/api/einvoice-recon/results/e04d2e4f-d316-4836-bbd8-cde22dc658b8")`.
6. Next.js proxy route handler (`app/api/einvoice-recon/[...path]/route.ts`) proxies request to `https://api.recondesk.in/api/einvoice-recon/results/e04d2e4f-d316-4836-bbd8-cde22dc658b8`.
7. Caddy reverse-proxies to FastAPI (`web:8000`).
8. FastAPI router `get_einvoice_recon_results` (`recondesk-backend/app/routers/einvoice_recon.py:237-270`) executes.
9. Queries table `einvoice_recon_results` where `run_id == "e04d2e4f-d316-4836-bbd8-cde22dc658b8"`.
10. Finds 0 rows. Falls back to checking if `client_gstin_id == "e04d2e4f-d316-4836-bbd8-cde22dc658b8"`. Finds 0 rows.
11. Raises `HTTPException(status.HTTP_404_NOT_FOUND, "No E-Invoice reconciliation results found for run_id: e04d2e4f-d316-4836-bbd8-cde22dc658b8")`.
12. `apiFetch` in frontend receives 404, throws `ApiError`, which SWR catches in its `error` state. `einvoiceResData` remains `undefined`.

---

## 3. Root Cause Analysis

### Cause A: Architectural Domain Mismatch (GSTR-2B vs E-Invoice Recon)
1. **Two Separate Systems**:
   - **GSTR-2B Reconciliation**: Stored in `reconciliation_runs` table with ID `e04d2e4f-d316-4836-bbd8-cde22dc658b8`. Represents 2B vs Purchase Register invoice matching.
   - **Books-to-E-Invoice Reconciliation**: A separate module stored in `einvoice_recon_results` table (`recondesk-backend/supabase/migrations/20260807120000_einvoice_recon_results.sql:3-16`).
2. **How E-Invoice Recon Runs**:
   - In `recondesk-backend/app/routers/einvoice_recon.py:177`:
     ```python
     run_id = str(uuid.uuid4())
     ```
   - E-Invoice reconciliation generates its **own fresh UUID** when run via `POST /api/einvoice-recon/run`.
   - It is keyed by `client_gstin_id` and `period`, **not** linked as a child foreign key to `reconciliation_runs`.
3. **The Mismatch**:
   - `results/page.tsx` passes `params.run_id` (the GSTR-2B run ID) directly to the E-Invoice endpoint.
   - The backend looks for an E-Invoice run with that ID. Because none exists, it predictably and correctly returns HTTP 404.

### Cause B: Unconditioned Speculative SWR Mount
Notice the contrast between how other modules are fetched in `results/page.tsx`:
- **Rule 37**: Guarded by `rule37Open`:
  ```typescript
  // results/page.tsx:1985
  authReady && runId && rule37Open ? ... : null
  ```
- **Section 17(5)**: Guarded by `section17Open`:
  ```typescript
  // results/page.tsx:2005
  authReady && runId && section17Open ? ... : null
  ```
- **ITC On Hold**: Guarded by `resultsTab === "itc_on_hold"`:
  ```typescript
  // results/page.tsx:2034
  authReady && runId && resultsTab === "itc_on_hold" ? ... : null
  ```
- **Matched**: Guarded by `resultsTab === "matched"`:
  ```typescript
  // results/page.tsx:1917
  authReady && runId && resultsTab === "matched" ? ... : null
  ```
- **Review Required**: Guarded by `resultsTab === "review_required"`:
  ```typescript
  // results/page.tsx:1964
  authReady && runId && resultsTab === "review_required" ? ... : null
  ```
- **E-Invoice (The Exception)**:
  ```typescript
  // results/page.tsx:2124-2128
  authReady && runId ? ... : null
  ```
  It has **no condition**. It executes on initial page load for every single reconciliation run in the application, regardless of active tab or run type.

### Cause C: Consumer Usage of `einvoiceResData`
Tracing where `einvoiceResData` is used across the entire frontend:
```typescript
// results/page.tsx:3185-3187
<ResultsBucketTabs
  active={resultsTab}
  onChange={setResultsTab}
  tabCounts={{
    ...
    ...(einvoiceResData?.summary != null
      ? { einvoice: einvoiceResData.summary.total_records }
      : {}),
  }}
/>
```
- It is used solely to conditionally append an `(N)` count badge to the "e-Invoice Check" tab button (`ResultsUi.tsx:946-948`).
- Inside the actual panel (`EInvoiceCheckPanel.tsx`), `einvoiceResData` is **never passed or consumed**. `EInvoiceCheckPanel` manages its own upload, run, and verification state internally.
- Because `einvoiceResData` is always 404 for GSTR-2B runs, the badge has **never once appeared in production**.

---

## 4. Impact Assessment

| System / Flow | Impact | Explanation |
|---|---|---|
| **GSTR-2B Reconciliation** | **None (0%)** | Reconciliation run status, matched/unmatched calculations, and results reconstruction occur independently. |
| **Disposition Updates (`bulk-update`)** | **None (0%)** | `PATCH /api/reconcile/records/bulk-update` targets FastAPI directly (`https://api.recondesk.in`) and succeeded with HTTP 200 `{"updated_count": 1}`. |
| **KPIs & Summary Cards** | **None (0%)** | All metrics are supplied by `GET /api/reconcile/runs/{id}/summary`. |
| **Table 4 Workpaper** | **None (0%)** | Table 4 uses `gstr3bApi.getTable4Workpaper` (`GET /api/reconcile/runs/{id}/gstr3b/table4`). |
| **Finalization** | **None (0%)** | Finalization uses `POST /api/reconcile/runs/{id}/finalize`. |
| **Browser Network Performance** | **Minor Negligible** | Generates an unnecessary ~1.5s background request and console red 404 error on page load. SWR may attempt exponential retries on error. |

---

## 5. Classification: (a), (b), or (c)?

The request is a combination of **(b) An unnecessary request that should be suppressed** and **(c) A genuine data-model mismatch**:
- **Why (c)**: Querying E-Invoice reconciliation by a GSTR-2B `run_id` is semantically invalid; the two reconciliation concepts do not share a primary key.
- **Why (b)**: Even if an E-Invoice check exists for the same client and period, querying it unconditionally on GSTR-2B results mount wastes network bandwidth and pollutes error logs.

---

## 6. Recommended Smallest Safe Remediation (For Future Implementation)

### Option 1 (Recommended — Suppress Until Tab Active):
In `recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx:2123-2128`:
Add `resultsTab === "einvoice"` to the SWR key guard:

```typescript
const einvoiceResKey = useMemo(
  () =>
    authReady && runId && resultsTab === "einvoice"
      ? ([`/api/einvoice-recon/results/${runId}`, authToken] as const)
      : null,
  [authReady, runId, resultsTab, authToken]
);
```
- **Effect**:
  - Eliminates the 404 on normal results page loads (when viewing Matched, ITC, Risk, Review Required).
  - Keeps page load completely clean.

### Option 2 (Alternative — Remove Dead Speculative Hook):
Since `EInvoiceCheckPanel` manages its own upload-driven workflow and the speculative count has never worked for GSTR-2B runs:
Remove `einvoiceResKey`, `useSWR(einvoiceResKey, ...)`, and the `...(einvoiceResData?.summary ...)` spread from `results/page.tsx`.
- **Effect**: Completely removes the dead request with zero loss of functionality.

---

## 7. Working Tree Verification

In compliance with constraints, **no code, schema, migration, or infrastructure changes were made during this audit**:
```
On branch main
Changes not staged for commit:
	modified:   recondesk-frontend/lib/api.ts (from previous REM-01 fix)

Untracked files:
	docs/phase-5.7/EINVOICE-404-AUDIT.md
	docs/phase-5.7/REM-01-PROXY-TIMEOUT-AUDIT.md
	recondesk-frontend/lib/apiRouting.test.ts
	test_data/
```
No commits, pushes, or deployments were executed.
