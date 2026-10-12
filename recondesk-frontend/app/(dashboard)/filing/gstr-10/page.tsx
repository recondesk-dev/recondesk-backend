"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Gstr10Workbench from "@/components/filing/Gstr10Workbench";

function Gstr10PageContent() {
  const searchParams = useSearchParams();
  const clientGstinId = searchParams.get("client_gstin_id") || searchParams.get("client_id") || "";
  const period = searchParams.get("period") || "2026-10";

  return <Gstr10Workbench initialClientGstinId={clientGstinId} initialPeriod={period} />;
}

export default function Gstr10Page() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Suspense fallback={<div className="p-12 text-center text-gray-500">Loading Form GSTR-10 Workbench...</div>}>
        <Gstr10PageContent />
      </Suspense>
    </div>
  );
}
