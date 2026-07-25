"use client";

import type { FilingReadinessVerdict } from "@/lib/api";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";

export function FilingReadinessSummary({
  verdict,
  recordCount,
}: {
  verdict: FilingReadinessVerdict;
  recordCount?: number | null;
}) {
  return (
    <section className={sectionContainerClass} aria-label="Filing readiness">
      <SectionHeader title="Filing readiness" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">{verdict.summary}</p>

      <div className="mt-4 flex flex-wrap gap-2">
        <StatusPill
          ok={verdict.can_save}
          okLabel="Ready to Save"
          badLabel="Cannot Save"
        />
        <StatusPill
          ok={verdict.can_file}
          okLabel="Ready to File"
          badLabel="Cannot File yet"
        />
        {recordCount != null ? (
          <span className="inline-flex items-center rounded-full bg-[#F5F5F6] px-3 py-1 text-[12px] font-semibold text-gray-700">
            {recordCount.toLocaleString("en-IN")} SR rows
          </span>
        ) : null}
      </div>

      {verdict.file_blockers.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-gray-500">
            Must fix before File
          </h3>
          <p className="mt-1 text-[12px] text-gray-500">
            GSTN will reject File when these are missing with outward supplies
            (Table 13 Documents Issued / Table 12 HSN–B2B). Save can still
            proceed without them.
          </p>
          <ul className="mt-2 space-y-2">
            {verdict.file_blockers.map((b) => (
              <li
                key={b}
                className="rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)] ring-1 ring-[#E8E8EA]"
              >
                {b}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {verdict.advisory.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-gray-500">
            Advisory (does not hard-block File)
          </h3>
          <ul className="mt-2 space-y-2">
            {verdict.advisory.map((a) => (
              <li
                key={a}
                className="rounded-xl px-4 py-3 text-[13px] text-gray-700 ring-1 ring-[#F0F0F0]"
              >
                {a}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {verdict.save_blockers.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-gray-500">
            Save blockers
          </h3>
          <ul className="mt-2 space-y-2">
            {verdict.save_blockers.map((b) => (
              <li
                key={b}
                className="rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)]"
              >
                {b}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function StatusPill({
  ok,
  okLabel,
  badLabel,
}: {
  ok: boolean;
  okLabel: string;
  badLabel: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-[12px] font-semibold ring-1 ${
        ok
          ? "bg-[#F5F5F6] text-[var(--ink)] ring-[#E5E5E7]"
          : "bg-white text-gray-600 ring-[#E5E5E7]"
      }`}
    >
      {ok ? okLabel : badLabel}
    </span>
  );
}
