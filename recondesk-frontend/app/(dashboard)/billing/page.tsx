"use client";

import useSWR from "swr";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  billingApi,
  isApiError,
  openPaymentReceipt,
  type BillingStatus,
  type PaymentHistoryRow,
} from "@/lib/api";
import { SubscriptionFeatures } from "@/components/billing/SubscriptionFeatures";
import { PricingGrid } from "@/components/billing/PricingGrid";
import { startPlanCheckout, type CheckoutPlan } from "@/lib/billing-checkout";
import { subscribeAccessToken } from "@/lib/supabase/client";

function formatInrPaise(paise: number | null | undefined): string {
  const p = Number(paise ?? 0);
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(p / 100);
}

function formatInr(n: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function planBadgeClass(plan: string | null | undefined): string {
  const p = (plan || "").toLowerCase();
  if (p === "solo") return "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200/50";
  if (p === "firm") return "bg-[var(--ink)] text-white";
  if (p === "large_firm" || p === "large firm") return "bg-[#F0F0F0] text-[var(--ink)] ring-1 ring-black/10";
  if (p === "free") return "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200/50";
  if (p === "starter") return "bg-[#F0F0F0] text-gray-700";
  if (p === "growth") return "bg-[var(--ink)] text-white";
  if (p === "pro") return "bg-[#F0F0F0] text-[var(--ink)] ring-1 ring-black/10";
  return "bg-[#F0F0F0] text-gray-700";
}

function TableSkeletonRows() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <tr key={i} className="animate-pulse border-b border-[var(--border)]">
          <td className="py-3">
            <div className="h-4 w-24 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-16 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-8 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-28 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-12 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-16 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-14 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-16 rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="h-4 w-20 rounded bg-gray-200" />
          </td>
        </tr>
      ))}
    </>
  );
}

export default function BillingPage() {
  const tBilling = useTranslations("billing");
  const [accessToken, setAccessToken] = useState<string | false | null>(null);
  const [checkoutPlan, setCheckoutPlan] = useState<CheckoutPlan | null>(null);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  useEffect(() => subscribeAccessToken(setAccessToken), []);

  const swrKey =
    typeof accessToken === "string" && accessToken.length > 0
      ? (["billing-status", accessToken] as const)
      : null;

  const {
    data: status,
    error: statusError,
    isLoading: statusLoading,
    mutate: mutateStatus,
  } = useSWR(swrKey, ([, token]) => billingApi.status(token), {
    revalidateOnFocus: true,
  });

  const histKey =
    typeof accessToken === "string" && accessToken.length > 0
      ? (["billing-history", accessToken] as const)
      : null;

  const {
    data: history,
    error: histError,
    isLoading: histLoading,
    mutate: mutateHistory,
  } = useSWR(histKey, ([, token]) => billingApi.history(token), {
    revalidateOnFocus: true,
  });

  function scrollChoosePlan() {
    document.getElementById("choose-plan")?.scrollIntoView({ behavior: "smooth" });
  }

  async function onBuyPlan(plan: CheckoutPlan, cycle: "monthly" | "yearly" = "yearly") {
    if (plan === "free") return;
    setCheckoutError(null);
    setCheckoutPlan(plan);
    try {
      await startPlanCheckout(plan, {
        billingCycle: cycle,
        onSuccess: () => {
          void mutateStatus();
          void mutateHistory();
        },
      });
    } catch (err) {
      setCheckoutError(err instanceof Error ? err.message : "Checkout failed");
    } finally {
      setCheckoutPlan(null);
    }
  }

  const banner = (
    <BillingBanner status={status} loading={statusLoading} onChoosePlan={scrollChoosePlan} />
  );

  return (
    <div className="mx-auto max-w-7xl space-y-8 text-[var(--text-primary)]">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">{tBilling("title")}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {tBilling("subtitle")}
        </p>
      </div>
      {banner}

      <section className="grid gap-3 md:grid-cols-2">
        <div className="dashboard-card p-5">
          <p className="text-sm font-medium text-gray-500">GSTINs used</p>
          <p className="mt-2 text-[1.85rem] font-semibold tracking-tight tabular-nums text-[var(--ink)]">
            {status ? `${status.gstins_used ?? 0} / ${status.gstin_limit ?? 2}` : "—"}
          </p>
        </div>
        <div className="dashboard-card p-5">
          <p className="text-sm font-medium text-gray-500">Subscription</p>
          <p className="mt-2 text-[1.85rem] font-semibold tracking-tight capitalize text-[var(--ink)]">
            {status?.subscription_active ? status.plan || "Active" : "Free"}
          </p>
          {status?.subscription_active && status?.subscription_ends_at && (
            <p className="mt-1 text-xs text-gray-500">
              Renews / ends {fmtDateShort(status.subscription_ends_at)}
            </p>
          )}
          {status &&
            !status.subscription_active &&
            status.runs_balance > 0 && (
              <p className="mt-1 text-xs text-gray-500">
                No GSTIN subscription — {status.runs_balance} legacy run
                {status.runs_balance === 1 ? "" : "s"} still available below
              </p>
            )}
          {status &&
            !status.subscription_active &&
            status.runs_balance === 0 &&
            status.subscription_ends_at && (
              <p className="mt-1 text-xs text-gray-500">
                Ended {fmtDateShort(status.subscription_ends_at)}
              </p>
            )}
        </div>
      </section>

      {statusError && isApiError(statusError) && (
        <p className="text-sm text-red-600">
          Could not load billing status: {statusError.detail}
        </p>
      )}

      {status && status.runs_balance > 0 && (
        <section className="dashboard-card space-y-4 p-6">
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            Legacy run credits
          </h2>
          <p className="text-sm text-gray-500">
            These are prepaid run packs from the old pricing model — not a GSTIN subscription.
            They still work until they expire. New purchases grant GSTIN capacity instead.
          </p>
          <div className="overflow-x-auto rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                <tr>
                  <th className="px-5 py-4 font-medium">Run pack</th>
                  <th className="px-4 py-4 font-medium">Purchased</th>
                  <th className="px-4 py-4 font-medium">Runs left</th>
                  <th className="px-4 py-4 font-medium">Expires on</th>
                  <th className="px-5 py-4 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {status.credit_batches.map((b, idx) => {
                  const exp = b.expires_at ? new Date(b.expires_at) : null;
                  const now = Date.now();
                  const useSoon =
                    exp != null &&
                    !Number.isNaN(exp.getTime()) &&
                    exp.getTime() - now < 7 * 24 * 3600 * 1000 &&
                    exp.getTime() > now;
                  const expired =
                    exp != null && !Number.isNaN(exp.getTime()) && exp.getTime() <= now;
                  return (
                    <tr
                      key={`${b.purchased_at}-${idx}`}
                      className="border-b border-[#F0F0F0] last:border-b-0"
                    >
                      <td className="px-5 py-3.5 capitalize font-medium text-[var(--ink)]">
                        {b.plan}{" "}
                        <span className="font-normal text-gray-400">(legacy)</span>
                      </td>
                      <td className="px-4 py-3.5 text-gray-500">
                        {fmtDateShort(b.purchased_at)}
                      </td>
                      <td className="px-4 py-3.5 tabular-nums">{b.runs_remaining}</td>
                      <td
                        className={`px-4 py-3.5 tabular-nums ${
                          useSoon
                            ? "font-medium text-orange-600"
                            : expired
                              ? "text-gray-400"
                              : ""
                        }`}
                      >
                        {fmtDateShort(b.expires_at)}
                      </td>
                      <td className="px-5 py-3.5">
                        <span
                          className={
                            expired
                              ? "rounded-full bg-[#F0F0F0] px-3 py-1 text-xs text-gray-600"
                              : useSoon
                                ? "rounded-full bg-orange-100 px-3 py-1 text-xs font-medium text-orange-800"
                                : "rounded-full bg-[var(--ink)] px-3 py-1 text-xs font-medium text-white"
                          }
                        >
                          {expired ? "Expired" : useSoon ? "Use soon" : "Active"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section id="choose-plan" className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">Choose a plan</h2>
          <p className="mt-1 max-w-3xl text-sm text-gray-500">
            One product. Four tiers (Free, Solo, Firm, Large Firm). Every plan includes the full desk — you only scale
            GSTIN capacity. All paid plans show +18% GST.
          </p>
        </div>

        {checkoutError && <p className="text-sm text-red-600">{checkoutError}</p>}

        <PricingGrid
          isDashboard
          loadingPlan={checkoutPlan}
          connectedGstins={status?.gstins_used || 2}
          onSelectPlan={(planId, cycle) => void onBuyPlan(planId, cycle)}
        />
      </section>

      <section className="dashboard-card p-6 sm:p-8">
        <SubscriptionFeatures compact />
      </section>

      <section className="dashboard-card space-y-4 p-6">
        <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">Payment history</h2>
        <div className="overflow-x-auto rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
              <tr>
                <th className="px-5 py-4 font-medium">Date</th>
                <th className="px-4 py-4 font-medium">Plan</th>
                <th className="px-4 py-4 font-medium">GSTINs</th>
                <th className="px-4 py-4 font-medium">Client</th>
                <th className="px-4 py-4 font-medium">Period</th>
                <th className="px-4 py-4 font-medium">Base</th>
                <th className="px-4 py-4 font-medium">GST</th>
                <th className="px-4 py-4 font-medium">Total</th>
                <th className="px-4 py-4 font-medium">Status</th>
                <th className="px-5 py-4 font-medium">Receipt</th>
              </tr>
            </thead>
            <tbody>
              {histLoading && <TableSkeletonRows />}
              {histError && isApiError(histError) && (
                <tr>
                  <td colSpan={10} className="px-4 py-6 text-red-600">
                    {histError.detail}
                  </td>
                </tr>
              )}
              {!histLoading && history && history.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center text-[var(--text-secondary)]">
                    Your first 2 reconciliations are free — no payment needed yet. Receipts appear
                    here after your first purchase.
                  </td>
                </tr>
              )}
              {!histLoading &&
                history?.map((row) => (
                  <HistoryRow
                    key={row.payment_id}
                    row={row}
                    token={typeof accessToken === "string" ? accessToken : ""}
                  />
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function BillingBanner({
  status,
  loading,
  onChoosePlan,
}: {
  status: BillingStatus | undefined;
  loading: boolean;
  onChoosePlan: () => void;
}) {
  if (loading && !status) {
    return <div className="h-14 animate-pulse rounded-[1.25rem] bg-white/70" aria-hidden />;
  }
  if (!status) return null;

  if (status.subscription_active) {
    return (
      <div className="rounded-[1.25rem] bg-[var(--ink)] px-5 py-4 text-sm text-white">
        <span className="capitalize">{status.plan}</span> active — {status.gstins_used}/
        {status.gstin_limit} GSTINs used
        {status.subscription_ends_at
          ? ` · access through ${fmtDateShort(status.subscription_ends_at)}`
          : ""}
        . Unlimited reconciliations during your subscription.
      </div>
    );
  }

  if (status.free_runs_remaining > 0) {
    return (
      <div className="rounded-[1.25rem] bg-[var(--ink)] px-5 py-4 text-sm text-white">
        You have {status.free_runs_remaining} free reconciliation
        {status.free_runs_remaining === 1 ? "" : "s"} remaining — no payment needed. Free tier
        allows up to {status.gstin_limit ?? 2} GSTINs.
      </div>
    );
  }

  if (status.runs_balance > 0) {
    const activePack = status.credit_batches?.find(
      (b) => (b.runs_remaining ?? 0) > 0 && (b.status || "").toLowerCase() !== "expired"
    );
    const packName = activePack?.plan?.trim();
    return (
      <div className="dashboard-card px-5 py-4 text-sm text-gray-700">
        <p>
          You have <strong className="text-[var(--ink)]">{status.runs_balance}</strong> legacy run
          credit{status.runs_balance === 1 ? "" : "s"} remaining
          {packName ? (
            <>
              {" "}
              from a <span className="capitalize">{packName}</span> run pack
            </>
          ) : null}
          . Your subscription is Free until you buy a GSTIN plan.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-[1.25rem] bg-orange-50 px-5 py-4 text-sm text-orange-950">
      <span>No active subscription — choose a plan to continue reconciling.</span>
      <button
        type="button"
        onClick={onChoosePlan}
        className="rounded-full bg-[var(--ink)] px-3.5 py-1.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
      >
        Choose a plan
      </button>
    </div>
  );
}

function gstinsForPlan(plan: string | null | undefined): string {
  const p = (plan || "").toLowerCase();
  if (p === "free") return "2";
  if (p === "solo") return "25";
  if (p === "firm") return "75";
  if (p === "large_firm" || p === "large firm") return "150";
  if (p === "starter") return "25";
  if (p === "growth") return "60";
  if (p === "pro") return "100";
  if (p === "monthly") return "25";
  return "—";
}

function HistoryRow({ row, token }: { row: PaymentHistoryRow; token: string }) {
  const st = (row.status || "").toUpperCase();
  const stClass =
    st === "PAID"
      ? "bg-[var(--ink)] text-white"
      : st === "FAILED"
        ? "bg-[#FEF2F2] text-[#EF4444]"
        : "bg-[#F0F0F0] text-gray-700";

  async function onReceipt() {
    if (!token) return;
    try {
      await openPaymentReceipt(token, row.payment_id);
    } catch {
      window.alert("Could not download receipt.");
    }
  }

  return (
    <tr className="border-b border-[#F0F0F0] last:border-b-0">
      <td className="px-5 py-3.5 whitespace-nowrap">{fmtDateShort(row.created_at)}</td>
      <td className="px-4 py-3.5">
        <span
          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${planBadgeClass(row.plan)}`}
        >
          {row.plan || "—"}
        </span>
      </td>
      <td className="px-4 py-3.5 tabular-nums">{gstinsForPlan(row.plan)}</td>
      <td className="px-4 py-3.5">{row.trade_name?.trim() || "—"}</td>
      <td className="px-4 py-3.5 whitespace-nowrap">{row.period || "—"}</td>
      <td className="px-4 py-3.5 tabular-nums">{formatInrPaise(row.base_amount_paise)}</td>
      <td className="px-4 py-3.5 tabular-nums">{formatInrPaise(row.gst_paise)}</td>
      <td className="px-4 py-3.5 font-medium tabular-nums">
        {formatInrPaise(row.total_amount_paise)}
      </td>
      <td className="px-4 py-3.5">
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${stClass}`}>
          {st}
        </span>
      </td>
      <td className="px-5 py-3.5">
        {st === "PAID" ? (
          <button
            type="button"
            onClick={() => void onReceipt()}
            className="text-sm font-semibold text-[var(--ink)] hover:underline"
          >
            Download
          </button>
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </td>
    </tr>
  );
}
