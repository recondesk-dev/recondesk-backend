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
  const [billingTier, setBillingTier] = useState<"solo" | "firm">("solo");

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
          Monthly Solo and Firm plans; checkout opens soon. Carryover rules are noted on each card.
        </p>

        <div className="mx-auto mt-8 flex w-full max-w-md justify-center lg:max-w-none">
          <div
            className="relative inline-flex w-full rounded-full border border-[var(--border)] bg-gray-100 p-1 shadow-inner sm:w-auto"
            role="tablist"
            aria-label="Plan type"
          >
            <span
              className="pointer-events-none absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-full bg-violet-600 shadow-md shadow-violet-600/25 transition-transform duration-300 ease-out"
              style={{
                transform: billingTier === "solo" ? "translateX(0)" : "translateX(100%)",
              }}
              aria-hidden
            />
            <button
              id="billing-tab-solo"
              type="button"
              role="tab"
              aria-selected={billingTier === "solo"}
              aria-controls="billing-plans-panel"
              className={`relative z-10 min-h-[44px] flex-1 rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-300 ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-600 sm:flex-none sm:px-8 ${
                billingTier === "solo" ? "text-white" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
              onClick={() => setBillingTier("solo")}
            >
              Solo CA
            </button>
            <button
              id="billing-tab-firm"
              type="button"
              role="tab"
              aria-selected={billingTier === "firm"}
              aria-controls="billing-plans-panel"
              className={`relative z-10 min-h-[44px] flex-1 rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-300 ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-600 sm:flex-none sm:px-8 ${
                billingTier === "firm" ? "text-white" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
              onClick={() => setBillingTier("firm")}
            >
              CA Firm
            </button>
          </div>
        </div>

        <div
          id="billing-plans-panel"
          role="tabpanel"
          aria-labelledby={billingTier === "solo" ? "billing-tab-solo" : "billing-tab-firm"}
          className="mt-6"
        >
          {billingTier === "solo" ? (
            <div key="solo" className="pricing-tier-enter grid gap-5 lg:grid-cols-4">
              <PlanCard
                title="Starter"
                price={`${formatInrWhole(399)} + GST`}
                features={[
                  "1 run/month",
                  "₹399/run",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Buy 1 run"
                highlight={false}
              />
              <PlanCard
                title="Growth"
                price={`${formatInrWhole(1699)} + GST`}
                features={[
                  "5 runs/month",
                  "₹339/run — save 15%",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Buy 5 runs"
                highlight="growth"
                badge={{ text: "Most Popular", className: "bg-violet-600 text-white" }}
              />
              <PlanCard
                title="Pro"
                price={`${formatInrWhole(3499)} + GST`}
                features={[
                  "12 runs/month",
                  "₹291/run — save 27%",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Buy 12 runs"
                highlight="pro"
                badge={{ text: "Best Value", className: "bg-amber-400 text-gray-900" }}
              />
              <EnterpriseSoloCard />
            </div>
          ) : (
            <div key="firm" className="pricing-tier-enter grid gap-5 lg:grid-cols-4">
              <PlanCard
                title="Starter Firm"
                price={`${formatInrWhole(9999)} + GST`}
                features={[
                  "35 runs/month",
                  "₹285/run — save 29%",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Coming soon"
                ctaExact
                highlight={false}
              />
              <PlanCard
                title="Growth Firm"
                price={`${formatInrWhole(13999)} + GST`}
                features={[
                  "50 runs/month",
                  "₹279/run — save 30%",
                  "Unused runs carry over for up to 2 months",
                ]}
                cta="Coming soon"
                ctaExact
                highlight="growth"
                badge={{ text: "Most Popular", className: "bg-violet-600 text-white" }}
              />
              <PlanCard
                title="Pro Firm"
                price={`${formatInrWhole(25999)} + GST`}
                features={[
                  "100 runs/month",
                  "₹259/run — save 35%",
                  "Unused runs carry over for up to 2 months",
                ]}
                cta="Coming soon"
                ctaExact
                highlight="pro"
                badge={{ text: "Best Value", className: "bg-amber-400 text-gray-900" }}
              />
              <EnterpriseFirmCard />
            </div>
          )}
        </div>

        <p className="mt-6 text-xs text-gray-500">
          All prices exclude GST. 18% GST applicable.
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

function EnterpriseSoloCard() {
  return (
    <div className="flex flex-col rounded-xl border border-[var(--border)] bg-white p-6 shadow-sm">
      <h3 className="text-lg font-semibold">Enterprise</h3>
      <p className="mt-2 text-2xl font-bold tracking-tight text-[var(--text-primary)]">Custom pricing</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm text-[var(--text-secondary)]">
        <li>• 100+ runs/month</li>
        <li>• Unlimited runs (negotiated)</li>
        <li>• SLA & onboarding support</li>
        <li>• GST invoice with your firm GSTIN</li>
        <li>• Dedicated account manager</li>
      </ul>
      <a
        href="mailto:contact@recondesk.in"
        className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-700"
      >
        Contact Sales
      </a>
    </div>
  );
}

function EnterpriseFirmCard() {
  return (
    <div className="flex flex-col rounded-xl border border-[var(--border)] bg-white p-6 shadow-sm">
      <h3 className="text-lg font-semibold">Enterprise</h3>
      <p className="mt-2 text-2xl font-bold tracking-tight text-[var(--text-primary)]">Custom pricing</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm text-[var(--text-secondary)]">
        <li>• 100+ runs/month</li>
        <li>• Dedicated support</li>
        <li>• Custom onboarding</li>
        <li>• SLA guarantee</li>
      </ul>
      <a
        href="mailto:contact@recondesk.in"
        className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-700"
      >
        Contact Sales
      </a>
    </div>
  );
}

function PlanCard(props: {
  title: string;
  price: string;
  features: string[];
  cta: string;
  highlight: false | "growth" | "pro";
  badge?: { text: string; className: string };
  /** When true, button label is exactly `cta` (e.g. &quot;Coming soon&quot;). Otherwise appends &quot; — Coming soon&quot;. */
  ctaExact?: boolean;
}) {
  const { title, price, features, cta, highlight, badge, ctaExact } = props;
  const border =
    highlight === "growth"
      ? "border-violet-400 shadow-md ring-1 ring-violet-200"
      : highlight === "pro"
        ? "border-amber-400 shadow-sm ring-1 ring-amber-100"
        : "border-[var(--border)] shadow-sm";
  const buttonLabel = ctaExact ? cta : `${cta} — Coming soon`;

  return (
    <div className={`relative flex flex-col rounded-xl border bg-white p-6 ${border}`}>
      {badge && (
        <span
          className={`absolute -top-3 right-4 rounded-full px-3 py-0.5 text-xs font-semibold ${badge.className}`}
        >
          {badge.text}
        </span>
      )}
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-2xl font-bold tracking-tight">{price}</p>
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
        {buttonLabel}
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
