"use client";

import type { Gstr3bPeriodLockedDetail } from "@/lib/api";

type Props = {
  detail: Gstr3bPeriodLockedDetail;
};

/** Full proof panel — not a bare error string. */
export function PeriodLockedProof({ detail }: Props) {
  const lr = detail.locking_run;
  return (
    <div className="rounded border border-[#6B2E2E] bg-[#1A1010] px-4 py-4 text-[#F0E4E4]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#E8A0A0]">
        Period locked — Offset already completed
      </p>
      <p className="mt-2 text-[13px] leading-relaxed text-[#E8D4D4]">
        {detail.message}
      </p>
      <dl className="mt-4 grid gap-2 font-mono text-[12px] sm:grid-cols-2">
        <div>
          <dt className="text-[#A88888]">run_id</dt>
          <dd className="break-all">{lr.run_id || "—"}</dd>
        </div>
        <div>
          <dt className="text-[#A88888]">status</dt>
          <dd>{lr.status || "—"}</dd>
        </div>
        <div>
          <dt className="text-[#A88888]">offset_completed_at</dt>
          <dd>
            {lr.offset_completed_at
              ? new Date(lr.offset_completed_at).toLocaleString("en-IN")
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[#A88888]">reference_id</dt>
          <dd className="break-all">{lr.reference_id || "—"}</dd>
        </div>
      </dl>

      <details className="mt-4">
        <summary className="cursor-pointer text-[12px] font-semibold text-[#E8A0A0]">
          What was offset (offset_payload)
        </summary>
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-[#0E0A0A] p-3 text-[11px] text-[#D8C8C8]">
          {JSON.stringify(lr.offset_payload, null, 2)}
        </pre>
      </details>

      <details className="mt-3">
        <summary className="cursor-pointer text-[12px] font-semibold text-[#E8A0A0]">
          Post-offset proof (tx_pmt_snapshot)
        </summary>
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-[#0E0A0A] p-3 text-[11px] text-[#D8C8C8]">
          {JSON.stringify(lr.tx_pmt_snapshot, null, 2)}
        </pre>
      </details>

      <p className="mt-4 text-[12px] text-[#C8A8A8]">
        Save and Offset for this GSTIN · period are permanently blocked.
        Corrections belong in a future period&apos;s return.
      </p>
    </div>
  );
}
