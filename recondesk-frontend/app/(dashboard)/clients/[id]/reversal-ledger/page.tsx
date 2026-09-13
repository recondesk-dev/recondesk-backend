"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";
import { ReversalReclaimLedgerView } from "@/components/reconcile/ReversalReclaimLedgerView";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { reconcileRunsApi, clientsApi, type ReconcileRunListRow } from "@/lib/api";

function PageSkeleton() {
  return (
    <div className="space-y-4 animate-pulse p-2">
      <div className="h-6 w-64 rounded-full bg-gray-100" />
      <div className="h-4 w-96 rounded-full bg-gray-100" />
      <div className="grid grid-cols-4 gap-4 mt-6">
        <div className="h-24 rounded-2xl bg-gray-100" />
        <div className="h-24 rounded-2xl bg-gray-100" />
        <div className="h-24 rounded-2xl bg-gray-100" />
        <div className="h-24 rounded-2xl bg-gray-100" />
      </div>
      <div className="h-64 rounded-2xl bg-gray-100 mt-6" />
    </div>
  );
}

export default function ClientReversalLedgerPage() {
  const params = useParams();
  const id = typeof params?.id === "string" ? params.id : "";
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  // Fetch client details
  const { data: clientInfo } = useSWR(
    authToken && id ? [`client-info`, id] : null,
    () => clientsApi.get(authToken!, id),
    { refreshInterval: 0 }
  );

  // Fetch client runs to allow target-period reclaim selection
  const { data: clientRuns } = useSWR<ReconcileRunListRow[]>(
    authToken && id ? [`client-runs`, id] : null,
    () => reconcileRunsApi.list(authToken!, { client_gstin_id: id }),
    { refreshInterval: 0 }
  );

  const availableRuns = (clientRuns || []).map((r) => ({
    id: r.id,
    period: r.period || "—",
    is_locked: Boolean(r.is_locked),
    status: r.status || "PENDING",
  }));

  if (tokenState === false) {
    return (
      <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
        Sign in required to view Table 4 Reversal & Reclaim Ledger.
      </div>
    );
  }

  if (!authToken || !id) {
    return <PageSkeleton />;
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <span className="rounded bg-black px-2 py-0.5 text-[11px] font-bold text-white uppercase tracking-wider">
            Table 4(B)(2) & 4(D)(1)
          </span>
          <span className="text-[12px] font-mono text-gray-500">
            {clientInfo?.gstin ? `${clientInfo.gstin} • ` : ""}
            {clientInfo?.legal_name || "Client Workspace"}
          </span>
        </div>
        <h1 className="mt-1 text-xl font-bold tracking-tight text-gray-900 sm:text-2xl">
          GSTR-3B Reversal & Reclaim Ledger
        </h1>
        <p className="mt-1 text-[13px] text-gray-500 max-w-3xl">
          Longitudinal audit ledger tracking temporary ITC reversals under Section 16 & Rules 37, 37A across return periods. Record statutory fulfillment evidence, obtain Chartered Accountant signoff, and execute atomic reclaims into active GSTR-3B returns.
        </p>
      </div>

      <ReversalReclaimLedgerView
        mode="client"
        clientId={id}
        authToken={authToken}
        availableTargetRuns={availableRuns}
      />
    </div>
  );
}
