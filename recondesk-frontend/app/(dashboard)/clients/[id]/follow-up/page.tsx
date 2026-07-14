"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";

import { ClientFollowupHistoryPanel } from "@/components/reconcile/ClientFollowupHistoryPanel";
import { clientsApi } from "@/lib/api";
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

export default function ClientFollowupHistoryPage() {
  const params = useParams();
  const id = typeof params?.id === "string" ? params.id : "";
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const clientKey =
    authToken && id ? (["client-followup", authToken, id] as const) : null;

  const { data: client, error, isLoading } = useSWR(
    clientKey,
    ([, token, cid]) => clientsApi.get(token, cid),
    { revalidateOnFocus: false }
  );

  if (!authToken || isLoading) {
    return <PanelSkeleton />;
  }

  if (error || !client) {
    return (
      <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
        Could not load client for follow-up history.
      </div>
    );
  }

  const gstin = String(client.gstin ?? "").trim();

  return (
    <ClientFollowupHistoryPanel
      clientId={id}
      clientGstin={gstin}
      authToken={authToken}
    />
  );
}
