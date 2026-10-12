"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Gstr6Workbench from "@/components/filing/Gstr6Workbench";

function Gstr6PageContent() {
  const searchParams = useSearchParams();
  const clientGstinId = searchParams.get("client_gstin_id") || searchParams.get("client_id") || "";
  const period = searchParams.get("period") || "2026-07";

  return <Gstr6Workbench initialClientGstinId={clientGstinId} initialPeriod={period} />;
}

export default function Gstr6Page() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Suspense fallback={<div className="p-12 text-center text-gray-500">Loading Form GSTR-6 Workbench...</div>}>
        <Gstr6PageContent />
      </Suspense>
    </div>
  );
}
