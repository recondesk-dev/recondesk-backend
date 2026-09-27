/**
 * Focused unit tests for REM-01: Direct Backend Routing for Reconciliation APIs.
 * Verifies that /api/reconcile endpoints bypass the Next.js same-origin proxy
 * and resolve directly to NEXT_PUBLIC_API_URL (FastAPI), eliminating production timeouts,
 * while preserving proxy routing for all other intentionally proxied endpoints.
 *
 * Run with: node --test lib/apiRouting.test.ts
 */

import assert from "node:assert/strict";
import { describe, it, beforeEach, afterEach } from "node:test";
import {
  usesSameOriginProxy,
  resolveApiUrl,
  backendApiUrl,
  apiFetch,
} from "./api.ts";

describe("REM-01: usesSameOriginProxy routing classifications", () => {
  it("classifies all /api/reconcile paths as NOT using same-origin proxy", () => {
    const reconcilePaths = [
      "/api/reconcile/records/bulk-update",
      "/api/reconcile/runs",
      "/api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/summary",
      "/api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/matched",
      "/api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/itc",
      "/api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/risk",
      "/api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/review-required",
      "/api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/gstr3b",
      "/api/reconcile/runs/e04d2e4f-d316-4836-bbd8-cde22dc658b8/dispositions",
      "/api/reconcile/clients/gstin-123/supplier-followup/audit",
    ];

    for (const path of reconcilePaths) {
      assert.equal(
        usesSameOriginProxy(path),
        false,
        `Expected ${path} to bypass same-origin proxy`
      );
    }
  });

  it("preserves same-origin proxy for all other intentionally proxied paths", () => {
    const proxiedPaths = [
      "/api/notes/record-123",
      "/api/notes/run/e04d2e4f-d316-4836-bbd8-cde22dc658b8",
      "/api/audit-observations/e04d2e4f-d316-4836-bbd8-cde22dc658b8",
      "/api/reconciliation/results/run-1/invoices",
      "/api/einvoice-recon/results/run-1",
      "/api/gstr2a-delta/summary",
      "/api/einvoicing/generate",
      "/api/notices/client/123",
    ];

    for (const path of proxiedPaths) {
      assert.equal(
        usesSameOriginProxy(path),
        true,
        `Expected ${path} to use same-origin proxy`
      );
    }
  });

  it("classifies direct backend paths (e.g. auth, clients) as NOT using proxy", () => {
    const directPaths = [
      "/api/v1/auth/me",
      "/api/v1/auth/login",
      "/health",
      "/api/clients",
      "/api/work-items/item-123",
    ];

    for (const path of directPaths) {
      assert.equal(
        usesSameOriginProxy(path),
        false,
        `Expected ${path} to bypass same-origin proxy`
      );
    }
  });
});

describe("REM-01: resolveApiUrl browser environment behavior", () => {
  // Simulate browser environment where window is defined
  const originalWindow = globalThis.window;

  beforeEach(() => {
    // @ts-expect-error - simulating browser environment
    globalThis.window = {} as Window & typeof globalThis;
  });

  afterEach(() => {
    // @ts-expect-error - restoring original environment
    globalThis.window = originalWindow;
  });

  it("resolves /api/reconcile/records/bulk-update to direct backend URL in browser", () => {
    const resolved = resolveApiUrl("/api/reconcile/records/bulk-update");
    const expected = backendApiUrl("/api/reconcile/records/bulk-update");
    assert.equal(resolved, expected);
    assert.match(resolved, /^https?:\/\/.+\/api\/reconcile\/records\/bulk-update$/);
  });

  it("resolves /api/reconcile query URLs to direct backend URL in browser", () => {
    const resolved = resolveApiUrl(
      "/api/reconcile/runs/run-123/summary"
    );
    assert.equal(
      resolved,
      backendApiUrl("/api/reconcile/runs/run-123/summary")
    );
  });

  it("resolves /api/notes to relative same-origin path in browser", () => {
    const resolved = resolveApiUrl("/api/notes/record-123");
    assert.equal(resolved, "/api/notes/record-123");
  });

  it("resolves /api/audit-observations to relative same-origin path in browser", () => {
    const resolved = resolveApiUrl("/api/audit-observations/run-123");
    assert.equal(resolved, "/api/audit-observations/run-123");
  });

  it("resolves /api/reconciliation to relative same-origin path in browser", () => {
    const resolved = resolveApiUrl("/api/reconciliation/results/run-123/invoices");
    assert.equal(resolved, "/api/reconciliation/results/run-123/invoices");
  });

  it("honors directBackend=true even for proxied paths in browser", () => {
    const resolved = resolveApiUrl("/api/notes/record-123", true);
    assert.equal(resolved, backendApiUrl("/api/notes/record-123"));
  });
});

describe("REM-01: apiFetch PATCH /records/bulk-update request contract", () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // @ts-expect-error - simulating browser environment
    globalThis.window = {} as Window & typeof globalThis;
  });

  afterEach(() => {
    // @ts-expect-error - restoring original environment
    globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  });

  it("issues PATCH to direct backend URL with JSON content type, token, and body", async () => {
    let capturedUrl: string | undefined;
    let capturedMethod: string | undefined;
    let capturedHeaders: Headers | undefined;
    let capturedBody: unknown;

    // Mock global fetch
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method;
      capturedHeaders = init?.headers instanceof Headers ? init.headers : new Headers(init?.headers);
      capturedBody = init?.body;

      return new Response(JSON.stringify({ updated_count: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    const payload = {
      run_id: "e04d2e4f-d316-4836-bbd8-cde22dc658b8",
      record_ids: ["rr:003e437b-6697-47fe-a07a-3846def231cf"],
      decision_status: "acted",
    };

    const res = await apiFetch<{ updated_count: number }>(
      "/api/reconcile/records/bulk-update",
      {
        method: "PATCH",
        token: "test-auth-jwt-token",
        body: JSON.stringify(payload),
      }
    );

    // 1. URL must target the backend directly (not relative same-origin /api/reconcile)
    const expectedUrl = backendApiUrl("/api/reconcile/records/bulk-update");
    assert.equal(capturedUrl, expectedUrl);
    assert.match(capturedUrl!, /^https?:\/\/.+\/api\/reconcile\/records\/bulk-update$/);

    // 2. Method must be PATCH
    assert.equal(capturedMethod, "PATCH");

    // 3. Authorization header must be forwarded
    assert.equal(capturedHeaders?.get("Authorization"), "Bearer test-auth-jwt-token");

    // 4. Content-Type must be application/json
    assert.equal(capturedHeaders?.get("Content-Type"), "application/json");

    // 5. Body must match payload
    assert.equal(capturedBody, JSON.stringify(payload));

    // 6. Response must deserialize properly
    assert.equal(res.updated_count, 1);
  });
});

describe("REM-01: e-Invoice Key Generation & Tab Conditional Gating", () => {
  /**
   * Pure key computation function mirroring results/page.tsx:2123-2129:
   * authReady && runId && resultsTab === "einvoice"
   *   ? ([`/api/einvoice-recon/results/${runId}`, authToken] as const)
   *   : null
   */
  function computeEinvoiceResKey(
    authReady: boolean,
    runId: string | null,
    resultsTab: string,
    authToken: string | null
  ): readonly [string, string] | null {
    return authReady && runId && resultsTab === "einvoice" && authToken
      ? ([`/api/einvoice-recon/results/${runId}`, authToken] as const)
      : null;
  }

  const runId = "e04d2e4f-d316-4836-bbd8-cde22dc658b8";
  const token = "mock-jwt-token";

  it("a. Returns null on initial GSTR-2B results-page load (default tab is 'matched')", () => {
    const key = computeEinvoiceResKey(true, runId, "matched", token);
    assert.equal(key, null, "Expected e-invoice SWR key to be null on initial page load");
  });

  it("b. Returns the valid SWR key tuple when resultsTab === 'einvoice'", () => {
    const key = computeEinvoiceResKey(true, runId, "einvoice", token);
    assert.notEqual(key, null);
    assert.deepEqual(key, [`/api/einvoice-recon/results/${runId}`, token]);
  });

  it("c. Returns null for all other reconciliation tabs to prevent 404 spam", () => {
    const nonEinvoiceTabs = [
      "matched",
      "itc_on_hold",
      "review_required",
      "risk",
      "itc",
      "duplicate_entry",
      "unmatched_notes",
      "rule37",
      "section17",
      "rcm",
      "gstr3b",
      "followup",
      "ims",
    ];

    for (const tab of nonEinvoiceTabs) {
      const key = computeEinvoiceResKey(true, runId, tab, token);
      assert.equal(
        key,
        null,
        `Expected e-invoice key to be null when active tab is '${tab}'`
      );
    }
  });

  it("d. Returns null if auth is not ready or runId is missing even on 'einvoice' tab", () => {
    assert.equal(computeEinvoiceResKey(false, runId, "einvoice", token), null);
    assert.equal(computeEinvoiceResKey(true, null, "einvoice", token), null);
    assert.equal(computeEinvoiceResKey(true, "", "einvoice", token), null);
    assert.equal(computeEinvoiceResKey(true, runId, "einvoice", null), null);
  });
});

