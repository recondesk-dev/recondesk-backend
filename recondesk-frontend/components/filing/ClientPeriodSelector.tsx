"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Calendar, Building2, ArrowRight, CheckCircle2 } from "lucide-react";
import useSWR from "swr";

import { clientsApi, type ClientGstin } from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { toFilingPeriodYyyyMm } from "@/components/filing/filingHelpers";

type Props = {
  title: string;
  subtitle: string;
  returnType: "gstr-1" | "gstr-3b";
  initialPeriod?: string;
  initialClientId?: string;
  badgeText?: string;
  badgeColor?: string;
};

function getDefaultFilingPeriod(): string {
  const d = new Date();
  // Default to previous month
  d.setMonth(d.getMonth() - 1);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function getRecentPeriods(count = 12): Array<{ value: string; label: string }> {
  const out: Array<{ value: string; label: string }> = [];
  const monthNames = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
  ];
  const now = new Date();
  for (let i = 1; i <= count; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const val = `${y}-${m}`;
    const lbl = `${monthNames[d.getMonth()]} ${y} (${val})`;
    out.push({ value: val, label: lbl });
  }
  return out;
}

export function ClientPeriodSelector({
  title,
  subtitle,
  returnType,
  initialPeriod,
  initialClientId,
  badgeText,
  badgeColor = "bg-blue-50 text-blue-700 border-blue-200",
}: Props) {
  const router = useRouter();
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const [period, setPeriod] = useState<string>(() => initialPeriod || getDefaultFilingPeriod());
  const [clientId, setClientId] = useState<string>(initialClientId || "");
  const [error, setError] = useState<string | null>(null);

  const clientsKey = token ? (["filing-clients-picker", token] as const) : null;
  const { data: clients, isLoading: clientsLoading } = useSWR(
    clientsKey,
    ([, t]) => clientsApi.list(t)
  );

  const recentPeriods = useMemo(() => getRecentPeriods(18), []);

  const selectedClient = useMemo(() => {
    if (!clients || !clientId) return null;
    return clients.find((c: ClientGstin) => c.id === clientId) ?? null;
  }, [clients, clientId]);

  const handleContinue = () => {
    setError(null);
    const validPeriod = toFilingPeriodYyyyMm(period);
    if (!validPeriod) {
      setError("Please select or enter a valid filing period in YYYY-MM format.");
      return;
    }
    if (!clientId) {
      setError("Please select a client to prepare this return.");
      return;
    }

    const path = `/filing/${returnType}/${encodeURIComponent(validPeriod)}?client_gstin_id=${encodeURIComponent(clientId)}`;
    router.push(path);
  };

  return (
    <div className="mx-auto max-w-2xl space-y-8 px-6 py-10">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight text-[var(--ink)]">
            {title}
          </h1>
          {badgeText ? (
            <span className={`px-3 py-1 text-xs font-semibold rounded-full border ${badgeColor}`}>
              {badgeText}
            </span>
          ) : null}
        </div>
        <p className="text-sm text-gray-500 leading-relaxed">
          {subtitle}
        </p>
      </div>

      <div className="rounded-2xl border border-gray-200/80 bg-white p-6 shadow-sm space-y-6">
        {/* Client Selection */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
            <Building2 className="h-4 w-4 text-gray-400" />
            Select Client
          </label>
          <select
            value={clientId}
            onChange={(e) => {
              setClientId(e.target.value);
              setError(null);
            }}
            disabled={clientsLoading}
            className="h-11 w-full rounded-xl border border-gray-200 bg-[#F9F9FA] px-4 text-[13px] font-medium text-[var(--ink)] outline-none transition focus:border-black/30 focus:bg-white focus:ring-2 focus:ring-black/5"
          >
            <option value="">
              {clientsLoading ? "Loading clients…" : "Choose a client from your roster…"}
            </option>
            {(clients || []).map((c: ClientGstin) => (
              <option key={c.id} value={c.id}>
                {(c.trade_name || c.legal_name || "Client").trim()} · {c.gstin}
              </option>
            ))}
          </select>

          {selectedClient ? (
            <div className="mt-2.5 flex items-center justify-between rounded-xl bg-gray-50 px-4 py-2.5 text-xs text-gray-600 border border-gray-100">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                <span className="font-semibold text-gray-900">
                  {selectedClient.trade_name || selectedClient.legal_name}
                </span>
                <span className="font-mono text-gray-500">
                  ({selectedClient.gstin})
                </span>
              </div>
              <span className="text-[11px] font-medium text-gray-400 uppercase">
                State: {selectedClient.state_code || selectedClient.gstin.slice(0, 2)}
              </span>
            </div>
          ) : null}
        </div>

        {/* Period Selection */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
            <Calendar className="h-4 w-4 text-gray-400" />
            Filing Return Period
          </label>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <span className="text-[11px] font-medium text-gray-400">Quick Select Month</span>
              <select
                value={period}
                onChange={(e) => {
                  setPeriod(e.target.value);
                  setError(null);
                }}
                className="mt-1 h-11 w-full rounded-xl border border-gray-200 bg-[#F9F9FA] px-4 text-[13px] font-medium text-[var(--ink)] outline-none transition focus:border-black/30 focus:bg-white focus:ring-2 focus:ring-black/5"
              >
                {recentPeriods.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <span className="text-[11px] font-medium text-gray-400">Or Custom YYYY-MM</span>
              <input
                type="text"
                value={period}
                onChange={(e) => {
                  setPeriod(e.target.value);
                  setError(null);
                }}
                placeholder="2026-08"
                className="mt-1 h-11 w-full rounded-xl border border-gray-200 bg-[#F9F9FA] px-4 text-[13px] font-mono text-[var(--ink)] outline-none transition focus:border-black/30 focus:bg-white focus:ring-2 focus:ring-black/5"
              />
            </div>
          </div>
        </div>

        {/* Error banner */}
        {error ? (
          <div className="rounded-xl bg-red-50 p-3 text-xs text-red-600 border border-red-100">
            {error}
          </div>
        ) : null}

        {/* Action Button */}
        <div className="pt-2">
          <button
            type="button"
            onClick={handleContinue}
            disabled={!clientId || !period}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--ink)] py-3 text-sm font-semibold text-white shadow-sm transition hover:opacity-90 disabled:opacity-40"
          >
            Continue to {returnType === "gstr-1" ? "GSTR-1 Preparation" : "GSTR-3B Return"}
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
