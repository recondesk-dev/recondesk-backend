"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import useSWR from "swr";

import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { apiFetch } from "@/lib/api";
import { formatINR } from "@/lib/format";

// ─── Types (mirrors GET /api/audit-observations/{run_id}) ────────────────────

type Severity = "Critical" | "High" | "Medium" | "Low";

type AuditObservation = {
  observation_id: string;
  source_rule: string;
  severity: Severity | string;
  section_reference: string;
  title: string;
  description: string;
  financial_impact: number | null;
  affected_count: number;
  recommendation: string;
  /** Present on invoice-level rules. */
  linked_invoice_ids?: string[];
  /**
   * Present on GSTR1_VS_3B_LIABILITY_MISMATCH only — period-level field names
   * (e.g. taxable_value, igst), not invoice IDs. Do not use for invoice deeplinks.
   */
  linked_fields?: string[];
  /** Rule 37 lower-bound caveat when interest is deadline-based, not availment-based. */
  financial_impact_note?: string;
};

type AuditObservationsResponse = {
  run_id: string;
  run_type: string;
  summary: {
    critical_count: number;
    high_count: number;
    medium_count: number;
    low_count: number;
    total_financial_impact: number;
  };
  observations: AuditObservation[];
};

const SEVERITY_RANK: Record<string, number> = {
  Critical: 0,
  High: 1,
  Medium: 2,
  Low: 3,
};

const FIELD_LABELS: Record<string, string> = {
  taxable_value: "Taxable value",
  igst: "IGST",
  cgst: "CGST",
  sgst: "SGST",
  cess: "CESS",
  total_tax: "Total tax",
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] || field;
}

function severityBadgeClass(severity: string): string {
  switch (severity) {
    case "Critical":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "High":
      return "bg-orange-50 text-orange-800 ring-1 ring-orange-200";
    case "Medium":
      return "bg-amber-50 text-amber-800 ring-1 ring-amber-200";
    default:
      return "bg-gray-100 text-gray-600 ring-1 ring-gray-200";
  }
}

function countBadgeClass(severity: Severity): string {
  switch (severity) {
    case "Critical":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "High":
      return "bg-orange-50 text-orange-800 ring-1 ring-orange-200";
    case "Medium":
      return "bg-amber-50 text-amber-800 ring-1 ring-amber-200";
    case "Low":
      return "bg-gray-100 text-gray-600 ring-1 ring-gray-200";
  }
}

function stripImpactNote(description: string, note: string | undefined): string {
  if (!note) return description;
  const trimmed = description.trim();
  if (trimmed.endsWith(note)) {
    return trimmed.slice(0, -note.length).trim();
  }
  if (trimmed.includes(note)) {
    return trimmed.replace(note, "").replace(/\s{2,}/g, " ").trim();
  }
  return trimmed;
}

function sortBySeverity(observations: AuditObservation[]): AuditObservation[] {
  return [...observations].sort((a, b) => {
    const ra = SEVERITY_RANK[a.severity] ?? 99;
    const rb = SEVERITY_RANK[b.severity] ?? 99;
    if (ra !== rb) return ra - rb;
    return a.source_rule.localeCompare(b.source_rule);
  });
}

function summarizeObservations(observations: AuditObservation[]): AuditObservationsResponse["summary"] {
  const counts = { Critical: 0, High: 0, Medium: 0, Low: 0 };
  let total = 0;
  for (const obs of observations) {
    const sev = obs.severity as Severity;
    if (sev in counts) counts[sev] += 1;
    if (obs.financial_impact != null && Number.isFinite(obs.financial_impact)) {
      total += obs.financial_impact;
    }
  }
  return {
    critical_count: counts.Critical,
    high_count: counts.High,
    medium_count: counts.Medium,
    low_count: counts.Low,
    total_financial_impact: Math.round(total * 100) / 100,
  };
}

// ─── Subcomponents ───────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${severityBadgeClass(severity)}`}
    >
      {severity}
    </span>
  );
}

function CountBadge({
  label,
  count,
  severity,
}: {
  label: string;
  count: number;
  severity: Severity;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-semibold ${countBadgeClass(severity)}`}
    >
      <span className="tabular-nums">{count}</span>
      <span className="font-medium opacity-80">{label}</span>
    </span>
  );
}

function LinkedList({
  observation,
}: {
  observation: AuditObservation;
}) {
  const [open, setOpen] = useState(false);
  const isFields =
    Array.isArray(observation.linked_fields) &&
    observation.linked_fields.length > 0;
  const items = isFields
    ? observation.linked_fields!
    : observation.linked_invoice_ids ?? [];

  if (items.length === 0) return null;

  const label = isFields ? "Affected fields" : "Affected invoices";
  const countLabel = isFields
    ? `${items.length} field${items.length === 1 ? "" : "s"}`
    : `${items.length} invoice${items.length === 1 ? "" : "s"}`;

  return (
    <div className="mt-3 border-t border-[#F0F0F0] pt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 text-left text-[12px] font-medium text-gray-600 transition-colors hover:text-[var(--ink)]"
        aria-expanded={open}
      >
        <span>
          {label}{" "}
          <span className="font-normal text-gray-400">({countLabel})</span>
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      {open ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {items.map((item) => (
            <li key={item}>
              <span className="inline-flex rounded-full bg-[#F5F5F6] px-2.5 py-0.5 font-mono text-[11px] font-medium text-gray-700">
                {isFields ? fieldLabel(item) : item}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ObservationCard({ observation }: { observation: AuditObservation }) {
  const note = observation.financial_impact_note?.trim();
  const description = stripImpactNote(observation.description || "", note);
  const hasFields =
    Array.isArray(observation.linked_fields) &&
    observation.linked_fields.length > 0;
  const affectedLabel = hasFields
    ? `${observation.affected_count} field${observation.affected_count === 1 ? "" : "s"} affected`
    : `${observation.affected_count} invoice${observation.affected_count === 1 ? "" : "s"} affected`;

  return (
    <article className="rounded-xl border border-[#F0F0F0] bg-white px-4 py-4 shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={observation.severity} />
            <h3 className="text-[14px] font-semibold tracking-tight text-[var(--ink)]">
              {observation.title}
            </h3>
          </div>
          <p className="text-[12px] text-gray-500">
            {observation.section_reference}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {observation.financial_impact != null ? (
            <p className="text-[15px] font-semibold tabular-nums tracking-tight text-[var(--ink)]">
              {formatINR(observation.financial_impact)}
            </p>
          ) : (
            <p className="text-[12px] text-gray-400">No direct ₹ impact</p>
          )}
          <span className="inline-flex rounded-full bg-[var(--ink)] px-2.5 py-0.5 text-[11px] font-semibold text-white">
            {affectedLabel}
          </span>
        </div>
      </div>

      {description ? (
        <p className="mt-3 text-[13px] leading-relaxed text-gray-600">
          {description}
        </p>
      ) : null}

      {note ? (
        <p className="mt-2 rounded-lg bg-[#F7F7F8] px-3 py-2 text-[12px] leading-snug text-gray-500">
          {note}
        </p>
      ) : null}

      {observation.recommendation ? (
        <div className="mt-3 rounded-lg border border-[#E8E8EA] bg-[#FAFAFB] px-3 py-2.5">
          <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
            Recommendation
          </p>
          <p className="mt-1 text-[13px] font-medium leading-snug text-[var(--ink)]">
            {observation.recommendation}
          </p>
        </div>
      ) : null}

      <LinkedList observation={observation} />
    </article>
  );
}

// ─── Panel ───────────────────────────────────────────────────────────────────

export function AuditObservationsPanel({
  runId,
  authToken,
  refreshKey = 0,
  filterSourceRule,
}: {
  runId: string;
  authToken: string;
  refreshKey?: number;
  /**
   * When set, only observations with this ``source_rule`` are shown, and
   * summary counts / total_financial_impact are recomputed for that subset.
   */
  filterSourceRule?: string;
}) {
  const swrKey =
    runId && authToken
      ? (["audit-observations", runId, authToken, refreshKey] as const)
      : null;

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    ([, rid, token]) =>
      apiFetch<AuditObservationsResponse>(
        `/api/audit-observations/${encodeURIComponent(rid)}`,
        { token }
      ),
    { revalidateOnFocus: false }
  );

  const sorted = useMemo(() => {
    const all = data?.observations ?? [];
    const filtered = filterSourceRule
      ? all.filter((o) => o.source_rule === filterSourceRule)
      : all;
    return sortBySeverity(filtered);
  }, [data?.observations, filterSourceRule]);

  const summary = useMemo(() => summarizeObservations(sorted), [sorted]);

  if (error) {
    return (
      <section
        className={sectionContainerClass}
        aria-label="Audit observations"
      >
        <SectionHeader title="Audit Observations" dotColor="#111111" />
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Failed to load audit observations.{" "}
          <button
            type="button"
            className="font-medium underline"
            onClick={() => void mutate()}
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  if (isLoading && !data) {
    return (
      <section
        className={sectionContainerClass}
        aria-label="Audit observations"
      >
        <SectionHeader title="Audit Observations" dotColor="#111111" />
        <p className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading audit observations…
        </p>
      </section>
    );
  }

  if (!data) return null;

  const isEmpty = sorted.length === 0;

  return (
    <section className={sectionContainerClass} aria-label="Audit observations">
      <SectionHeader
        title="Audit Observations"
        dotColor="#111111"
        actions={
          <span className="inline-flex rounded-full bg-[var(--ink)] px-3 py-1 text-xs font-semibold text-white">
            {sorted.length} finding{sorted.length === 1 ? "" : "s"}
          </span>
        }
      />

      {/* Summary header */}
      <div className="mt-1 flex flex-col gap-4 border-t border-[#F0F0F0] pt-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-wrap gap-2">
          <CountBadge
            label="Critical"
            count={summary.critical_count}
            severity="Critical"
          />
          <CountBadge
            label="High"
            count={summary.high_count}
            severity="High"
          />
          <CountBadge
            label="Medium"
            count={summary.medium_count}
            severity="Medium"
          />
          <CountBadge
            label="Low"
            count={summary.low_count}
            severity="Low"
          />
        </div>
        <div className="min-w-0 sm:text-right">
          <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
            Total financial impact
          </p>
          <p className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight text-[var(--ink)]">
            {formatINR(summary.total_financial_impact)}
          </p>
        </div>
      </div>

      {isEmpty ? (
        <p className="mt-6 text-[13px] italic text-gray-400">
          {filterSourceRule
            ? "No audit observations for this category."
            : "No audit observations for this run."}
        </p>
      ) : (
        <ul className="mt-5 space-y-3">
          {sorted.map((obs) => (
            <li key={obs.observation_id}>
              <ObservationCard observation={obs} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
