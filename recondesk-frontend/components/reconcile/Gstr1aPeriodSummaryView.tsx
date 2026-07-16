"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Check, FileSpreadsheet, Loader2 } from "lucide-react";

import {
  Gstr1aMarkFiledModal,
  type Gstr1aMarkFiledTarget,
} from "@/components/reconcile/Gstr1aMarkFiledModal";
import {
  Gstr1aWindowBadge,
  Gstr1aWindowBanner,
} from "@/components/reconcile/Gstr1aWindowBadge";
import {
  EmptyTableState,
  pageContentClass,
  sectionContainerClass,
  StatCard,
} from "@/components/reconcile/ResultsUi";
import { isApiError } from "@/lib/api";
import {
  groupGstr1aEligibleByPeriod,
  gstr1RunPeriodLabel,
  listGstr1aFiledPeriods,
  markGstr1aPeriodFiled,
  mismatchTypeShort,
  normalisePeriodKey,
  type Gstr1aPeriodAction,
  type Gstr1aWindow,
  type Gstr1DecisionFields,
  type Gstr1ReconcileResult,
} from "@/lib/gstr1Reconcile";
import { downloadGstr1aReadyExcel } from "@/lib/gstr1ReconcileExport";

function SeverityPill({ severity }: { severity?: string | null }) {
  const s = String(severity || "").toLowerCase();
  const tone =
    s === "critical"
      ? "bg-red-50 text-red-700"
      : s === "high"
        ? "bg-amber-50 text-amber-800"
        : s === "medium"
          ? "bg-[#F0F0F0] text-gray-600"
          : "bg-[#F0F0F0] text-gray-500";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-medium capitalize ${tone}`}
    >
      {severity || "—"}
    </span>
  );
}

function TypePill({ type }: { type?: string }) {
  return (
    <span className="inline-flex rounded-full bg-[var(--ink)] px-2.5 py-0.5 text-[11px] font-semibold text-white">
      {mismatchTypeShort(type)}
    </span>
  );
}

function FiledBadge({ filedDate }: { filedDate?: string | null }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-0.5 text-[11px] font-medium text-green-700 ring-1 ring-green-200">
      <Check className="h-3 w-3" aria-hidden />
      GSTR-1A filed
      {filedDate ? ` · ${filedDate}` : ""}
    </span>
  );
}

function EligibleMismatchRow({
  mismatch,
  index,
  gstr1aWindow,
  isFiled,
}: {
  mismatch: Gstr1DecisionFields;
  index: number;
  gstr1aWindow: Gstr1aWindow | null;
  isFiled: boolean;
}) {
  return (
    <li className="rounded-xl bg-white px-4 py-3 ring-1 ring-[#F0F0F0]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium tabular-nums text-gray-400">
          {index}
        </span>
        <TypePill type={mismatch.mismatch_type} />
        <SeverityPill severity={mismatch.mismatch_severity} />
        {isFiled ? (
          <FiledBadge />
        ) : (
          <Gstr1aWindowBadge
            eligibility={mismatch.eligibility}
            window={gstr1aWindow}
          />
        )}
        <span className="text-[13px] font-medium text-[var(--ink)]">
          {mismatch.decision_what || mismatch.invoice_number || "—"}
        </span>
      </div>
      {mismatch.decision_why ? (
        <p className="mt-1.5 text-[12px] leading-snug text-gray-500">
          {mismatch.decision_why}
        </p>
      ) : null}
      {mismatch.decision_next ? (
        <p className="mt-1 text-[12px] font-medium text-[var(--ink)]">
          {mismatch.decision_next}
        </p>
      ) : null}
      {mismatch.note ? (
        <p className="mt-1 text-[11px] text-gray-400">{mismatch.note}</p>
      ) : null}
    </li>
  );
}

function PeriodSection({
  period,
  mismatches,
  gstr1aWindow,
  filedAction,
  canMarkFiled,
  marking,
  onMarkFiled,
}: {
  period: string;
  mismatches: Gstr1DecisionFields[];
  gstr1aWindow: Gstr1aWindow | null;
  filedAction?: Gstr1aPeriodAction | null;
  canMarkFiled: boolean;
  marking: boolean;
  onMarkFiled: () => void;
}) {
  const isFiled = Boolean(filedAction);

  return (
    <section
      className={`${sectionContainerClass} ${isFiled ? "opacity-90" : ""}`}
      aria-label={`Period ${period}`}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
            Period
          </p>
          <h2 className="mt-0.5 text-[15px] font-semibold tracking-tight text-[var(--ink)]">
            {period}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {isFiled ? (
              <FiledBadge filedDate={filedAction?.filed_date} />
            ) : (
              <Gstr1aWindowBadge eligibility="eligible" window={gstr1aWindow} />
            )}
            <span className="text-[13px] text-gray-500">
              {mismatches.length.toLocaleString("en-IN")} eligible mismatch
              {mismatches.length === 1 ? "" : "es"}
            </span>
          </div>
        </div>
        {!isFiled ? (
          <button
            type="button"
            disabled={!canMarkFiled || marking}
            onClick={onMarkFiled}
            title={
              canMarkFiled
                ? undefined
                : "Persist the GSTR-1 run (with a client) to mark periods as filed"
            }
            className="inline-flex h-9 items-center gap-2 rounded-full bg-[var(--ink)] px-4 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {marking ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
            Mark GSTR-1A as filed
          </button>
        ) : null}
      </div>
      <ul className="space-y-2">
        {mismatches.map((m, i) => (
          <EligibleMismatchRow
            key={`${period}-${m.mismatch_type}-${m.invoice_number}-${i}`}
            mismatch={m}
            index={i + 1}
            gstr1aWindow={gstr1aWindow}
            isFiled={isFiled}
          />
        ))}
      </ul>
    </section>
  );
}

export function Gstr1aPeriodSummaryView({
  result,
  backHref,
  token,
}: {
  result: Gstr1ReconcileResult;
  backHref: string;
  token?: string | null;
}) {
  const [excelBusy, setExcelBusy] = useState(false);
  const [filedByPeriod, setFiledByPeriod] = useState<
    Record<string, Gstr1aPeriodAction>
  >({});
  const [actionsLoading, setActionsLoading] = useState(false);
  const [markTarget, setMarkTarget] = useState<Gstr1aMarkFiledTarget | null>(
    null
  );
  const [markSaving, setMarkSaving] = useState(false);
  const [markError, setMarkError] = useState<string | null>(null);

  const runId = result.run_id?.trim() || null;
  const canPersist = Boolean(runId && token);

  const gstr1aWindow =
    result.gstr1a_window ?? result.summary?.gstr1a_window ?? null;
  const fallbackPeriod = gstr1RunPeriodLabel(result) || "—";

  const periodGroups = useMemo(
    () =>
      groupGstr1aEligibleByPeriod(result.mismatches || [], fallbackPeriod),
    [result.mismatches, fallbackPeriod]
  );

  const { openGroups, filedGroups } = useMemo(() => {
    const open: typeof periodGroups = [];
    const filed: typeof periodGroups = [];
    for (const g of periodGroups) {
      const key = normalisePeriodKey(g.period) || g.period;
      if (filedByPeriod[key]) filed.push(g);
      else open.push(g);
    }
    return { openGroups: open, filedGroups: filed };
  }, [periodGroups, filedByPeriod]);

  const openEligibleCount = useMemo(
    () => openGroups.reduce((n, g) => n + g.mismatches.length, 0),
    [openGroups]
  );
  const totalEligible = useMemo(
    () => periodGroups.reduce((n, g) => n + g.mismatches.length, 0),
    [periodGroups]
  );

  const refreshFiledActions = useCallback(async () => {
    if (!runId || !token) {
      setFiledByPeriod({});
      return;
    }
    setActionsLoading(true);
    try {
      const rows = await listGstr1aFiledPeriods(token, runId);
      const map: Record<string, Gstr1aPeriodAction> = {};
      for (const row of rows) {
        const key = normalisePeriodKey(row.period) || row.period;
        if (key) map[key] = row;
      }
      setFiledByPeriod(map);
    } catch {
      // Non-blocking — screen still usable without filed history.
    } finally {
      setActionsLoading(false);
    }
  }, [runId, token]);

  useEffect(() => {
    void refreshFiledActions();
  }, [refreshFiledActions]);

  const handleExport = () => {
    setExcelBusy(true);
    try {
      downloadGstr1aReadyExcel(result);
    } finally {
      setExcelBusy(false);
    }
  };

  const handleMarkSubmit = async (payload: {
    confirmed: boolean;
    filed_date?: string;
    note?: string;
  }) => {
    if (!markTarget || !runId || !token) return;
    setMarkSaving(true);
    setMarkError(null);
    try {
      const saved = await markGstr1aPeriodFiled(token, runId, {
        period: markTarget.period,
        confirmed: payload.confirmed,
        filed_date: payload.filed_date,
        note: payload.note,
      });
      const key = normalisePeriodKey(saved.period) || saved.period;
      setFiledByPeriod((prev) => ({
        ...prev,
        [key]: saved,
      }));
      setMarkTarget(null);
    } catch (err) {
      if (isApiError(err)) {
        setMarkError(err.detail || `Request failed (${err.status})`);
      } else if (err instanceof Error) {
        setMarkError(err.message);
      } else {
        setMarkError("Failed to mark GSTR-1A as filed");
      }
    } finally {
      setMarkSaving(false);
    }
  };

  /** Banner for open queue — hide urgency once every period is filed. */
  const bannerWindow: Gstr1aWindow | null =
    openGroups.length === 0 && filedGroups.length > 0
      ? {
          status: "window_closed",
          days_remaining: 0,
          note: "All periods on this run are marked GSTR-1A filed.",
        }
      : gstr1aWindow;

  return (
    <div className="min-h-screen w-full min-w-0 pb-24">
      <div className="sticky top-0 z-30 border-b border-[#F0F0F0]/80 bg-white/90 px-8 py-5 backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Link
              href={backHref}
              className="inline-flex items-center gap-1.5 text-[12px] font-medium text-gray-500 transition-colors hover:text-[var(--ink)]"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
              Back to GSTR-1 results
            </Link>
            <p className="mt-2 text-[11px] font-medium uppercase tracking-widest text-gray-400">
              GSTR-1A · Per-period summary
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight text-[var(--ink)]">
              Amendable mismatches
            </h1>
            <p className="mt-1 text-[13px] text-gray-500">
              All GSTR-1A-eligible issues for this run, grouped by period —
              review as one batch before filing.
            </p>
            {markError ? (
              <p className="mt-2 text-[12px] font-medium text-red-600">
                {markError}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-3">
            <button
              type="button"
              disabled={excelBusy || totalEligible === 0}
              onClick={handleExport}
              className="inline-flex h-9 items-center gap-2 rounded-full bg-[var(--ink)] px-4 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {excelBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileSpreadsheet className="h-4 w-4" />
              )}
              GSTR-1A ready
            </button>
            <div className="grid grid-cols-2 gap-3">
              <StatCard
                label="Open queue"
                value={openEligibleCount.toLocaleString("en-IN")}
                subtext={`${openGroups.length} period${openGroups.length === 1 ? "" : "s"}`}
                emphasis="attention"
              />
              <StatCard
                label="Filed"
                value={filedGroups.length.toLocaleString("en-IN")}
                subtext={actionsLoading ? "Loading…" : "Periods marked filed"}
                emphasis="secondary"
              />
            </div>
          </div>
        </div>

        <div className="mt-5">
          <Gstr1aWindowBanner window={bannerWindow} />
        </div>
      </div>

      <div className={pageContentClass}>
        {totalEligible === 0 ? (
          <section className={sectionContainerClass}>
            <EmptyTableState
              title="No GSTR-1A-eligible mismatches"
              description="Nothing in this run is marked eligible for GSTR-1A amendment."
            />
          </section>
        ) : (
          <>
            {openGroups.length > 0 ? (
              <div className="space-y-5">
                <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
                  Open / urgent
                </p>
                {openGroups.map((group) => (
                  <PeriodSection
                    key={group.period}
                    period={group.period}
                    mismatches={group.mismatches}
                    gstr1aWindow={gstr1aWindow}
                    filedAction={null}
                    canMarkFiled={canPersist}
                    marking={
                      markSaving && markTarget?.period === group.period
                    }
                    onMarkFiled={() => {
                      setMarkError(null);
                      setMarkTarget({
                        period: group.period,
                        mismatchCount: group.mismatches.length,
                      });
                    }}
                  />
                ))}
              </div>
            ) : (
              <section className={sectionContainerClass}>
                <EmptyTableState
                  title="Open queue is clear"
                  description="Every period with eligible mismatches has been marked GSTR-1A filed."
                />
              </section>
            )}

            {filedGroups.length > 0 ? (
              <div className="mt-8 space-y-5">
                <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
                  Filed periods
                </p>
                {filedGroups.map((group) => {
                  const key = normalisePeriodKey(group.period) || group.period;
                  return (
                    <PeriodSection
                      key={`filed-${group.period}`}
                      period={group.period}
                      mismatches={group.mismatches}
                      gstr1aWindow={gstr1aWindow}
                      filedAction={filedByPeriod[key]}
                      canMarkFiled={false}
                      marking={false}
                      onMarkFiled={() => {}}
                    />
                  );
                })}
              </div>
            ) : null}
          </>
        )}
      </div>

      <Gstr1aMarkFiledModal
        open={markTarget != null}
        target={markTarget}
        saving={markSaving}
        onClose={() => {
          if (!markSaving) setMarkTarget(null);
        }}
        onSubmit={handleMarkSubmit}
      />
    </div>
  );
}
