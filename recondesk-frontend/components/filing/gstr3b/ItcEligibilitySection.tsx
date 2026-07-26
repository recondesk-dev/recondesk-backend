"use client";

import { useCallback, useState } from "react";

import { DraftSuggestionBanner } from "@/components/filing/gstr3b/DraftSuggestionBanner";
import {
  type Gstr3bFiguresState,
  type ItcOthSuggestion,
  type ItcRowProps,
  type SuggestionLoadResult,
} from "@/components/filing/gstr3b/figuresModel";
import { parseAmountInput } from "@/components/filing/gstr3b/TaxHeadTable";

type Props = {
  value: Gstr3bFiguresState["itc_elg"];
  onChange: (next: Gstr3bFiguresState["itc_elg"]) => void;
  onLoadOthSuggestion: () => Promise<SuggestionLoadResult<ItcOthSuggestion>>;
};

const ITC_COLS = ["iamt", "camt", "samt", "csamt"] as const;

const UNAVAILABLE_HINTS: Record<string, string> = {
  no_gstr2b_reconcile_run:
    "No GSTR-2B reconcile run for this period — OTH suggestions unavailable. This does not mean OTH ITC is zero; enter the amount from the books.",
  no_gstr2b_records:
    "GSTR-2B reconcile has no invoice records for this period — OTH suggestions unavailable. This does not mean OTH ITC is zero; enter the amount from the books.",
};

function ItcBlock({
  title,
  rows,
  onPatch,
}: {
  title: string;
  rows: ItcRowProps[];
  onPatch: (index: number, field: keyof ItcRowProps, raw: string) => void;
}) {
  return (
    <div>
      <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-gray-400">
        {title}
      </h4>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-[#E8E8EA] text-[11px] font-semibold uppercase text-gray-400">
              <th className="py-2 pr-2 text-left">Type</th>
              <th className="px-1 py-2">IGST</th>
              <th className="px-1 py-2">CGST</th>
              <th className="px-1 py-2">SGST</th>
              <th className="px-1 py-2">Cess</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={`${row.ty}-${i}`} className="border-b border-[#F0F0F2]">
                <td className="py-2 pr-2 font-mono text-[12px] font-medium">
                  {row.ty || "—"}
                </td>
                {ITC_COLS.map((c) => (
                  <td key={c} className="px-1 py-1.5">
                    <input
                      type="text"
                      inputMode="decimal"
                      value={row[c] === "" ? "" : String(row[c])}
                      onChange={(e) => onPatch(i, c, e.target.value)}
                      className="h-9 w-full rounded-lg border-0 bg-[#F5F5F6] px-2 font-mono text-[12px] outline-none focus:ring-2 focus:ring-black/10"
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ItcEligibilitySection({
  value,
  onChange,
  onLoadOthSuggestion,
}: Props) {
  const [suggestion, setSuggestion] = useState<ItcOthSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(false);
  const [emptyHint, setEmptyHint] = useState<string | null>(null);

  const patchBlock = useCallback(
    (
      block: keyof Gstr3bFiguresState["itc_elg"],
      index: number,
      field: keyof ItcRowProps,
      raw: string
    ) => {
      const rows = [...value[block]];
      const row = { ...rows[index] };
      if (field === "ty") row.ty = raw;
      else row[field] = parseAmountInput(raw);
      rows[index] = row;
      onChange({ ...value, [block]: rows });
    },
    [onChange, value]
  );

  const othIndex = value.itc_avl.findIndex((r) => r.ty === "OTH");
  const othRow = othIndex >= 0 ? value.itc_avl[othIndex] : null;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-[14px] font-semibold text-[var(--ink)]">
          Table 4 — ITC eligibility
        </h3>
        <p className="mt-0.5 text-[12px] text-gray-500">
          4(A) Available by type, 4(B) Reversed, 4(C) Net, 4(D) Ineligible.
          Only OTH can pull an optional GSTR-2B suggestion.
        </p>
      </div>

      <ItcBlock
        title="4(A) ITC available"
        rows={value.itc_avl}
        onPatch={(i, f, raw) => patchBlock("itc_avl", i, f, raw)}
      />

      <DraftSuggestionBanner
        sourceLabel={suggestion?.source || "GSTR-2B Table 4.1(A) OTH"}
        values={{
          iamt: suggestion?.iamt,
          camt: suggestion?.camt,
          samt: suggestion?.samt,
          csamt: suggestion?.csamt,
        }}
        fieldLabels={{ iamt: "IGST", camt: "CGST", samt: "SGST", csamt: "Cess" }}
        applied={applied}
        differsFromInput={
          !!suggestion &&
          !!othRow &&
          (["iamt", "camt", "samt", "csamt"] as const).some((k) => {
            const sv = suggestion[k];
            if (sv == null) return false;
            return Number(othRow[k] === "" ? NaN : othRow[k]) !== Number(sv);
          })
        }
        busy={busy}
        emptyHint={emptyHint}
        loadLabel="Load suggestions (GSTR-2B OTH)"
        onLoad={() => {
          void (async () => {
            setBusy(true);
            setEmptyHint(null);
            setApplied(false);
            try {
              const result = await onLoadOthSuggestion();
              if (result.status === "unavailable") {
                setSuggestion(null);
                setEmptyHint(
                  UNAVAILABLE_HINTS[result.reason] ||
                    "No OTH suggestion available for this period. This does not mean OTH ITC is zero; enter the amount from the books."
                );
                return;
              }
              setSuggestion(result.suggestion);
              setEmptyHint(null);
            } catch {
              setSuggestion(null);
              setEmptyHint(
                "Could not load GSTR-2B suggestions. Try again, or enter the amount from the books."
              );
            } finally {
              setBusy(false);
            }
          })();
        }}
        onUse={() => {
          if (!suggestion || othIndex < 0) return;
          const rows = [...value.itc_avl];
          rows[othIndex] = {
            ...rows[othIndex],
            iamt: suggestion.iamt ?? "",
            camt: suggestion.camt ?? "",
            samt: suggestion.samt ?? "",
            csamt: suggestion.csamt ?? "",
          };
          onChange({ ...value, itc_avl: rows });
          setApplied(true);
        }}
        onDismiss={() => {
          setSuggestion(null);
          setApplied(false);
          setEmptyHint(null);
        }}
      />

      <ItcBlock
        title="4(B) ITC reversed"
        rows={value.itc_rev}
        onPatch={(i, f, raw) => patchBlock("itc_rev", i, f, raw)}
      />
      <ItcBlock
        title="4(C) Net ITC"
        rows={value.itc_net}
        onPatch={(i, f, raw) => patchBlock("itc_net", i, f, raw)}
      />
      <ItcBlock
        title="4(D) Ineligible ITC"
        rows={value.itc_inelg}
        onPatch={(i, f, raw) => patchBlock("itc_inelg", i, f, raw)}
      />
    </div>
  );
}
