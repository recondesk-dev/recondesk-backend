"use client";

import type { Gstr3bOffsetStaleDetail } from "@/lib/api";
import {
  sumPdcashTaxOutflow,
  sumPditcItc,
  formatInr,
} from "@/components/filing/gstr3b/offsetConfirmLogic";

type Props = {
  detail: Gstr3bOffsetStaleDetail;
  onRefreshPreview: () => void;
  busy?: boolean;
};

/**
 * Stale confirmation — forces a full re-preview. Parent must also reset
 * all three deliberate steps (checkbox, typed total, hold).
 */
export function OffsetStaleBanner({
  detail,
  onRefreshPreview,
  busy,
}: Props) {
  const postedCash = sumPdcashTaxOutflow(detail.posted.pdcash);
  const currentCash = sumPdcashTaxOutflow(detail.current.pdcash);
  const postedItc = sumPditcItc(detail.posted.pditc);
  const currentItc = sumPditcItc(detail.current.pditc);

  return (
    <div className="rounded border border-[#8A6A20] bg-[#1A1608] px-4 py-4 text-[#F0E8D0]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#E8C860]">
        Confirmation stale — numbers changed
      </p>
      <p className="mt-2 text-[13px] leading-relaxed text-[#E0D6B8]">
        {detail.message} Your deliberate confirmation steps have been cleared —
        you must review, re-type the cash total, and hold-to-commit again.
      </p>

      <div className="mt-4 grid gap-3 font-mono text-[12px] sm:grid-cols-2">
        <div className="rounded border border-[#4A4020] bg-[#120F08] px-3 py-3">
          <p className="mb-2 text-[10px] uppercase tracking-wide text-[#A89860]">
            You confirmed
          </p>
          <p>Cash {formatInr(postedCash)}</p>
          <p className="mt-1">ITC {formatInr(postedItc)}</p>
        </div>
        <div className="rounded border border-[#4A4020] bg-[#120F08] px-3 py-3">
          <p className="mb-2 text-[10px] uppercase tracking-wide text-[#A89860]">
            Current (recomputed)
          </p>
          <p>Cash {formatInr(currentCash)}</p>
          <p className="mt-1">ITC {formatInr(currentItc)}</p>
        </div>
      </div>

      <button
        type="button"
        disabled={busy}
        onClick={onRefreshPreview}
        className="mt-4 inline-flex rounded border border-[#E8C860]/40 bg-[#E8C860] px-4 py-2 text-[12px] font-semibold text-[#1A1608] hover:opacity-90 disabled:opacity-40"
      >
        {busy ? "Refreshing…" : "Refresh preview & restart confirmation"}
      </button>
    </div>
  );
}
