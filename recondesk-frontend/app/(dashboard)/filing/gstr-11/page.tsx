"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Gstr11Workbench from "@/components/filing/Gstr11Workbench";

function Gstr11PageContent() {
  const searchParams = useSearchParams();
  const clientGstinId = searchParams.get("client_gstin_id") || searchParams.get("client_id") || "";
  const period = searchParams.get("period") || "2026-10";

  return <Gstr11Workbench initialClientGstinId={clientGstinId} initialPeriod={period} />;
}

export default function Gstr11Page() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Suspense fallback={<div className="p-12 text-center text-gray-500">Loading Form GSTR-11 Workbench...</div>}>
        <Gstr11PageContent />
      </Suspense>
    </div>
  );
}
