"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import { filingApi } from "@/lib/api";
import { ClientPeriodSelector } from "@/components/filing/ClientPeriodSelector";

function Gstr3bIndexContent() {
  const searchParams = useSearchParams();
  const initialClientId = searchParams.get("client_gstin_id") || undefined;
  const initialPeriod = searchParams.get("period") || undefined;

  const { data: features } = useSWR(
    "filing-features",
    () => filingApi.features()
  );

  const isLiveFiling = features?.gstr3b_filing_enabled === true;

  return (
    <ClientPeriodSelector
      title="File Form GSTR-3B"
      subtitle="Reconcile outward liabilities, auto-populate Table 4 ITC from purchase runs, generate official GSTN offline JSON, or file directly via GSP."
      returnType="gstr-3b"
      initialClientId={initialClientId}
      initialPeriod={initialPeriod}
      badgeText={isLiveFiling ? "Live GSP Filing Active" : "Preparation & Offline JSON Export"}
      badgeColor={isLiveFiling ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-purple-50 text-purple-700 border-purple-200"}
    />
  );
}

export default function Gstr3bFilingIndexPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center text-xs text-gray-500">
          Loading GSTR-3B workspace…
        </div>
      }
    >
      <Gstr3bIndexContent />
    </Suspense>
  );
}
