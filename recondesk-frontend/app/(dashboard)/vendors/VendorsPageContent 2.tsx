"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";

import { ReconcilePaginationFooter } from "@/components/reconcile/ReconcilePaginationFooter";
import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import { RiskScoreBadge } from "@/components/vendors/RiskScoreBadge";
import {
  vendorsApi,
  type VendorScorecardRow,
  type VendorScorecardSort,
} from "@/lib/api";
import { paiseToRupee } from "@/lib/dashboard-portfolio";
import { formatINR } from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const PAGE_SIZE = 50;

function useDebounced<T>(value: T, ms: number): T {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return d;
}

function VendorsSkeleton() {
  return (
    <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-[#F0F0F0] px-5 py-4 last:border-b-0"
          >
            <div className="h-4 flex-1 rounded bg-gray-100" />
            <div className="h-4 w-16 rounded bg-gray-100" />
            <div className="h-4 w-12 rounded bg-gray-100" />
            <div className="h-4 w-16 rounded bg-gray-100" />
            <div className="h-4 w-28 rounded bg-gray-100" />
          </div>
        ))}
      </div>
    </div>
  );
}

function formatPct(rate: number): string {
  const n = Number(rate);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toLocaleString("en-IN", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 0,
  })}%`;
}

type SortKey = VendorScorecardSort;

function SortHeader({
  label,
  sortKey,
  current,
  order,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  order: "asc" | "desc";
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = current === sortKey;
  return (
    <th className={`py-4 ${className || "px-4"}`}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 uppercase tracking-widest transition-colors ${
          active ? "text-[var(--ink)]" : "text-gray-400 hover:text-gray-600"
        }`}
      >
        {label}
        {active ? (
          <span className="text-[10px] font-semibold" aria-hidden>
            {order === "desc" ? "↓" : "↑"}
          </span>
        ) : null}
      </button>
    </th>
  );
}

export function VendorsPageContent() {
  const router = useRouter();
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0
      ? tokenState
      : null;

  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortKey>("risk_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [q, setQ] = useState("");
  const debouncedQ = useDebounced(q, 250);

  useEffect(() => {
    setPage(1);
  }, [debouncedQ, sort, order]);

  const queryParams = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
      sort,
      order,
      q: debouncedQ.trim() || undefined,
    }),
    [page, sort, order, debouncedQ]
  );

  const swrKey = authToken
    ? (["vendors-scorecard", authToken, queryParams] as const)
    : null;

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    ([, token, params]) => vendorsApi.scorecard(token, params),
    { keepPreviousData: true, revalidateOnFocus: false }
  );

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const items = data?.items ?? [];

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const resolvingToken = tokenState === null;
  const showSkeleton =
    resolvingToken || (!!authToken && isLoading && !data);
  const showEmpty =
    !showSkeleton &&
    !error &&
    authToken &&
    total === 0 &&
    !debouncedQ.trim();
  const showSearchMiss =
    !showSkeleton &&
    !error &&
    authToken &&
    total === 0 &&
    !!debouncedQ.trim();

  function handleSort(key: SortKey) {
    if (sort === key) {
      setOrder((o) => (o === "desc" ? "asc" : "desc"));
    } else {
      setSort(key);
      setOrder(key === "supplier_gstin_normalized" ? "asc" : "desc");
    }
  }

  function goDetail(row: VendorScorecardRow) {
    router.push(`/vendors/${encodeURIComponent(row.supplier_gstin)}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
              Vendors
            </h1>
            {!showSkeleton && authToken && !error && (
              <span className="rounded-full bg-[#F0F0F0] px-2.5 py-1 text-xs font-semibold text-gray-600">
                {total.toLocaleString("en-IN")}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Cross-client supplier compliance scorecard for your firm
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load vendor scorecard.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--ink)] underline"
            onClick={() => void mutate()}
          >
            Retry
          </button>
        </div>
      )}

      {!authToken && tokenState === false && (
        <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
          Sign in to load the vendor scorecard.
        </div>
      )}

      {showEmpty ? (
        <div className="dashboard-card flex min-h-[320px] flex-col items-center justify-center px-6 py-16 text-center">
          <div className="mx-auto w-full max-w-[400px]">
            <EmptyStateIllustration className="mx-auto text-gray-300" />
            <h3 className="mt-4 text-lg font-semibold text-[var(--ink)]">
              No vendor data yet
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Complete a reconciliation run to populate this.
            </p>
            <Link
              href="/clients"
              className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              Go to Clients
            </Link>
          </div>
        </div>
      ) : (
        <section className="dashboard-card space-y-5 p-6">
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search supplier GSTIN…"
              className="h-10 min-w-[220px] flex-1 rounded-full border-0 bg-[#F5F5F6] px-4 text-[13px] font-medium text-gray-700 placeholder:text-gray-400 outline-none transition-shadow focus:ring-2 focus:ring-black/10"
              aria-label="Search supplier GSTIN"
            />
          </div>

          {showSkeleton ? (
            <VendorsSkeleton />
          ) : showSearchMiss ? (
            <p className="px-1 py-8 text-center text-sm text-gray-500">
              No vendors match your search.
            </p>
          ) : (
            <>
              <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
                <div className="overflow-x-auto">
                  <table className="min-w-[1100px] w-full border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                        <SortHeader
                          label="Supplier"
                          sortKey="supplier_gstin_normalized"
                          current={sort}
                          order={order}
                          onSort={handleSort}
                          className="px-5 text-left"
                        />
                        <SortHeader
                          label="Risk"
                          sortKey="risk_score"
                          current={sort}
                          order={order}
                          onSort={handleSort}
                        />
                        <SortHeader
                          label="Clients"
                          sortKey="clients_touched_count"
                          current={sort}
                          order={order}
                          onSort={handleSort}
                        />
                        <SortHeader
                          label="Mismatch"
                          sortKey="mismatch_rate"
                          current={sort}
                          order={order}
                          onSort={handleSort}
                        />
                        <SortHeader
                          label="Rule 37"
                          sortKey="rule37_open_count"
                          current={sort}
                          order={order}
                          onSort={handleSort}
                        />
                        <th className="px-4 py-4">17(5)</th>
                        <SortHeader
                          label="Late filing"
                          sortKey="late_filing_rate"
                          current={sort}
                          order={order}
                          onSort={handleSort}
                        />
                        <th className="px-5 py-4">Filer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((row) => {
                        const atRisk = paiseToRupee(row.rule37_at_risk_paise);
                        return (
                          <tr
                            key={row.supplier_gstin}
                            role="link"
                            tabIndex={0}
                            onClick={() => goDetail(row)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                goDetail(row);
                              }
                            }}
                            className="cursor-pointer border-b border-[#F0F0F0] transition-colors hover:bg-[#F7F7F8] last:border-b-0"
                          >
                            <td className="px-5 py-3.5">
                              <div className="font-medium text-[var(--ink)]">
                                {row.supplier_trade_name?.trim() || "—"}
                              </div>
                              <div className="mt-0.5 font-mono text-xs text-gray-400">
                                {row.supplier_gstin}
                              </div>
                            </td>
                            <td className="px-4 py-3.5">
                              <RiskScoreBadge score={row.risk_score} />
                            </td>
                            <td className="px-4 py-3.5 tabular-nums text-gray-700">
                              {row.clients_touched_count.toLocaleString("en-IN")}
                            </td>
                            <td className="px-4 py-3.5 tabular-nums text-gray-700">
                              {formatPct(row.mismatch_rate)}
                            </td>
                            <td className="px-4 py-3.5">
                              <div className="tabular-nums text-[var(--ink)]">
                                {row.rule37_open_count.toLocaleString("en-IN")}
                              </div>
                              <div className="mt-0.5 font-mono text-xs text-gray-400">
                                {atRisk != null ? formatINR(atRisk) : "—"}
                              </div>
                            </td>
                            <td className="px-4 py-3.5 tabular-nums text-gray-700">
                              {row.section_17_5_count.toLocaleString("en-IN")}
                            </td>
                            <td className="px-4 py-3.5 tabular-nums text-gray-700">
                              {formatPct(row.late_filing_rate)}
                            </td>
                            <td className="px-5 py-3.5">
                              {row.quarterly_filer_flag ? (
                                <span className="inline-flex rounded-full bg-[var(--ink)] px-2.5 py-0.5 text-[11px] font-semibold text-white">
                                  Quarterly
                                </span>
                              ) : (
                                <span className="inline-flex rounded-full bg-[#F0F0F0] px-2.5 py-0.5 text-[11px] font-medium text-gray-500">
                                  —
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
              <ReconcilePaginationFooter
                page={page}
                totalPages={totalPages}
                total={total}
                limit={PAGE_SIZE}
                onPrev={() => setPage((p) => Math.max(1, p - 1))}
                onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={isLoading}
              />
            </>
          )}
        </section>
      )}
    </div>
  );
}
