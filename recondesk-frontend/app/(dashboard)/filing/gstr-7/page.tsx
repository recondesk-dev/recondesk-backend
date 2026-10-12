"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Gstr7Workbench from "@/components/filing/Gstr7Workbench";

function Gstr7PageContent() {
  const searchParams = useSearchParams();
  const clientGstinId = searchParams.get("client_gstin_id") || searchParams.get("client_id") || "";
  const period = searchParams.get("period") || "2026-07";

  return <Gstr7Workbench initialClientGstinId={clientGstinId} initialPeriod={period} />;
}

export default function Gstr7Page() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Suspense fallback={<div className="p-12 text-center text-gray-500">Loading Form GSTR-7 Workbench...</div>}>
        <Gstr7PageContent />
      </Suspense>
    </div>
  );
}
