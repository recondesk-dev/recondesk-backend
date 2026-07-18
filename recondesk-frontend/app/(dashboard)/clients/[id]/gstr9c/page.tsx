"use client";

import { useParams } from "next/navigation";

import { Gstr9cItcFyRollupPanel } from "@/components/reconcile/Gstr9cItcFyRollupPanel";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function PanelSkeleton() {
  return (
    <div className="dashboard-card animate-pulse space-y-3 p-6">
      <div className="h-4 w-48 rounded-full bg-gray-100" />
      <div className="h-10 w-full rounded-2xl bg-gray-100" />
      <div className="h-32 w-full rounded-2xl bg-gray-100" />
    </div>
  );
}

export default function ClientGstr9cItcPage() {
  const params = useParams();
  const id = typeof params?.id === "string" ? params.id : "";
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  if (tokenState === false) {
    return (
      <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
        Sign in required to view GSTR-9C ITC rollup.
      </div>
    );
  }

  if (!authToken || !id) {
    return <PanelSkeleton />;
  }

  return <Gstr9cItcFyRollupPanel clientId={id} authToken={authToken} />;
}
