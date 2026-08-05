# ReconDesk UX Audit — CA Reconciliation Journey

**Basis:** Traced directly from `.tsx` source files. No intended behavior — only what the code actually renders.  
**Scope:** First login → account setup → new reconciliation wizard → results → IMS actions → finalize → export → history.  
**Source files read:** `login/page.tsx`, `onboarding/page.tsx`, `clients/ClientsPageContent.tsx`, `clients/[id]/page.tsx`, `reconcile/[client_id]/new/page.tsx` (2 176 lines), `runs/[run_id]/results/page.tsx` (5 751 lines), `ImsActionPanel.tsx`, `AdvancedExportPanel.tsx`, `AuditObservationsPanel.tsx`, `DecisionInvoiceCard.tsx`.

---

## Screen 1 — Login
**Route:** `/login`  
**Source:** `app/(auth)/login/page.tsx`

### Purpose
The CA authenticates before accessing any data.

### Interactive elements
| Label | Type | Action |
|---|---|---|
| Email | `<input type="email">` | Sets email field |
| Password | `<input type="password">` | Sets password field |
| **Sign in** | `<button>` | `supabase.auth.signInWithPassword({ email, password })` → on success `router.push('/dashboard')`; on error: inline error string below form |
| **Continue with Google** | `<button>` | `supabase.auth.signInWithOAuth({ provider: 'google' })` → redirect to Google OAuth |
| **Forgot password?** | `<Link>` | Navigate to `/forgot-password` |
| **Create an account** | `<Link>` | Navigate to `/register` |

### Loading / wait states
- No spinner on the **Sign in** button during the network round-trip — form appears frozen.
- On error: an inline `<p>` error message appears below the form.

### Click path: arrived → authenticated
1. Type email (1 interaction)
2. Type password (1 interaction)
3. Click **Sign in** → Supabase call → redirect

**Minimum clicks to exit: 1** (Google SSO) or **3 interactions** (email/pass/submit).

### Friction points
- No spinner on Sign in → CA cannot tell if the form is processing or broken.
- No "remember me" option visible in the code.

---

## Screen 2 — Onboarding Wizard (first-time users only)
**Route:** `/onboarding`  
**Source:** `app/onboarding/page.tsx`

### Purpose
New users complete firm/practice setup before reconciliation is accessible.

### Steps (`uiStep` state machine, 1–5)
| Step | Heading | Elements |
|---|---|---|
| 1 | Full name | `<input>`, **Continue** `<button>` |
| 2 | Firm / practice name | `<input>`, **Continue** |
| 3 | Phone number | `<input type="tel">`, **Continue** |
| 4 | GSTIN | `<input>` labeled "optional", **Continue** |
| 5 | Confirm | Summary of entered values, **Finish setup** `<button>` |

**Finish setup** → `POST /api/profile/onboard`. On success: `router.push('/dashboard')`. On error: inline error `<div>`.

### Loading / wait states
- Steps 1–4: local state only, no API calls.
- Step 5: **Finish setup** button shows spinner icon while POST is in-flight.

### Click path: new user → done with onboarding
Steps 1–4: 4 field fills + 4 **Continue** clicks = 8 interactions. Step 5: 1 click.  
**Total: 9 interactions.**

### Friction points
- No reminder to add GSTIN later if skipped — this will block GSTN auto-fetch in Step 2 of the wizard.
- No progress bar ("Step 3 of 5") — only unlabeled dot/step indicators.

---

## Screen 3 — Dashboard / Client List
**Route:** `/dashboard`  
**Source:** `app/(dashboard)/clients/ClientsPageContent.tsx`

### Purpose
The CA sees all clients and picks one to manage or reconcile.

### Interactive elements
| Label | Type | Action |
|---|---|---|
| **+ Add Client** | `<button>` | Opens Add Client modal |
| Client card / row | Clickable element | `router.push('/clients/[id]')` |
| Search `<input>` | Text filter | Client-side search, no API call |
| **Edit** (per client) | `<button>` | Opens Edit Client modal pre-filled |
| **Delete** (admin only, per client) | `<button>` | Confirmation modal → `DELETE /api/clients/[id]` |

### Add Client modal fields
- Client Name `<input>` (required)
- GSTIN `<input>` (required, validated format)
- Trade Name `<input>` (optional)
- PAN `<input>` (optional)
- **Save** → `POST /api/clients` → closes modal, refreshes list via SWR mutate
- **Cancel** → closes modal

### Loading / wait states
- Client list: `useSWR` on mount. Skeleton (animated pulse `<div>`s) while loading.
- Modal **Save**: button disabled while POST in-flight.

### Click path: Dashboard → ready to reconcile
**Existing client:** 1 click (click client card).  
**New client:** click **+ Add Client** (1) + fill 2–4 fields + click **Save** (1) + click client card (1) = **4–6 interactions**.

---

## Screen 4 — Client Detail
**Route:** `/clients/[id]`  
**Source:** `app/(dashboard)/clients/[id]/page.tsx`

### Purpose
View a client's profile, connected data sources, and reconciliation history. Entry point for starting a new run.

### Interactive elements
| Label | Type | Action |
|---|---|---|
| **New Reconciliation** | `<button>` | `router.push('/reconcile/[client_id]/new')` |
| **Connect GSTN** | `<button>` (if not connected) | Opens GSTN credential modal |
| **Edit Client** | `<button>` | Opens edit modal |
| Past run rows | Clickable `<tr>` | Navigate to `/reconcile/runs/[run_id]/results` |
| **Download** (per run) | `<button>` | Downloads run export |
| **Delete Run** (admin, per run) | `<button>` | Confirmation modal → `DELETE /api/reconcile/runs/[run_id]` |
| **View Vendors** | `<Link>` | Navigate to `/reconcile/runs/[run_id]/vendors` |

### GSTN credential modal
- GSTN Username `<input>`, GSTN Password `<input type="password">`
- **Connect** → `POST /api/clients/[id]/gstn` → shows "Connected" badge on success

### Friction points
- GSTN connection state is not prominently highlighted on load — CAs may enter the wizard and discover a broken connection only at Step 2.
- No column on the run history table indicating finalized vs. draft status.

---

## Screen 5 — Wizard Step 1: Select Period
**Route:** `/reconcile/[client_id]/new` (`uiStep === 1`)  
**Source:** `page.tsx` lines 1328–1360

### Purpose
The CA picks the GST period (month) they want to reconcile.

### Renders on arrival
- `<StepIndicator step={1} />` — 4-step progress indicator at top of the card.
- **If an incomplete prior run exists:** amber banner —  
  _"You have an incomplete reconciliation for [period]. Resume it?"_
  - **Resume** → `importWizardApi.resumeRun()` → restores saved state and advances `uiStep`
  - **Start fresh** → `importWizardApi.cancel()` on old run → creates a new run

### Interactive elements
| Label | Type | Action |
|---|---|---|
| Month `<select>` | Dropdown — last 13 months from today | Sets `period` state |
| **Continue** | `<button>` | Disabled until period selected. On click: `importWizardApi.createRun(token, { client_gstin_id, period })` → stores `runId` → `setUiStep(2)` |

### "Completed run already exists" notice
If a completed reconciliation exists for the chosen period, passive text: _"A completed reconciliation already exists for this period. Starting a new one will be a separate run."_ — not blocking.

### Loading / wait states
- `<select>` is computed locally — no API call.
- **Continue** triggers `createRun()` — **no spinner, no button-disable guard observed** → double-click risk.

### Click path: arrived → Step 1 done
1. Open `<select>` and pick a month (2 interactions)
2. Click **Continue** (1 click)

**Total: 3 interactions.**

### Friction points
- No visual feedback during `createRun()` — the button does not disable or show a loading state; a double-click could create two wizard runs.

---

## Screen 6 — Wizard Step 2: GSTR-2B
**Route:** `/reconcile/[client_id]/new` (`uiStep === 2`)  
**Source:** `page.tsx` lines 1362–1680

### Purpose
The CA provides GSTR-2B data via auto-fetch (if GSTN is connected) or manual file upload.

---

### Branch A — GSTN connected, file not yet uploaded
Heading rendered: **"GSTR-2B"**

| Label | Type | Action |
|---|---|---|
| **Fetch GSTR-2B for [Month Year]** | `<button>` | `gstnApi.fetchGstr2b(token, clientId, ym)` → parses result → creates `File` object (filename: `gstr2b_YYYY_MM_autofetch.json`) → calls `uploadGstrFile()` (signed URL → PUT to R2) → background `gstnApi.fetchIms()` (non-blocking) |
| **Upload manually instead** | Text link-button | `setShowManualGstrUpload(true)` → shows Branch B UI |
| **Back** | Text button (top-right) | `setUiStep(1)` |

**Success state (green box):**  
_"Fetched N invoices from GSTR-2B · IMS: M mapped (P pending action)"_

**Zero-data state (amber box):**  
_"No GSTR-2B data found for this period…"_  
- **Try a different period** → `setUiStep(1)`  
- **Continue anyway** → `setUiStep(3)`

**Error state (red box):**  
_"Couldn't fetch GSTR-2B automatically. [detail]"_  
- **Reconnect GSTN** → `<Link href="/clients/[id]">` ← exits the wizard  
- **Upload manually instead** → `setShowManualGstrUpload(true)`

---

### Branch B — Manual upload (no GSTN or user chose "Upload manually instead")
Heading rendered: **"Upload GSTR-2B"**

| Label | Type | Action |
|---|---|---|
| File `<input type="file">` | Accepts `.json, .xlsx, .xls` | `setGstrFile(file)`. Shows _"Selected: [filename] ([size])"_ |
| **Upload & verify** | `<button>` | Disabled until file selected. `importWizardApi.signedUrl()` → PUT to R2 with `gstrProgress` bar → `importWizardApi.gstrUploadComplete()` → backend runs sanity checks |
| **Retry upload** | `<button>` (on failure) | Re-calls `onGstrUpload()` |
| **Back to auto-fetch** | Text link-button | `setShowManualGstrUpload(false)` (only visible if GSTN is connected) |

---

### Sanity check results (shown after upload completes)

Rendered as a `<ul>`. Per-check `<li>` items:

| Status | Visual | Action rendered |
|---|---|---|
| `pass` | ✓ green checkmark | None |
| `warning` | ⚠ amber | **Dismiss** or **I understand — continue** |
| `error` | ✕ red | None (blocks progress) |

**Blocking acknowledgment warnings** (e.g., `multi_sheet_combine`, `missing_invoice_number`): the **I understand — continue** button must be clicked before **Continue to purchase register** is enabled. Regular warnings show **Dismiss**.

`affected_records` (up to 20 rows of GSTIN + invoice number) are listed inline under the check item.

**Re-upload GSTR-2B** link appears when there are sanity errors.

### Gating condition for **Continue to purchase register**
```
canGoToStep3 = sanityErrors.length === 0 && highRiskWarningsOk && !!checksDisplayed.length
```
The button renders `disabled:bg-gray-400 disabled:cursor-not-allowed` when false.

### Loading / wait states
- Auto-fetch: button text changes to _"Fetching GSTR-2B…"_ while `gstnFetchBusy`.
- Manual upload: horizontal progress bar (`gstrProgress` 0–100%).
- Sanity checks: _"Running sanity checks…"_ while `sanityBusy`.
- **Gap:** after upload completes but before sanity results appear — ~2–5s of no feedback.

### Click path (Branch A — GSTN connected, no warnings): Step 2 done
1. Click **Fetch GSTR-2B for [Month Year]** (1 click)
2. Wait for fetch + upload + IMS prefetch (~15–40s)
3. Click **Continue to purchase register** (1 click)

**Total: 2 clicks + wait.**

### Click path (Branch B — manual, 1 blocking warning): Step 2 done
1. Click file picker + choose file (2 interactions)
2. Click **Upload & verify** (1 click)
3. Wait for upload + sanity
4. Click **I understand — continue** on blocking warning (1 click)
5. Click **Continue to purchase register** (1 click)

**Total: 5 interactions + wait.**

### Friction points
- **No feedback gap** (~2–5s) between upload success and sanity check display.
- **Reconnect GSTN error path exits the wizard.** The CA must navigate back manually; no return link is provided in the error box.
- **"Continue anyway" (zero data)** — the CA proceeds without any warning that the final run will match 0 invoices.

---

## Screen 7 — Wizard Step 3: Upload Purchase Register
**Route:** `/reconcile/[client_id]/new` (`uiStep === 3`)  
**Source:** `page.tsx` lines 1682–2103

### Purpose
The CA uploads their internal purchase register (Tally/ERP export) and confirms column mapping.

### Always-visible elements
| Label | Type | Action |
|---|---|---|
| **ITC claimed period** `<select>` | Optional. Month dropdown | On change: immediately calls `importWizardApi.patchRun(token, runId, { itc_claimed_period })` (non-blocking, best-effort). |
| File `<input type="file">` | Accepts `.csv, .xlsx, .xls` | On file selection: calls `prUploadApi.detectColumns(token, file, clientId)` (pre-detect API call). |
| **Back** | Text button | `setUiStep(2)` |
| **Continue to start** | `<button>` | Gated by `canGoToStep4`. |
| Tally export guide | `<details>` accordion | _"How to export from Tally (Purchase Register)"_ — collapsed by default. |

### Register type detection banner (`RegisterTypeDetectionBanner`)
Appears if `prUploadApi.detectColumns()` returns a `register_type_detection` result:

- **Sales register detected (high/medium confidence):**
  - **It's a sales register — go to GSTR-1 Check** → `router.push('/reconcile/gstr1/new?client_gstin_id=…')` ← exits wizard permanently, no back link
  - **Override: treat as purchase register** → `setRegisterTypeOverride("purchase")`
- **Ambiguous / requires choice:** upload button stays disabled until one of the above is clicked.

### Sub-flow A — Saved mapping covers this file
**Green box:** _"Using saved mapping from last upload."_

| Button | Action |
|---|---|
| **Confirm & Upload** | SHA-256 hash → `importWizardApi.signedUrl()` → PUT to R2 (with `prProgress` bar) → `importWizardApi.prUploadComplete()` → `runDetectWithRetry()` |
| **Edit mapping** | `setConfirmSavedMapping(false); setSavedMappingCovers(false)` → drops to Sub-flow C |

### Sub-flow B — Schema OK (standard Tally headers)
**Text:** _"Columns look standard. You can upload as-is, or adjust the mapping below."_

Pre-upload mapping table: two columns — **Your file has** | **Maps to** — each row a `<select>` of target fields.

| Button | Action |
|---|---|
| **Upload & continue** | `onPrUpload()` |

### Sub-flow C — Unknown schema (manual mapping required)
**Text:** _"Map your file columns to ReconDesk fields. Required fields show a red asterisk; at least one tax field is required."_

Same mapping table as Sub-flow B. Required field completion indicators shown below: `GSTIN* ✓ / ✕`, `Invoice Number* ✓ / ✕`, `Invoice Date* ✓ / ✕`, `Taxable Value* ✓ / ✕`, `Tax (CGST/SGST/IGST/Cess)* ✓ / ✕`.

| Button | Action |
|---|---|
| **Save mapping & upload** | Validates → `prUploadApi.saveMapping(token, clientId, items)` → `onPrUpload()` |

### Post-upload server-side column detection table
After `runDetectWithRetry()` resolves, a second table renders:

**Columns:** Standard field | Detected column | Confidence | Sample values | Action `<select>`

| Confidence | Badge color | Extra action |
|---|---|---|
| `high` | Green | None |
| `medium` | Amber | Dropdown to change column assignment |
| `low` | Red | Dropdown + **"I confirm this mapping is correct"** checkbox (must be checked) |
| `not_found` (required) | Red | Dropdown — blocks **Continue to start** until filled |

### Blocking warnings in Step 3
`multi_sheet_combine` and `missing_invoice_number` render with **I understand — continue** button; until clicked, `canGoToStep4 = false`. Also shows `prParseWarning` amber notice if returned by server.

### Gating condition for **Continue to start**
```
canGoToStep4 = requiredOk && taxOk && lowOk && !!mappingLocal?.length && highRiskWarningsOk
```
- `requiredOk`: GSTIN, invoice_number, invoice_date, taxable_value all have a detected_column ≠ not_found
- `taxOk`: at least one of CGST / SGST / IGST / Cess / total_tax mapped
- `lowOk`: all low-confidence rows have `confirmed = true`
- `highRiskWarningsOk`: no unacknowledged blocking warnings

### Loading / wait states
- File selection triggers pre-detect: _"Reading columns…"_ while `preDetectBusy`.
- Upload: `prProgress` bar 0–100%.
- Post-upload server detection: _"Detecting columns…"_ while `detectBusy`.
- **Gap:** ~2–5s between upload success and detection table appearing.

### Click path (Sub-flow A — saved mapping, no warnings): Step 3 done
1. Choose file from picker (2 interactions) → wait for pre-detect
2. Click **Confirm & Upload** (1 click) → wait for upload + detect
3. Click **Continue to start** (1 click)

**Total: 4 interactions + wait.**

### Click path (Sub-flow C — first-time file, manual mapping, 1 blocking warning): Step 3 done
1. Choose file (2) → wait for pre-detect
2. Map N columns via dropdowns (typically 5–12 interactions for a Tally export)
3. Click **Save mapping & upload** (1) → wait for upload + detect
4. Confirm any `low`-confidence rows with checkbox (1–3 interactions)
5. Click **I understand — continue** on blocking warning (1)
6. Click **Continue to start** (1)

**Total: 11–20 interactions + wait.**

### Friction points
- **Two-phase mapping confusion:** Pre-detect mapping table (before upload) and the post-upload server detection table are both shown to the CA as separate steps. CAs who map columns before upload are surprised to see another mapping table afterward.
- **Failed upload doesn't reset pre-detect state.** A CA who fixes a column-mapping mistake after an upload failure must re-select the file to re-trigger pre-detect.
- **ITC claimed period is labeled "optional"** but affects Rule 37 interest calculation. No tooltip or consequence warning for leaving it blank.
- **Tally export guide is hidden** inside a `<details>` accordion — invisible to first-time CAs unless expanded.

---

## Screen 8 — Wizard Step 4: Start Reconciliation
**Route:** `/reconcile/[client_id]/new` (`uiStep === 4`)  
**Source:** `page.tsx` lines 2106–2172

### Purpose
The CA reviews a pre-flight summary and fires the reconciliation engine.

### Confirmation card shows
- Period: `[Month Year]`
- GSTR-2B: `[filename] ([size]) — N records`
- Purchase register: `[filename] ([size]) — M records`
- ITC claimed period: `[Month Year]` (if set)
- Summary: _"N GSTR-2B records vs M Purchase Register records"_

### Interactive elements
| Label | Type | Action |
|---|---|---|
| **Start reconciliation** | `<button>` | Calls `importWizardApi.start(token, runId)`. **This is a blocking HTTP call** — the server holds the connection until the engine finishes (Railway connection timeout: ~300s). Optimistic UI: immediately sets `run.status = 'processing'` and `poll = { pct: 0, message: 'Starting…' }`. |
| **Back** | Text button | `setUiStep(3)` |
| **Try again** (on prior error) | `<button>` | `importWizardApi.retry(token, runId)` → refreshes run state |

### Processing screen (while `run.status === 'pending' \| 'processing'`)
The page swaps to a full-screen processing view:
- `<h1>Reconciliation in progress</h1>`
- `<p>{msg}</p>` (status message from poll)
- Horizontal progress bar + `{pct}%` counter
- If `pollSlow = true` (>5 min elapsed): _"This is taking longer than expected. Please keep this page open — reconciliation is still running."_
- **Cancel run** `<button>` → `importWizardApi.cancel()` → `router.push('/clients/[id]')` ← **no confirmation dialog**
- **Back to Dashboard** `<Link>` → `/dashboard`

**Polling:** `importWizardApi.pollStatus()` every 3 000ms.  
**On complete:** `router.push('/reconcile/runs/[run_id]/results')` automatically.

### Error codes surfaced on Start
| Code | Message rendered |
|---|---|
| 402 | _"No runs remaining on your current plan. Please upgrade to continue."_ + **Go to Billing** link |
| 429 | _"Too many requests. Please wait a moment and try again."_ |
| 409 | `start409` message rendered separately (run already started/duplicate) |

### Click path: Step 4 → results page
1. Click **Start reconciliation** (1 click)
2. Processing screen renders automatically (~20–120s for typical datasets)
3. Auto-redirect to results on completion (0 clicks)

**Total: 1 click.**

### Friction points
- **Blocking HTTP call** — if the network blips during the 300s window, the CA sees an error even though the engine may have completed successfully. There is no "check run status" recovery path on the error screen.
- **Cancel run has no confirmation dialog** — one misclick on the processing screen deletes the in-progress run.
- **No ETA or step counter** — the CA cannot distinguish "just started at 2%" from "stuck at 2% for 3 minutes."

---

## Screen 9 — Reconciliation Results
**Route:** `/reconcile/runs/[run_id]/results`  
**Source:** `runs/[run_id]/results/page.tsx` (5 751 lines)

This is the primary working screen. It has multiple layers of interactive content.

---

### 9A — Sticky Summary Header (always visible)
`position: sticky; top: 0; backdrop-blur-md`

**Five stat cards:**
| Card label | Source field |
|---|---|
| Total GSTR | `total_gstr_records` |
| Matched | `clean_matched_count` |
| Review Required | `review_required_count` |
| Missed ITC / Net 2B Difference | `missed_itc_total_amount` |
| ITC at Risk — Not in GSTR-2B | `wrongful_risk_total_amount` |

**Match rate bars:** Two horizontal `<div>` bars — "Clean Match Rate" and "Total Linked Rate" — with percentage pills below them.

**Confidence Summary Card (`ConfidenceSummaryCard`):** Segmented bar + chips for High / Medium / Low / Unmatched invoice counts (from `GET /api/reconcile/runs/[id]/confidence-summary`).

**Header buttons (top-right of header):**
| Label | Action |
|---|---|
| **Excel** | `GET /api/reconcile/runs/[id]/export/excel` → triggers download of `ReconDesk-report.xlsx` |
| **Delete run** (admin only) | `setDeleteModalOpen(true)` |

**Alert banners (conditionally shown below stats):**
- ISD/IMPG present → amber banner: _"ISD / Import of goods not included in this reconciliation"_
- Unmatched CDN/DBN → amber banner + **View quarantined notes** button → `setResultsTab("unmatched_notes")`
- PR rows skipped (missing invoice number) → amber status notice with count

---

### 9B — Results Bucket Tabs (`ResultsBucketTabs`)

| Tab ID | Label | Count source |
|---|---|---|
| `matched` | Matched | `clean_matched_count` |
| `review_required` | Review Required | `review_required_count` |
| `duplicate_entry` | Duplicate Entry | `duplicate_entry_count` |
| `unmatched_notes` | Notes — Not Auto-Matched | `unmatched_notes_count` |
| `itc` | Missed ITC | `missed_itc_count` |
| `risk` | ITC at Risk | `wrongful_risk_count` |
| `rule37` | Rule 37 | `rule37Data.total` (lazy — loads only when tab clicked) |
| `section17` | Section 17(5) | `section17Data.total` (lazy) |

**Right of tab bar:** **Download Report (PDF)** `<button>` → `buildReconciliationReportPdf()` (fetches all bucket data client-side → builds PDF → triggers download). No progress indicator during the 5–20s build phase.

---

### 9C — Tab: Matched
**API:** `GET /api/reconcile/runs/[id]/matched?page=&limit=&sort=&search=&match_level=&has_notes=&section_17_5=&amount_min=&amount_max=&ims_status=`

**Filter toolbar:**
| Control | Type | Values |
|---|---|---|
| Search `<input>` | Text, 400ms debounce | Invoice number, GSTIN, supplier name |
| Match Level | `<select>` | All (blank) / EXACT / FUZZY / MANUAL |
| Has Notes | Toggle button | On / Off |
| Section 17(5) | Toggle button | On / Off |
| Amount Min / Amount Max | `<input type="number">` | Numeric range |
| IMS Status | `<select>` | All / accepted / rejected / pending / etc. |
| Sort | `<select>` | Amount: High–Low, Low–High; Date: Newest, Oldest; Supplier A–Z |
| Page size | `<select>` | 25 / 50 / 100 / 200 |

**Table columns:** GSTIN | Invoice Number | Date | Amount | Match Level | Confidence | IMS | Discrepancy Note | Notes Count | What / Why / Next guidance | Action

**Per-row interactions:**
- Click row → opens side drawer with full invoice detail
- **why?** button (Info icon) → toggles `ComparedFieldsAccordionRow` — a field-by-field breakdown table inline below the row (Rule fired, matched fields, differed fields, normalized pairs)
- Match confidence badge (e.g., "92% match") → also toggles the accordion

**Side drawer (`activeRecord` panel):**
- Invoice identity (GSTIN, number, date, amount)
- Decision block: **What is wrong** | **Why it happened** | **What to do next**
- GSTR-2B vs Purchase Register side-by-side comparison table
- Notes list (author, timestamp, text)
- New note `<textarea>` + **Add note** `<button>` → `POST /api/notes/[record_id]` with `{ note, run_id, record_type: 'matched' }` (optimistic update)
- Decision buttons: **Mark as Acted** | **Mark as Ignored** | **Reset to Pending** → `PATCH /api/reconcile/records/bulk-update` with `{ decision_status }`

**Late matches sub-section** (shown if `late_match_count > 0`): collapsible table of invoices matched from a different GSTR-2B period than the run period.

---

### 9D — Tab: Review Required
Same filter controls and table structure as Matched.  
Query adds `force_review_required: true`.  
**Default sort:** "Confidence: Low to High" (lowest confidence first — most problematic first).

**Auto-approve settings panel (admin only):**
- `<input type="number">` labeled _"Auto-approve confidence threshold"_ (0–100, default 95)
- **Save** → `PATCH /api/reconcile/settings/auto-approve-threshold` → toast "Auto-approve threshold saved"

> **Friction:** No inline label or tooltip communicating this setting affects **future runs only**, not the current Review Required rows.

---

### 9E — Tab: Missed ITC
**API:** `GET /api/reconcile/runs/[id]/itc?page=&limit=&sort=&amount_min=&amount_max=&supplier_gstin=&date_from=&date_to=&ims_status=`

**Section header:** "ITC You Can Still Claim" (or "Net 2B Documents Not Booked in PR" if CDN rows present) + total amount badge + **Download CSV** `<button>` → `GET .../export/itc?[filters]`

**Group by Supplier** toggle → fetches all pages (`fetchAllBucketPages` with limit 250) → renders `SupplierGroupView` accordion tree.

**Top 5 suppliers table:** GSTIN | Trade Name | Invoice Count | Total Amount | Impact badge (high/medium/low)

**Filter toolbar:** Amount Min/Max | Supplier GSTIN `<input>` | Date From/To | IMS Status `<select>` | Sort

**Bulk actions:**
- Checkbox per row (header = select all on page; shows `indeterminate` when partial)
- **Mark as Acted** | **Mark as Ignored** → `PATCH /api/reconcile/records/bulk-update`

**Invoice cards (`DecisionInvoiceCard`):**
- GSTIN, invoice number, date, amount
- Three structured fields: **What is wrong** | **Why it happened** | **What to do next**
- ImpactBadge (relative to highest amount on page)
- Checkbox for selection

---

### 9F — Tab: ITC at Risk
**API:** `GET /api/reconcile/runs/[id]/risk?page=&limit=&sort=&amount_min=&amount_max=&supplier_gstin=&risk_level=`

Additional filter: **Risk Level** `<select>` (all / high / medium / low).

Same structure as ITC tab (supplier table, bulk actions, invoice cards).

**Follow-up letter:** **Generate Follow-up Letter** `<button>` → `SupplierFollowupLetterModal`.  
Condition: all selected rows must share the same GSTIN. If not: _"Select invoices from one supplier only to generate a combined follow-up letter."_  
If selection spans multiple pages: _"Some selected invoices are on another page. Generate follow-up for rows on this page, or clear selection and re-select here."_

---

### 9G — Tab: Rule 37
**API:** `GET /api/reconcile/runs/[id]/rule37?page=&limit=` (fetched lazily when `rule37Open = true`)

**`Rule37SummarySection`:** Total ITC at risk + coverage sublabel (e.g., "12 of 40 invoices resolved").

**Per-row buttons:**
| Label | Action |
|---|---|
| **Mark as Settled** | Opens `Rule37MarkPaidModal`: amount paid `<input>`, TDS deducted `<input>`, TDS confirmed `<checkbox>` → `PATCH /api/reconcile/runs/[id]/rule37/[record_id]` with `{ status: 'resolved', amount_paid, tds_deducted, tds_confirmed }` |
| **Note reversal** | `PATCH ...` with `{ status: 'acknowledged' }` |

Toast on success: _"Rule 37 marked as settled"_ or _"Rule 37 ITC reversal noted"_ (auto-dismiss 3s).

---

### 9H — Tab: Section 17(5)
**API:** `GET /api/reconcile/runs/[id]/section17?page=&limit=`

Table of invoices with blocked ITC categories. Same per-row decision buttons as other tabs.

---

### 9I — Tab: Duplicate Entry
**API:** `GET /api/reconciliation/results/[run_id]/invoices?category=duplicate_entry&page=1&page_size=200`

`DecisionInvoiceCard` list with sort controls.

---

### 9J — Tab: Notes — Not Auto-Matched
**API:** `GET /api/reconciliation/results/[run_id]/invoices?category=unmatched_notes&page=1&page_size=200`

`DecisionInvoiceCard` list for credit/debit notes excluded from auto-matching.

---

### 9K — IMS Actions Panel
**Source:** `components/reconcile/ImsActionPanel.tsx`  
Rendered below tab content. Amber "Unconfirmed recommendations" section.

**State: idle**
- Amber dashed box: _"Draft only until you Load, then Confirm — not a pre-filled GSTN decision."_
- **Load recommendations** `<button>` → `GET /api/ims/[run_id]/recommendations` → populates invoice list.

**State: loading**
- `<Loader2>` spinner + _"Loading draft recommendations…"_

**State: available (after load)**
- Invoice count badge in section header
- **Bulk action bar:**

| Button | Condition | Action |
|---|---|---|
| **Select high-confidence Accept (N)** | Always shown | Selects all high-confidence Accept rows (`selectHighConfidenceAccepts()`) |
| **Clear selection** | Always | `clearSelection()` |
| **Confirm [action] (N)…** | Enabled when ≥1 row selected and all selected rows share the same action | Opens `ImsDeliberateConfirm` modal |
| **Mixed actions — align before bulk confirm** | Shown (disabled) when selected rows have different actions | No action — instructional label |

**Per-invoice row (`ImsInvoiceRow`):**
- GSTIN, invoice number, recommended action badge
- Checkbox (select/deselect)
- **Why?** toggle → expands rationale text
- Action override (Accept / Reject / Hold) inline controls
- **Confirm one** `<button>` → opens single-invoice confirm modal

**IMS Confirm flow (`ImsDeliberateConfirm` modal):**
1. Summary shown: action type + count
2. CA clicks **Confirm**
3. `POST /api/ims/[run_id]/actions/confirm` with full invoice list + chosen actions
4. Polls `GET /api/ims/[run_id]/actions/[reference_id]/status` every 3 000ms (up to `MAX_POLLS` attempts)
5. Inline status: _"Waiting on GSTN IMS… status_cd=— (poll N/MAX)"_
6. On success: _"GSTN confirmed IMS action (inner status_cd P)"_
7. On failure: red error banner with `error_message`
8. On poll timeout: error _"Timed out waiting for GSTN IMS confirmation. Do not assume success."_

**Phase 4 note (incomplete feature visible in production):** When the backend returns `phase4_note`, the panel renders:  
_"Phase 4 hook (not built): [note]"_ — displayed to production users with no actionable guidance.

---

### 9L — Audit Observations Panel
**Source:** `components/AuditObservationsPanel.tsx`  
**API:** `GET /api/audit-observations/[run_id]` (via `useSWR` on mount)

Collapsed accordion. On expand:
- Summary chips: N Critical | N High | N Medium | N Low | Total financial impact (₹)
- Per-observation cards sorted by severity (Critical → High → Medium → Low):
  - `SeverityBadge` (Critical / High / Medium / Low)
  - Title, Description, Section Reference, Affected Count
  - Financial impact amount (with Rule 37 caveat note where applicable)
  - Recommendation text
  - **Affected invoices (N)** / **Affected fields (N)** toggle → expands a list

**Read-only.** No action buttons — informational diagnostic panel.

---

### 9M — Advanced Export Panel
**Source:** `components/reconcile/AdvancedExportPanel.tsx`

Collapsed accordion with `<ChevronDown>` toggle. On expand:

**Filter controls:**
| Control | Type | Values |
|---|---|---|
| Status pills | Multi-select toggle buttons | Matched / Mismatched / Missing / ITC at Risk — Not in GSTR-2B / Duplicate |
| Period | `<input type="text">` | Pre-filled with current period (YYYY-MM) |
| ITC eligibility category | `<select multiple>` | Hold Ctrl/Cmd for multi-select. Options load from Apply Filters call. |

**Action buttons:**
| Label | Action |
|---|---|
| **Apply Filters** | `POST /api/export/advanced` `{ format: 'preview' }` → shows _"N rows match"_ count |
| **Export to Excel** | `POST /api/export/advanced` `{ format: 'xlsx' }` → downloads file |
| **Export to PDF** | `POST /api/export/advanced` `{ format: 'pdf' }` → downloads file |

---

### 9N — Finalize Reconciliation
**Visibility:** Admin only (`summary.user_role === 'admin'`). Staff users see a passive text message: _"Ask your admin to finalize this reconciliation."_

**Finalize bar:** Sticky bottom bar visible when `!isRunFinalized && user_role === 'admin'`.
- **Finalize Reconciliation** `<button>` → `setFinalizeModalOpen(true)`

**Finalize modal checklist (all 5 required before Finalize button enables):**

| Item | Key |
|---|---|
| ☐ I have reviewed all matches requiring human review | `reviewed_l3_matches` |
| ☐ I have verified all Section 17(5) flagged invoices | `verified_section_17_5` |
| ☐ I have reviewed all Rule 37 payment deadline warnings | `reviewed_rule_37` |
| ☐ I have contacted suppliers with missing GSTR filings (if any) | `contacted_suppliers` |
| ☐ All ITC amounts match what I plan to claim in GSTR-3B | `itc_amounts_verified` |

| Button | Condition | Action |
|---|---|---|
| **Finalize** | All 5 checked, not `finalizing` | `POST /api/reconcile/runs/[id]/finalize` with `{ checklist_snapshot }` → run status = `'final'` → toast _"Reconciliation finalized successfully"_ |
| **Cancel** | Always (if not `finalizing`) | Closes modal, resets checklist |

**Post-finalization state:**
- Header shows black pill badge: _"Finalized by [name] on [date]"_
- Finalize bar removed from DOM
- **Finalize Reconciliation** button no longer rendered

### Click path: arrived on results → finalized
1. Click **Finalize Reconciliation** bar (1 click)
2. Check all 5 items (5 clicks)
3. Click **Finalize** (1 click)

**Total: 7 clicks.**

---

### 9O — Delete Run
| Button | Condition | Action |
|---|---|---|
| **Delete run** (in header) | Admin only | `setDeleteModalOpen(true)` |
| **Delete** (in modal) | Enabled | `DELETE /api/reconcile/runs/[id]` → `router.push('/dashboard')` |
| **Cancel** | Always | Closes modal |

---

## Screen 10 — Vendor / Supplier Detail
**Route:** `/reconcile/runs/[run_id]/vendors`

Supplier grouping view for a run. Accessible via **View Vendors** link on the client detail page.

---

## Screen 11 — GSTR-3B Comparison
**Route:** `/reconcile/runs/[run_id]/gstr3b`

`Gstr3bSummaryView` component. Shows booked vs. computed GSTR-3B ITC section values. Read-only.

---

## Screen 12 — Supplier Follow-up Log
**Component:** `SupplierFollowupAuditLogPanel`  
**Source:** `components/reconcile/SupplierFollowupAuditLogPanel.tsx`

Timestamped audit log of follow-up letters sent to suppliers. Rendered inside the results page. Read-only.

---

## Total Click Count Table

Tracks **minimum** interactions for an optimistic path (GSTN connected, saved mapping, no sanity warnings, no engine errors).

| Stage | Screen | Min Clicks | Notes |
|---|---|---|---|
| Authentication | Login | 3 | Email + Password + Sign in |
| Onboarding | Wizard | 9 | 4 fills + 4 Continues + Finish setup |
| Navigate to client | Dashboard | 1 | Click client card |
| Start wizard | Client Detail | 1 | Click New Reconciliation |
| Select period | Step 1 | 3 | Open select + pick month + Continue |
| GSTR-2B (GSTN auto-fetch, no warnings) | Step 2 | 2 | Fetch + Continue |
| Purchase register (saved mapping, no warnings) | Step 3 | 4 | Choose file + wait + Confirm & Upload + Continue |
| Start engine | Step 4 | 1 | Start reconciliation |
| Engine processing | Processing screen | 0 | Auto-redirect at completion |
| Per-invoice decision (each) | Results tabs | 2–3 | Checkbox + bulk action, or row click + drawer button |
| IMS actions (if needed) | IMS panel | 3+ | Load recommendations + Select + Confirm |
| Finalize | Results (admin) | 7 | Open modal + 5 checkboxes + Finalize |
| Excel export | Results header | 1 | Direct download |
| PDF export | Results tab bar | 1 | Client-side build (~5–20s) |
| **TOTAL — returning CA, clean run, no exceptions** | — | **~23** | Login through finalize |
| **TOTAL — first-time CA: manual mapping, 2 warnings** | — | **~45–55** | Adds onboarding + mapping + acknowledgments |

---

## Summary: Friction Points & Dead Ends

### Critical friction
1. **No feedback on "Continue" (Step 1)** — `createRun()` has no spinner or button-disable, creating a double-click / duplicate run risk.
2. **Blocking HTTP call for engine start** — a 300s Railway connection timeout means a network drop during reconciliation leaves the CA on an error screen with no way to know if the run succeeded. No "check status" recovery link is shown.
3. **Two-phase column mapping** — pre-detect (before upload) and post-upload server detection are both shown as separate mapping tables, causing confusion about which is authoritative.
4. **Cancel run — no confirmation dialog** on the processing screen. One misclick deletes an in-progress run.
5. **Phase 4 IMS hook incomplete** — `phase4_note` text is rendered in production UI with no actionable guidance for the CA.

### Navigational dead ends
- **GSTN reconnect path (Step 2 error)** → navigates away from wizard to `/clients/[id]`. Returning CAs get the Resume/Start fresh banner, but this is not explained on the error screen.
- **Sales register detection → redirect** → CA is pushed to `/reconcile/gstr1/new` with no back link if it was a false positive.
- **Zero GSTR-2B + "Continue anyway"** → engine runs, produces 0 matches, no warning at Step 4 that results will be empty.

### Ambiguous states
- Results tabs with 0 records render an empty table with no messaging (`EmptyTableState` exists but is not consistently applied across all tabs).
- **Decision status** (Acted / Ignored / Pending) is never aggregated in the summary stats header — CAs have no quick view of how many ITC items they've already decided on.
- **Auto-approve threshold** (Review Required tab) modifies future run behavior only — no label or tooltip communicates this to the CA.
- The **processing screen** shows a `%` counter that can stall at a low percentage for several minutes — CAs cannot distinguish a slow run from a stuck one until the `pollSlow` message appears after 5 minutes.

### Loading gaps without visual feedback
- Step 2: ~2–5s blank between upload success and sanity check results appearing.
- Step 3: ~2–5s blank between upload success and column detection table appearing.
- PDF report generation: fetches all bucket data client-side then renders — no progress indicator during the 5–20s build phase for large datasets.
