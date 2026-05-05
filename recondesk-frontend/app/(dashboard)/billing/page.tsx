"use client";

import useSWR from "swr";
import { useEffect, useState } from "react";
import {
  billingApi,
  isApiError,
  openPaymentReceipt,
  type BillingStatus,
  type PaymentHistoryRow,
} from "@/lib/api";
import { subscribeAccessToken } from "@/lib/supabase/client";

const WA_NUMBER = process.env.NEXT_PUBLIC_BILLING_WHATSAPP ?? "919876543210";

function formatInrPaise(paise: number | null | undefined): string {
  const p = Number(paise ?? 0);
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(p / 100);
}

function formatInrWhole(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
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
  if (p === "starter") return "bg-slate-100 text-slate-800 border border-slate-200";
  if (p === "growth") return "bg-violet-100 text-violet-800 border border-violet-200";
  if (p === "pro") return "bg-amber-100 text-amber-900 border border-amber-300";
  return "bg-gray-100 text-gray-700 border border-gray-200";
}

function TableSkeletonRows() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <tr key={i} className="animate-pulse border-b border-[var(--border)]">
          <td className="py-3"><div className="h-4 w-24 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-16 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-8 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-28 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-12 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-16 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-14 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-16 rounded bg-gray-200" /></td>
          <td className="py-3"><div className="h-4 w-20 rounded bg-gray-200" /></td>
        </tr>
      ))}
    </>
  );
}

export default function BillingPage() {
  const [accessToken, setAccessToken] = useState<string | false | null>(null);

  useEffect(() => subscribeAccessToken(setAccessToken), []);

  const swrKey =
    typeof accessToken === "string" && accessToken.length > 0
      ? (["billing-status", accessToken] as const)
      : null;

  const {
    data: status,
    error: statusError,
    isLoading: statusLoading,
  } = useSWR(
    swrKey,
    ([, token]) => billingApi.status(token),
    { revalidateOnFocus: true }
  );

  const histKey =
    typeof accessToken === "string" && accessToken.length > 0
      ? (["billing-history", accessToken] as const)
      : null;

  const {
    data: history,
    error: histError,
    isLoading: histLoading,
  } = useSWR(histKey, ([, token]) => billingApi.history(token), {
    revalidateOnFocus: true,
  });

  function scrollBuyRuns() {
    document.getElementById("buy-runs")?.scrollIntoView({ behavior: "smooth" });
  }

  const banner = <BillingBanner status={status} loading={statusLoading} onBuyRuns={scrollBuyRuns} />;

  return (
    <div className="mx-auto max-w-7xl space-y-10 text-[var(--text-primary)]">
      {banner}

      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-[var(--border)] bg-white p-5 shadow-sm">
          <p className="text-sm font-medium text-[var(--text-secondary)]">Runs available</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums">
            {(status?.free_runs_remaining ?? 0) + (status?.runs_balance ?? 0)}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-white p-5 shadow-sm">
          <p className="text-sm font-medium text-[var(--text-secondary)]">Free runs left</p>
          <p
            className={`mt-2 text-3xl font-semibold tabular-nums ${
              (status?.free_runs_remaining ?? 0) === 0 ? "text-gray-400" : ""
            }`}
          >
            {status?.free_runs_remaining ?? 0}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-white p-5 shadow-sm">
          <p className="text-sm font-medium text-[var(--text-secondary)]">Total spent</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums">
            {formatInrPaise(status?.total_spent_paise ?? 0)}
          </p>
        </div>
      </section>

      {statusError && isApiError(statusError) && (
        <p className="text-sm text-red-600">
          Could not load billing status: {statusError.detail}
        </p>
      )}

      {status && status.runs_balance > 0 && (
        <section>
          <h2 className="text-lg font-semibold">Your run credits</h2>
          <div className="mt-3 overflow-x-auto rounded-xl border border-[var(--border)] bg-white shadow-sm">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-xs uppercase tracking-wide text-[var(--text-secondary)]">
                <tr>
                  <th className="px-4 py-3 font-medium">Plan</th>
                  <th className="px-4 py-3 font-medium">Purchased</th>
                  <th className="px-4 py-3 font-medium">Runs left</th>
                  <th className="px-4 py-3 font-medium">Expires on</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {status.credit_batches.map((b, idx) => {
                    const exp = b.expires_at ? new Date(b.expires_at) : null;
                    const now = Date.now();
                    const soonDate =
                      exp != null &&
                      !Number.isNaN(exp.getTime()) &&
                      exp.getTime() - now < 30 * 24 * 3600 * 1000 &&
                      exp.getTime() > now;
                    const st = (b.status || "").toLowerCase();
                    const expired = st === "expired";
                    const soon = st === "expiring soon";
                    return (
                      <tr key={`${b.purchased_at}-${idx}`} className="border-b border-[var(--border)]">
                        <td className="px-4 py-3 capitalize">{b.plan}</td>
                        <td className="px-4 py-3 text-[var(--text-secondary)]">
                          {fmtDateShort(b.purchased_at)}
                        </td>
                        <td className="px-4 py-3 tabular-nums">{b.runs_remaining}</td>
                        <td
                          className={`px-4 py-3 tabular-nums ${
                            soon || soonDate
                              ? "font-medium text-orange-600"
                              : expired
                                ? "text-gray-400"
                                : ""
                          }`}
                        >
                          {fmtDateShort(b.expires_at)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={
                              expired
                                ? "rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
                                : soon || soonDate
                                  ? "rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-800"
                                  : "rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800"
                            }
                          >
                            {expired ? "Expired" : soon || soonDate ? "Expiring soon" : "Active"}
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

      <section id="buy-runs">
        <h2 className="text-lg font-semibold">Buy more runs</h2>
        <p className="mt-1 max-w-3xl text-sm text-[var(--text-secondary)]">
          Bundles stack with their own 6-month expiry; we use oldest-expiring credits first (FIFO).
        </p>
        <div className="mt-6 grid gap-5 lg:grid-cols-4">
          <PlanCard
            title="Starter"
            price={`${formatInrWhole(299)} + GST`}
            perRun={`${formatInrWhole(299)} per run`}
            runsLabel="1 reconciliation run"
            anchor="Try it on one client"
            features={[
              "Full reconciliation",
              "Excel + PDF export",
              "Decision layer",
              "Carry over for 6 months",
            ]}
            cta="Buy 1 run"
            highlight={false}
          />
          <PlanCard
            title="Growth"
            price={`${formatInrWhole(1199)} + GST`}
            perRun={`${formatInrWhole(239)} per run`}
            runsLabel="5 reconciliation runs"
            anchor="Pays for itself after 5 clients — save ₹260 vs Starter"
            features={[
              "Everything in Starter",
              "Best for ~5 clients / month",
              "Most popular for growing firms",
            ]}
            cta="Buy 5 runs"
            highlight="growth"
            badge={{ text: "Most Popular", className: "bg-violet-600 text-white" }}
          />
          <PlanCard
            title="Pro"
            price={`${formatInrWhole(2699)} + GST`}
            perRun={`${formatInrWhole(225)} per run`}
            runsLabel="12 reconciliation runs"
            anchor="Best for active firms — save ₹888 vs Starter"
            features={[
              "Everything in Growth",
              "Best for active firms",
              "Lower cost per reconciliation",
            ]}
            cta="Buy 12 runs"
            highlight="pro"
            badge={{ text: "Best Value", className: "bg-amber-400 text-gray-900" }}
          />
          <div className="flex flex-col rounded-xl border border-[var(--border)] bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold">Enterprise</h3>
            <p className="mt-3 text-sm text-[var(--text-secondary)]">
              Custom runs and pricing for high-volume CA firms.
            </p>
            <ul className="mt-4 flex-1 space-y-2 text-sm text-[var(--text-secondary)]">
              <li>Unlimited runs (negotiated)</li>
              <li>SLA & onboarding support</li>
              <li>GST invoice with your firm GSTIN</li>
              <li>Dedicated account manager</li>
            </ul>
            <a
              href={`https://wa.me/${WA_NUMBER.replace(/\D/g, "")}`}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg px-4 py-2.5 text-sm font-semibold text-white"
              style={{ backgroundColor: "#25D366" }}
            >
              Talk to Omkar
            </a>
          </div>
        </div>
        <p className="mt-6 text-xs text-gray-500">
          All prices exclude GST. 18% GST applicable. Runs carry over for 6 months from purchase
          date.
        </p>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Payment history</h2>
        <div className="overflow-x-auto rounded-xl border border-[var(--border)] bg-white shadow-sm">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              <tr>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Plan</th>
                <th className="px-4 py-3 font-medium">Runs</th>
                <th className="px-4 py-3 font-medium">Client</th>
                <th className="px-4 py-3 font-medium">Period</th>
                <th className="px-4 py-3 font-medium">Base</th>
                <th className="px-4 py-3 font-medium">GST</th>
                <th className="px-4 py-3 font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Receipt</th>
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
              {!histLoading &&
                history &&
                history.length === 0 && (
                  <tr>
                    <td colSpan={10} className="px-4 py-8 text-center text-[var(--text-secondary)]">
                      Your first 2 reconciliations are free — no payment needed yet. Your receipts
                      will appear here after your first purchase.
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
  onBuyRuns,
}: {
  status: BillingStatus | undefined;
  loading: boolean;
  onBuyRuns: () => void;
}) {
  if (loading && !status) {
    return <div className="h-14 animate-pulse rounded-lg bg-gray-200" aria-hidden />;
  }
  if (!status) return null;

  const free = status.free_runs_remaining;
  const bal = status.runs_balance;
  const runsWord = (n: number) => (n === 1 ? "run" : "runs");

  const expiringRuns = (status.expiring_soon ?? []).reduce(
    (a, b) => a + (b.runs_remaining ?? 0),
    0
  );
  const exp0 = status.expiring_soon?.[0]?.expires_at;
  const expiringDate = exp0 ? fmtDateShort(exp0) : null;

  if (free > 0) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        You have {free} free reconciliation{free === 1 ? "" : "s"} remaining — no payment needed.
      </div>
    );
  }

  if (bal > 0) {
    return (
      <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
        <p>
          You have {bal} {runsWord(bal)} remaining.
        </p>
        {expiringRuns > 0 && expiringDate && (
          <p className="mt-2 font-medium text-orange-600">
            {expiringRuns} {runsWord(expiringRuns)} expiring on {expiringDate} — use them before they
            expire.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-950">
      <span>No runs remaining — purchase a plan to continue reconciling.</span>
      <button
        type="button"
        onClick={onBuyRuns}
        className="rounded-lg bg-orange-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-orange-700"
      >
        Buy runs
      </button>
    </div>
  );
}

function PlanCard(props: {
  title: string;
  price: string;
  perRun: string;
  runsLabel: string;
  anchor: string;
  features: string[];
  cta: string;
  highlight: false | "growth" | "pro";
  badge?: { text: string; className: string };
}) {
  const {
    title,
    price,
    perRun,
    runsLabel,
    anchor,
    features,
    cta,
    highlight,
    badge,
  } = props;
  const border =
    highlight === "growth"
      ? "border-violet-400 shadow-md ring-1 ring-violet-200"
      : highlight === "pro"
        ? "border-amber-400 shadow-sm ring-1 ring-amber-100"
        : "border-[var(--border)] shadow-sm";
  return (
    <div
      className={`relative flex flex-col rounded-xl border bg-white p-6 ${border}`}
    >
      {badge && (
        <span
          className={`absolute -top-3 right-4 rounded-full px-3 py-0.5 text-xs font-semibold ${badge.className}`}
        >
          {badge.text}
        </span>
      )}
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-2xl font-bold tracking-tight">{price}</p>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">{perRun}</p>
      <p className="mt-2 text-sm text-[var(--text-secondary)]">{runsLabel}</p>
      <p className="mt-2 text-xs text-gray-600">{anchor}</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm text-[var(--text-secondary)]">
        {features.map((f) => (
          <li key={f}>• {f}</li>
        ))}
      </ul>
      <button
        type="button"
        disabled
        className="mt-6 w-full cursor-not-allowed rounded-lg border border-gray-200 bg-gray-100 px-4 py-2.5 text-sm font-semibold text-gray-500"
      >
        {cta} — Coming soon
      </button>
    </div>
  );
}

function HistoryRow({ row, token }: { row: PaymentHistoryRow; token: string }) {
  const st = (row.status || "").toUpperCase();
  const stClass =
    st === "PAID"
      ? "bg-emerald-100 text-emerald-800"
      : st === "FAILED"
        ? "bg-red-100 text-red-800"
        : "bg-gray-100 text-gray-700";

  async function onReceipt() {
    if (!token) return;
    try {
      await openPaymentReceipt(token, row.payment_id);
    } catch {
      // Toast could be added via provider if needed
      window.alert("Could not download receipt.");
    }
  }

  return (
    <tr className="border-b border-[var(--border)]">
      <td className="px-4 py-3 whitespace-nowrap">{fmtDateShort(row.created_at)}</td>
      <td className="px-4 py-3">
        <span
          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${planBadgeClass(row.plan)}`}
        >
          {row.plan || "—"}
        </span>
      </td>
      <td className="px-4 py-3 tabular-nums">{row.runs_purchased ?? "—"}</td>
      <td className="px-4 py-3">{row.trade_name?.trim() || "—"}</td>
      <td className="px-4 py-3 whitespace-nowrap">{row.period || "—"}</td>
      <td className="px-4 py-3 tabular-nums">{formatInrPaise(row.base_amount_paise)}</td>
      <td className="px-4 py-3 tabular-nums">{formatInrPaise(row.gst_paise)}</td>
      <td className="px-4 py-3 font-medium tabular-nums">
        {formatInrPaise(row.total_amount_paise)}
      </td>
      <td className="px-4 py-3">
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${stClass}`}>
          {st}
        </span>
      </td>
      <td className="px-4 py-3">
        {st === "PAID" ? (
          <button
            type="button"
            onClick={() => void onReceipt()}
            className="text-sm font-semibold text-violet-600 hover:underline"
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
