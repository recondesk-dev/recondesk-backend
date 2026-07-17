"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";

import { RiskScoreBadge } from "@/components/vendors/RiskScoreBadge";
import {
  isApiError,
  vendorsApi,
  type VendorScorecardRow,
} from "@/lib/api";
import { paiseToRupee } from "@/lib/dashboard-portfolio";
import { formatINR } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function formatPct(rate: number): string {
  const n = Number(rate);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toLocaleString("en-IN", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 0,
  })}%`;
}

function DetailSkeleton() {
  return (
    <div className="space-y-4">
      <div className="dashboard-card animate-pulse space-y-3 p-6">
        <div className="h-5 w-48 rounded-full bg-gray-100" />
        <div className="h-4 w-64 rounded-full bg-gray-100" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 rounded-2xl bg-gray-100" />
          ))}
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  note,
}: {
  label: string;
  value: string;
  sub?: string;
  note?: string;
}) {
  return (
    <div className="rounded-2xl bg-[#F7F7F8] px-4 py-3.5">
      <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
        {label}
      </p>
      <p className="mt-1.5 text-xl font-semibold tabular-nums tracking-tight text-[var(--ink)]">
        {value}
      </p>
      {sub ? (
        <p className="mt-0.5 text-xs tabular-nums text-gray-500">{sub}</p>
      ) : null}
      {note ? (
        <p className="mt-2 text-[12px] leading-snug text-gray-500">{note}</p>
      ) : null}
    </div>
  );
}

function noteFor(
  notes: Record<string, string> | undefined,
  key: string,
  fallback: string
): string {
  const n = notes?.[key]?.trim();
  return n || fallback;
}

function metricsFromSupplier(s: VendorScorecardRow) {
  const atRisk = paiseToRupee(s.rule37_at_risk_paise);
  return {
    atRiskLabel: atRisk != null ? formatINR(atRisk) : "—",
    mismatchPct: formatPct(s.mismatch_rate),
    latePct: formatPct(s.late_filing_rate),
  };
}

export default function VendorDetailPage() {
  const params = useParams();
  const rawGstin = String(params?.supplier_gstin || "");
  const supplierGstin = decodeURIComponent(rawGstin).trim().toUpperCase();

  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0
      ? tokenState
      : null;

  const key =
    authToken && supplierGstin
      ? (["vendor-scorecard-detail", authToken, supplierGstin] as const)
      : null;

  const { data, error, isLoading, mutate } = useSWR(
    key,
    ([, token, gstin]) => vendorsApi.scorecardDetail(token, gstin),
    { revalidateOnFocus: false }
  );

  const resolvingToken = tokenState === null;
  const showSkeleton =
    resolvingToken || (!!authToken && isLoading && !data);

  const notFound =
    error && isApiError(error) && (error.status === 404 || error.status === 422);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/vendors"
          className="text-sm font-medium text-gray-500 transition-colors hover:text-[var(--ink)]"
        >
          ← Vendors
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
            {data?.supplier.supplier_trade_name?.trim() ||
              supplierGstin ||
              "Vendor"}
          </h1>
          {data ? <RiskScoreBadge score={data.supplier.risk_score} /> : null}
        </div>
        <p className="mt-1 font-mono text-sm text-gray-500">
          {data?.supplier.supplier_gstin || supplierGstin}
        </p>
      </div>

      {!authToken && tokenState === false && (
        <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
          Sign in to view this vendor.
        </div>
      )}

      {error && !notFound && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load vendor detail.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--ink)] underline"
            onClick={() => void mutate()}
          >
            Retry
          </button>
        </div>
      )}

      {notFound && (
        <div className="dashboard-card px-6 py-10 text-center">
          <h3 className="text-lg font-semibold text-[var(--ink)]">
            Vendor not found
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            This supplier is not in your firm scorecard, or the GSTIN is
            invalid.
          </p>
          <Link
            href="/vendors"
            className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          >
            Back to Vendors
          </Link>
        </div>
      )}

      {showSkeleton ? <DetailSkeleton /> : null}

      {data && !error ? (
        <>
          <section className="dashboard-card space-y-5 p-6">
            <div>
              <h2 className="text-sm font-semibold text-[var(--ink)]">
                Compliance summary
              </h2>
              <p className="mt-0.5 text-xs text-gray-500">
                Aggregated across clients that transact with this supplier
              </p>
            </div>
            {(() => {
              const s = data.supplier;
              const m = metricsFromSupplier(s);
              const notes = data.signal_notes;
              return (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <MetricCard
                    label="Clients touched"
                    value={s.clients_touched_count.toLocaleString("en-IN")}
                    sub={`${s.total_invoices.toLocaleString("en-IN")} invoices`}
                  />
                  <MetricCard
                    label="Mismatch rate"
                    value={m.mismatchPct}
                    sub={`${s.mismatch_invoice_count.toLocaleString("en-IN")} mismatched`}
                  />
                  <MetricCard
                    label="Rule 37 open"
                    value={s.rule37_open_count.toLocaleString("en-IN")}
                    sub={`At risk ${m.atRiskLabel}`}
                  />
                  <MetricCard
                    label="Section 17(5)"
                    value={s.section_17_5_count.toLocaleString("en-IN")}
                  />
                  <MetricCard
                    label="Late filing rate"
                    value={m.latePct}
                    sub={`${s.late_filing_count.toLocaleString("en-IN")} late-filed`}
                    note={noteFor(
                      notes,
                      "late_filing_rate",
                      "Share of invoices flagged via supplier GSTR-1 filing date (supfildt) after the due date."
                    )}
                  />
                  <MetricCard
                    label="Not in 2B (PR only)"
                    value={s.pr_only_count.toLocaleString("en-IN")}
                    note={noteFor(
                      notes,
                      "pr_only_count",
                      "Invoices in books but not in GSTR-2B (PR_ONLY). Not a non-filer determination."
                    )}
                  />
                  <MetricCard
                    label="Quarterly filer"
                    value={s.quarterly_filer_flag ? "Yes" : "No"}
                    note={noteFor(
                      notes,
                      "quarterly_filer_flag",
                      "Supplier marked quarterly filer on at least one GSTR-2B invoice (QUARTERLY_FILER risk)."
                    )}
                  />
                  <MetricCard
                    label="Risk score"
                    value={String(s.risk_score)}
                    sub="0–100 composite"
                  />
                </div>
              );
            })()}

            {data.signal_notes?.non_filer ? (
              <p className="rounded-2xl bg-[#F7F7F8] px-4 py-3 text-[12px] leading-relaxed text-gray-600">
                {data.signal_notes.non_filer}
              </p>
            ) : (
              <p className="rounded-2xl bg-[#F7F7F8] px-4 py-3 text-[12px] leading-relaxed text-gray-600">
                No non-filer / Rule 37A signal is computed. Use PR_ONLY,
                QUARTERLY_FILER, and late filing proxies only.
              </p>
            )}
          </section>

          <section className="dashboard-card space-y-4 p-6">
            <div>
              <h2 className="text-sm font-semibold text-[var(--ink)]">
                Clients touched
              </h2>
              <p className="mt-0.5 text-xs text-gray-500">
                Your firm&apos;s clients that have invoices with this supplier
              </p>
            </div>
            {data.clients.length === 0 ? (
              <p className="text-sm text-gray-500">No client links available.</p>
            ) : (
              <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
                <table className="w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                      <th className="px-5 py-4">Client</th>
                      <th className="px-5 py-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.clients.map((c) => (
                      <tr
                        key={c.client_gstin_id}
                        className="border-b border-[#F0F0F0] transition-colors hover:bg-[#F7F7F8] last:border-b-0"
                      >
                        <td className="px-5 py-3.5">
                          <div className="font-medium text-[var(--ink)]">
                            {c.trade_name?.trim() || "—"}
                          </div>
                          <div className="mt-0.5 font-mono text-xs text-gray-400">
                            {c.gstin || "—"}
                          </div>
                        </td>
                        <td className="px-5 py-3.5 text-right">
                          <Link
                            href={`/clients/${c.client_gstin_id}`}
                            className="inline-flex min-h-[36px] items-center justify-center rounded-full bg-[#F5F5F6] px-4 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-200/70"
                          >
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
