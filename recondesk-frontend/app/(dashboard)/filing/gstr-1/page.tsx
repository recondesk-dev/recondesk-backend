"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ClientPeriodSelector } from "@/components/filing/ClientPeriodSelector";

function Gstr1IndexContent() {
  const searchParams = useSearchParams();
  const initialClientId = searchParams.get("client_gstin_id") || undefined;
  const initialPeriod = searchParams.get("period") || undefined;

  return (
    <ClientPeriodSelector
      title="File Form GSTR-1"
      subtitle="Prepare outward supply return, B2B/B2C sections, export official GSTN offline JSON, or save directly to the GSTN portal via GSP."
      returnType="gstr-1"
      initialClientId={initialClientId}
      initialPeriod={initialPeriod}
      badgeText="Outward Supplies"
      badgeColor="bg-blue-50 text-blue-700 border-blue-200"
    />
  );
}

export default function Gstr1FilingIndexPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center text-xs text-gray-500">
          Loading GSTR-1 workspace…
        </div>
      }
    >
      <Gstr1IndexContent />
    </Suspense>
  );
}
