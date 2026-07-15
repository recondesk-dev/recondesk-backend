"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Gstr1ResultsView } from "@/components/reconcile/Gstr1ResultsView";
import {
  loadGstr1Result,
  type Gstr1ReconcileResult,
} from "@/lib/gstr1Reconcile";

export default function Gstr1ReconcileResultsPage() {
  const router = useRouter();
  const [result, setResult] = useState<Gstr1ReconcileResult | null | undefined>(
    undefined
  );

  useEffect(() => {
    setResult(loadGstr1Result());
  }, []);

  if (result === undefined) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8">
        <p className="text-[13px] text-gray-500">Loading results…</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="mx-auto flex min-h-[50vh] w-full max-w-lg flex-col items-center justify-center px-8 text-center">
        <h1 className="text-xl font-semibold tracking-tight text-[var(--ink)]">
          No GSTR-1 results yet
        </h1>
        <p className="mt-2 text-[14px] text-gray-500">
          Run a Sales Reconciliation to see matched invoices, mismatches, and
          the GSTR-1 vs 3B tie-out.
        </p>
        <Link
          href="/reconcile/gstr1/new"
          className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
        >
          Start GSTR-1 Check
        </Link>
      </div>
    );
  }

  return (
    <Gstr1ResultsView
      result={result}
      onRunAgain={() => router.push("/reconcile/gstr1/new")}
    />
  );
}
