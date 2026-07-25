"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { toFilingPeriodYyyyMm } from "@/components/filing/filingHelpers";

export default function Gstr1FilingIndexPage() {
  const router = useRouter();
  const [period, setPeriod] = useState("");
  const [clientId, setClientId] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-lg space-y-6 px-8 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
          File GSTR-1
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Enter the return period (YYYY-MM), then upload the Sales Register on
          the next screen.
        </p>
      </div>

      <label className="block">
        <span className="text-[12px] font-medium text-gray-500">
          Period (YYYY-MM)
        </span>
        <input
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          placeholder="2026-07"
          className="mt-1.5 h-10 w-full rounded-full border-0 bg-white px-4 text-[13px] font-medium shadow-[var(--shadow-soft)] outline-none focus:ring-2 focus:ring-black/10"
        />
      </label>

      <label className="block">
        <span className="text-[12px] font-medium text-gray-500">
          Client GSTIN id (optional)
        </span>
        <input
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          placeholder="uuid from clients"
          className="mt-1.5 h-10 w-full rounded-full border-0 bg-white px-4 text-[13px] font-medium shadow-[var(--shadow-soft)] outline-none focus:ring-2 focus:ring-black/10"
        />
      </label>

      {error ? (
        <p className="text-[13px] text-gray-600">{error}</p>
      ) : null}

      <button
        type="button"
        className="inline-flex rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white"
        onClick={() => {
          const p = toFilingPeriodYyyyMm(period);
          if (!p) {
            setError("Period must be YYYY-MM (e.g. 2026-07).");
            return;
          }
          const q = clientId.trim()
            ? `?client_gstin_id=${encodeURIComponent(clientId.trim())}`
            : "";
          router.push(`/filing/gstr-1/${encodeURIComponent(p)}${q}`);
        }}
      >
        Continue
      </button>

      <p className="text-[13px] text-gray-500">
        Or open from{" "}
        <Link
          href="/reconcile/gstr1/results"
          className="font-semibold text-[var(--ink)] underline-offset-2 hover:underline"
        >
          GSTR-1 results
        </Link>{" "}
        after a Sales Reconciliation.
      </p>
    </div>
  );
}
