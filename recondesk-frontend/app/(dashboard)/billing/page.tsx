"use client";

import useSWR from "swr";
import { useEffect, useState } from "react";
import Script from "next/script";
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
  if (p === "starter") return "bg-[#F0F0F0] text-gray-700";
  if (p === "growth") return "bg-[var(--ink)] text-white";
  if (p === "pro") return "bg-[#F0F0F0] text-[var(--ink)] ring-1 ring-black/10";
  if (p === "scale") return "bg-[var(--ink)] text-white";
  return "bg-[#F0F0F0] text-gray-700";
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
  const [isProcessing, setIsProcessing] = useState(false);

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

  async function handleBuyPlan(planName: string) {
    setIsProcessing(true);
    try {
      const createRes = await fetch("/api/billing/create-order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_name: planName }),
      });
      
      const createData = await createRes.json();
      if (!createRes.ok) {
        throw new Error(createData.error || "Failed to create order");
      }

      const options = {
        key: process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID,
        amount: createData.amount,
        currency: createData.currency,
        order_id: createData.order_id,
        name: "ReconDesk",
        description: `Purchase ${planName} plan`,
        handler: async function (response: any) {
          console.log("[Razorpay] Handler fired! Received response:", response);
          try {
            console.log("[Razorpay] Sending verify-payment request...");
            const verifyRes = await fetch("/api/billing/verify-payment", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
              }),
            });
            console.log("[Razorpay] verify-payment response status:", verifyRes.status);
            const verifyData = await verifyRes.json();
            console.log("[Razorpay] verify-payment response data:", verifyData);

            if (!verifyRes.ok) {
              throw new Error(verifyData.error || "Payment verification failed");
            }
            alert("Payment successful! Runs have been credited to your account.");
            // Refresh data
            window.location.reload();
          } catch (err: any) {
            console.error("[Razorpay] verify-payment caught error:", err);
            alert(err.message || "Payment verification failed");
          } finally {
            console.log("[Razorpay] Handler finished processing.");
            setIsProcessing(false);
          }
        },
        modal: {
          ondismiss: function () {
            console.log("[Razorpay] modal.ondismiss fired!");
            setIsProcessing(false);
          },
        },
        theme: {
          color: "#7C3AED",
        },
      };

      const rzp = new (window as any).Razorpay(options);
      rzp.on("payment.failed", function (response: any) {
        alert(`Payment failed: ${response.error.description}`);
        setIsProcessing(false);
      });
      rzp.open();
    } catch (err: any) {
      alert(err.message || "An error occurred");
      setIsProcessing(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8 text-[var(--text-primary)]">
      <Script src="https://checkout.razorpay.com/v1/checkout.js" strategy="lazyOnload" />
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">Billing</h1>
        <p className="mt-1 text-sm text-gray-500">
          Credits, plans, and payment history for your workspace
        </p>
      </div>
      {banner}

      <section className="grid gap-3 md:grid-cols-3">
        <div className="dashboard-card p-5">
          <p className="text-sm font-medium text-gray-500">Runs available</p>
          <p className="mt-2 text-[1.85rem] font-semibold tracking-tight tabular-nums text-[var(--ink)]">
            {(status?.free_runs_remaining ?? 0) + (status?.runs_balance ?? 0)}
          </p>
        </div>
        <div className="dashboard-card p-5">
          <p className="text-sm font-medium text-gray-500">Free runs left</p>
          <p
            className={`mt-2 text-[1.85rem] font-semibold tracking-tight tabular-nums ${
              (status?.free_runs_remaining ?? 0) === 0 ? "text-gray-300" : "text-[var(--ink)]"
            }`}
          >
            {status?.free_runs_remaining ?? 0}
          </p>
        </div>
        <div className="dashboard-card p-5">
          <p className="text-sm font-medium text-gray-500">Total spent</p>
          <p className="mt-2 text-[1.85rem] font-semibold tracking-tight tabular-nums text-[var(--ink)]">
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
        <section className="dashboard-card space-y-4 p-6">
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            Your run credits
          </h2>
          <div className="overflow-x-auto rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                <tr>
                  <th className="px-5 py-4 font-medium">Plan</th>
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
                    // Single source of truth: client-side 7-day window computed from expires_at.
                    // Do NOT use b.status ("expiring soon" string) — it may be stale from a
                    // cached API response made before the 30→7 day threshold fix was deployed.
                    const useSoon =
                      exp != null &&
                      !Number.isNaN(exp.getTime()) &&
                      exp.getTime() - now < 7 * 24 * 3600 * 1000 &&
                      exp.getTime() > now;
                    const expired =
                      exp != null &&
                      !Number.isNaN(exp.getTime()) &&
                      exp.getTime() <= now;
                    return (
                      <tr key={`${b.purchased_at}-${idx}`} className="border-b border-[#F0F0F0] last:border-b-0">
                        <td className="px-5 py-3.5 capitalize font-medium text-[var(--ink)]">{b.plan}</td>
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

      <section id="buy-runs" className="dashboard-card space-y-6 p-6">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">Buy more runs</h2>
          <p className="mt-1 max-w-3xl text-sm text-gray-500">
            Monthly Solo and Firm plans. Carryover rules are noted on each card.
          </p>
        </div>

        <div className="mx-auto flex w-full max-w-md justify-center lg:max-w-none">
          <div
            className="relative inline-flex w-full rounded-full bg-[#F5F5F6] p-1 sm:w-auto"
            role="tablist"
            aria-label="Plan type"
          >
            <span
              className="pointer-events-none absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-full bg-[var(--ink)] shadow-sm transition-transform duration-300 ease-out"
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
              className={`relative z-10 min-h-[44px] flex-1 rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-300 ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black sm:flex-none sm:px-8 ${
                billingTier === "solo" ? "text-white" : "text-gray-500 hover:text-[var(--ink)]"
              }`}
              onClick={() => setBillingTier("solo")}
            >
              Individual
            </button>
            <button
              id="billing-tab-firm"
              type="button"
              role="tab"
              aria-selected={billingTier === "firm"}
              aria-controls="billing-plans-panel"
              className={`relative z-10 min-h-[44px] flex-1 rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-300 ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black sm:flex-none sm:px-8 ${
                billingTier === "firm" ? "text-white" : "text-gray-500 hover:text-[var(--ink)]"
              }`}
              onClick={() => setBillingTier("firm")}
            >
              Enterprise
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
                price={`${formatInrWhole(499)} + GST`}
                features={[
                  "1 run/month",
                  "₹499/run",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Buy 1 run"
                highlight={false}
                onBuy={() => handleBuyPlan("starter")}
                isProcessing={isProcessing}
              />
              <PlanCard
                title="Growth"
                price={`${formatInrWhole(1699)} + GST`}
                features={[
                  "5 runs/month",
                  "₹340/run",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Buy 5 runs"
                highlight="growth"
                badge={{ text: "Most Popular", className: "bg-[var(--ink)] text-white" }}
                onBuy={() => handleBuyPlan("growth")}
                isProcessing={isProcessing}
              />
              <PlanCard
                title="Pro"
                price={`${formatInrWhole(3699)} + GST`}
                features={[
                  "12 runs/month",
                  "₹308/run",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Buy 12 runs"
                highlight="pro"
                badge={{ text: "Best Value", className: "bg-[#F0F0F0] text-[var(--ink)]" }}
                onBuy={() => handleBuyPlan("pro")}
                isProcessing={isProcessing}
              />
              <PlanCard
                title="Scale"
                price={`${formatInrWhole(5699)} + GST`}
                features={[
                  "30 runs/month",
                  "₹190/run",
                  "Runs expire monthly — no carry over",
                ]}
                cta="Buy 30 runs"
                highlight="scale"
                badge={{ text: "Founder's Offer", className: "bg-[var(--ink)] text-white" }}
                onBuy={() => handleBuyPlan("scale")}
                isProcessing={isProcessing}
              />
              <EnterpriseSoloCard />
            </div>
          ) : (
            <div key="firm" className="pricing-tier-enter grid gap-5 lg:grid-cols-3">
              <PlanCard
                title="Growth Firm"
                price={`${formatInrWhole(8699)} + GST`}
                features={[
                  "50 runs/month",
                  "₹174/run",
                  "Unused runs carry over for up to 2 months",
                ]}
                cta="Coming soon"
                ctaExact
                highlight="growth"
                badge={{ text: "Most Popular", className: "bg-[var(--ink)] text-white" }}
              />
              <PlanCard
                title="Scale Firm"
                price={`${formatInrWhole(14699)} + GST`}
                features={[
                  "100 runs/month",
                  "₹147/run",
                  "Unused runs carry over for up to 2 months",
                ]}
                cta="Coming soon"
                ctaExact
                highlight="scale"
                badge={{ text: "Best Value", className: "bg-[#F0F0F0] text-[var(--ink)]" }}
              />
              <EnterpriseFirmCard />
            </div>
          )}
        </div>

        <p className="text-xs text-gray-500">
          All prices exclude GST. 18% GST applicable.
        </p>
      </section>

      <section className="dashboard-card space-y-4 p-6">
        <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">Payment history</h2>
        <div className="overflow-x-auto rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
              <tr>
                <th className="px-5 py-4 font-medium">Date</th>
                <th className="px-4 py-4 font-medium">Plan</th>
                <th className="px-4 py-4 font-medium">Runs</th>
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
              {!histLoading &&
                history &&
                history.length === 0 && (
                  <tr>
                    <td colSpan={10} className="px-4 py-8 text-center text-[var(--text-secondary)]">
                      {(status?.runs_balance ?? 0) > 0 ||
                      (status?.total_spent_paise ?? 0) > 0 ||
                      (status?.credit_batches?.length ?? 0) > 0
                        ? "No payment history available."
                        : "Your first 2 reconciliations are free — no payment needed yet. Your receipts will appear here after your first purchase."}
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
    return <div className="h-14 animate-pulse rounded-[1.25rem] bg-white/70" aria-hidden />;
  }
  if (!status) return null;

  const free = status.free_runs_remaining;
  const bal = status.runs_balance;
  const runsWord = (n: number) => (n === 1 ? "run" : "runs");

  if (free > 0) {
    return (
      <div className="rounded-[1.25rem] bg-[var(--ink)] px-5 py-4 text-sm text-white">
        You have {free} free reconciliation{free === 1 ? "" : "s"} remaining — no payment needed.
      </div>
    );
  }

  if (bal > 0) {
    return (
      <div className="dashboard-card px-5 py-4 text-sm text-gray-700">
        <p>
          You have <strong className="text-[var(--ink)]">{bal}</strong> {runsWord(bal)} remaining.
        </p>
        {status.expiring_soon && status.expiring_soon.length > 0 && (
          <div className="mt-2 space-y-1">
            {status.expiring_soon.map((b, idx) => {
              const rem = b.runs_remaining ?? 0;
              if (rem <= 0) return null;
              const planName = b.plan ? b.plan.charAt(0).toUpperCase() + b.plan.slice(1) : "Starter";
              const dateStr = b.expires_at ? fmtDateShort(b.expires_at) : "";
              const verb = rem === 1 ? "expires" : "expire";
              const pronoun = rem === 1 ? "it" : "them";
              return (
                <p key={idx} className="font-medium text-orange-600">
                  Note: {rem} of your {bal} {runsWord(bal)} (from the {planName} pack) {verb} on {dateStr} — use {pronoun} before then.
                </p>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-[1.25rem] bg-orange-50 px-5 py-4 text-sm text-orange-950">
      <span>No runs remaining — purchase a plan to continue reconciling.</span>
      <button
        type="button"
        onClick={onBuyRuns}
        className="rounded-full bg-[var(--ink)] px-3.5 py-1.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
      >
        Buy runs
      </button>
    </div>
  );
}

function EnterpriseSoloCard() {
  return (
    <div className="flex flex-col rounded-[1.5rem] bg-[#F7F7F8] p-6 transition duration-200 hover:-translate-y-0.5">
      <h3 className="text-lg font-semibold text-[var(--ink)]">Individual</h3>
      <p className="mt-2 text-2xl font-bold tracking-tight text-[var(--ink)]">Custom pricing</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm text-gray-500">
        <li>• Dedicated support</li>
        <li>• Custom onboarding</li>
        <li>• SLA guarantee</li>
      </ul>
      <p className="mt-6 text-lg font-semibold text-[var(--ink)]">Need More?</p>
      <a
        href="mailto:contact@recondesk.in"
        className="mt-6 inline-flex w-full items-center justify-center rounded-full bg-[var(--ink)] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
      >
        Contact Sales
      </a>
    </div>
  );
}

function EnterpriseFirmCard() {
  return (
    <div className="flex flex-col rounded-[1.5rem] bg-[#F7F7F8] p-6 transition duration-200 hover:-translate-y-0.5">
      <h3 className="text-lg font-semibold text-[var(--ink)]">Enterprise</h3>
      <p className="mt-2 text-2xl font-bold tracking-tight text-[var(--ink)]">Custom pricing</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm text-gray-500">
        <li>• 100+ runs/month</li>
        <li>• Dedicated support</li>
        <li>• Custom onboarding</li>
        <li>• SLA guarantee</li>
      </ul>
      <a
        href="mailto:contact@recondesk.in"
        className="mt-6 inline-flex w-full items-center justify-center rounded-full bg-[var(--ink)] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
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
  highlight: false | "growth" | "pro" | "scale";
  badge?: { text: string; className: string };
  /** When true, button label is exactly `cta` (e.g. "Coming soon"). Otherwise appends " — Coming soon". */
  ctaExact?: boolean;
  onBuy?: () => void;
  isProcessing?: boolean;
}) {
  const { title, price, features, cta, highlight, badge, ctaExact, onBuy, isProcessing } = props;
  const emphasized = highlight === "growth" || highlight === "scale";
  const buttonLabel = onBuy ? cta : (ctaExact ? cta : `${cta} — Coming soon`);

  return (
    <div
      className={`relative z-10 flex flex-col rounded-[1.5rem] p-6 transition duration-200 hover:-translate-y-0.5 ${
        emphasized
          ? "bg-[var(--ink)] text-white shadow-[var(--shadow-lift)]"
          : "bg-[#F7F7F8] text-[var(--ink)]"
      }`}
    >
      {badge && (
        <span
          className={`absolute -top-3 right-4 rounded-full px-3 py-0.5 text-xs font-semibold ${
            emphasized ? "bg-white text-[var(--ink)]" : badge.className
          }`}
        >
          {badge.text}
        </span>
      )}
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-2xl font-bold tracking-tight">{price}</p>
      <ul className={`mt-4 flex-1 space-y-2 text-sm ${emphasized ? "text-white/70" : "text-gray-500"}`}>
        {features.map((f) => (
          <li key={f}>• {f}</li>
        ))}
      </ul>
      <button
        type="button"
        disabled={!onBuy || isProcessing}
        onClick={onBuy}
        className={`mt-6 w-full rounded-full px-4 py-2.5 text-sm font-semibold transition-opacity ${
          onBuy
            ? emphasized
              ? "bg-white text-[var(--ink)] hover:opacity-90"
              : "bg-[var(--ink)] text-white hover:opacity-90"
            : "cursor-not-allowed bg-white/50 text-gray-400"
        } ${isProcessing ? "opacity-75 cursor-wait" : ""}`}
      >
        {isProcessing && onBuy ? "Processing..." : buttonLabel}
      </button>
    </div>
  );
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
      // Toast could be added via provider if needed
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
      <td className="px-4 py-3.5 tabular-nums">{row.runs_purchased ?? "—"}</td>
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
