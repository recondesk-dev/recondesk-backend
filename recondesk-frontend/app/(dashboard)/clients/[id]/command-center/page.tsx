"use client";

import { useParams } from "next/navigation";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { ItcCommandCenterView } from "@/components/clients/ItcCommandCenterView";

export default function ItcCommandCenterPage() {
  const params = useParams();
  const clientId = params?.id as string;
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  if (!authToken || !clientId) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3">
        <svg className="h-8 w-8 animate-spin text-black" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
        </svg>
        <p className="text-[13px] text-gray-500">Authenticating Command Center…</p>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      <ItcCommandCenterView clientId={clientId} authToken={authToken} />
    </div>
  );
}
