"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Gstr5aWorkbench from "@/components/filing/Gstr5aWorkbench";

function Gstr5aPageContent() {
  const searchParams = useSearchParams();
  const clientGstinId = searchParams.get("client_gstin_id") || searchParams.get("client_id") || "";
  const period = searchParams.get("period") || "2026-07";

  return <Gstr5aWorkbench initialClientGstinId={clientGstinId} initialPeriod={period} />;
}

export default function Gstr5aPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Suspense fallback={<div className="p-12 text-center text-gray-500">Loading Form GSTR-5A Workbench...</div>}>
        <Gstr5aPageContent />
      </Suspense>
    </div>
  );
}
