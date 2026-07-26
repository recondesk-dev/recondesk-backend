"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { toFilingPeriodYyyyMm } from "@/components/filing/filingHelpers";
import { filingApi } from "@/lib/api";

export default function Gstr3bFilingIndexPage() {
  const router = useRouter();
  const [period, setPeriod] = useState("");
  const [clientId, setClientId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: features, isLoading: featuresLoading } = useSWR(
    "filing-features",
    () => filingApi.features()
  );
  const enabled = features?.gstr3b_filing_enabled === true;

  if (featuresLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
        Loading…
      </div>
    );
  }

  if (!enabled) {
    return (
      <div className="mx-auto max-w-lg space-y-4 px-8 py-16 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
          GSTR-3B filing unavailable
        </h1>
        <p className="text-[14px] text-gray-500">
          GSTR-3B filing is not yet available. Save → Offset → File has not been
          live-proven end-to-end against GSTN. Offset moves real ledger money
          and stays gated until that proof completes.
        </p>
        <Link
          href="/settings"
          className="inline-flex rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white"
        >
          Back to Settings
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg space-y-6 px-8 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
          File GSTR-3B
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Enter the return period (YYYY-MM). You will confirm figures, Save,
          then deliberately Offset liability before File.
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
          router.push(`/filing/gstr-3b/${encodeURIComponent(p)}${q}`);
        }}
      >
        Continue
      </button>

      <p className="text-[13px] text-gray-500">
        Prefer the smallest-liability period for first live tests — not
        whatever period is next in sequence.
      </p>
    </div>
  );
}
