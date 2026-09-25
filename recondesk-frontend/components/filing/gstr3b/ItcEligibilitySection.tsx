"use client";

import { useCallback, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Sparkles } from "lucide-react";

import { DraftSuggestionBanner } from "@/components/filing/gstr3b/DraftSuggestionBanner";
import {
  type Gstr3bFiguresState,
  type ItcOthSuggestion,
  type ItcRowProps,
  type SuggestionLoadResult,
} from "@/components/filing/gstr3b/figuresModel";
import { parseAmountInput } from "@/components/filing/gstr3b/TaxHeadTable";
import { isApiError, type Gstr3bTable4SuggestionResponse } from "@/lib/api";

type Props = {
  value: Gstr3bFiguresState["itc_elg"];
  onChange: (next: Gstr3bFiguresState["itc_elg"]) => void;
  onLoadOthSuggestion: () => Promise<SuggestionLoadResult<ItcOthSuggestion>>;
  onLoadTable4Suggestion?: () => Promise<Gstr3bTable4SuggestionResponse>;
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
  onLoadTable4Suggestion,
}: Props) {
  const [suggestion, setSuggestion] = useState<ItcOthSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(false);
  const [emptyHint, setEmptyHint] = useState<string | null>(null);

  const [table4Result, setTable4Result] = useState<Gstr3bTable4SuggestionResponse | null>(null);
  const [table4Busy, setTable4Busy] = useState(false);
  const [table4Applied, setTable4Applied] = useState(false);
  const [table4Error, setTable4Error] = useState<string | null>(null);

  const handleLoadTable4 = useCallback(async () => {
    if (!onLoadTable4Suggestion) return;
    setTable4Busy(true);
    setTable4Error(null);
    try {
      const res = await onLoadTable4Suggestion();
      setTable4Result(res);
      if ((res.available || res.status === "available") && res.itc_elg) {
        onChange({
          itc_avl: res.itc_elg.itc_avl.map((r) => ({
            ty: r.ty,
            iamt: r.iamt ?? "",
            camt: r.camt ?? "",
            samt: r.samt ?? "",
            csamt: r.csamt ?? "",
          })),
          itc_rev: res.itc_elg.itc_rev.map((r) => ({
            ty: r.ty,
            iamt: r.iamt ?? "",
            camt: r.camt ?? "",
            samt: r.samt ?? "",
            csamt: r.csamt ?? "",
          })),
          itc_net: res.itc_elg.itc_net.map((r) => ({
            ty: r.ty,
            iamt: r.iamt ?? "",
            camt: r.camt ?? "",
            samt: r.samt ?? "",
            csamt: r.csamt ?? "",
          })),
          itc_inelg: res.itc_elg.itc_inelg.map((r) => ({
            ty: r.ty,
            iamt: r.iamt ?? "",
            camt: r.camt ?? "",
            samt: r.samt ?? "",
            csamt: r.csamt ?? "",
          })),
        });
        setTable4Applied(true);
      }
    } catch (err: unknown) {
      setTable4Error(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Failed to load Table 4 suggestion"
      );
    } finally {
      setTable4Busy(false);
    }
  }, [onChange, onLoadTable4Suggestion]);

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
          Auto-populate from reconciliation or edit manually.
        </p>
      </div>

      {onLoadTable4Suggestion ? (
        <div className="rounded-2xl border border-emerald-200/90 bg-gradient-to-r from-emerald-50/70 to-teal-50/50 p-4 shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-white">
                  <Sparkles className="h-3.5 w-3.5" />
                </span>
                <h4 className="text-[13px] font-semibold text-emerald-950">
                  1-Click Table 4 Auto-Population from Reconciliation
                </h4>
              </div>
              <p className="text-[12px] text-emerald-800/80">
                Pulls all 4 sections (4A5 All other ITC, 4B2 Rule 37 reversals, 4C Net ITC, 4D2 Ineligible) directly from this period&apos;s reconciliation run.
              </p>
            </div>
            <button
              type="button"
              disabled={table4Busy}
              onClick={() => void handleLoadTable4()}
              className="inline-flex items-center justify-center gap-1.5 self-start sm:self-center shrink-0 rounded-full bg-emerald-700 px-4 py-2 text-[12px] font-semibold text-white shadow-xs hover:bg-emerald-800 transition disabled:opacity-50"
            >
              {table4Busy ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Calculating from Recon…</span>
                </>
              ) : table4Applied ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Re-sync Table 4</span>
                </>
              ) : (
                <>
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>Auto-populate Table 4</span>
                </>
              )}
            </button>
          </div>

          {(table4Result?.available || table4Result?.status === "available") && table4Result.summary ? (
            <div className="mt-3 border-t border-emerald-200/60 pt-3">
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className="rounded-md bg-emerald-100/90 px-2 py-0.5 font-medium text-emerald-900">
                  Available ITC: ₹{table4Result.summary.itc_available_tax.toLocaleString("en-IN")}
                </span>
                <span className="rounded-md bg-amber-100/90 px-2 py-0.5 font-medium text-amber-900">
                  Reversals (Rule 37): ₹{table4Result.summary.itc_reversed_tax.toLocaleString("en-IN")}
                </span>
                <span className="rounded-md bg-teal-100/90 px-2 py-0.5 font-semibold text-teal-950">
                  Net ITC: ₹{table4Result.summary.net_itc_tax.toLocaleString("en-IN")}
                </span>
                {table4Result.summary.ineligible_tax > 0 ? (
                  <span className="rounded-md bg-rose-100/90 px-2 py-0.5 font-medium text-rose-900">
                    Ineligible (16(4)/17(5)): ₹{table4Result.summary.ineligible_tax.toLocaleString("en-IN")}
                  </span>
                ) : null}
                {table4Result.run_id ? (
                  <span className="font-mono text-[10px] text-emerald-700">
                    Run #{table4Result.run_id.slice(0, 8)}
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}

          {table4Result && (!table4Result.available || table4Result.status === "unavailable") ? (
            <div className="mt-3 flex items-center gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-[12px] text-amber-800 border border-amber-200">
              <AlertCircle className="h-4 w-4 shrink-0 text-amber-600" />
              <span>
                {table4Result.reason === "no_gstr2b_reconcile_run"
                  ? "No reconciliation run found for this period. Run reconciliation first to auto-calculate Table 4, or enter values manually."
                  : "No invoice records found in reconciliation for this period. Enter values manually."}
              </span>
            </div>
          ) : null}

          {table4Error ? (
            <div className="mt-3 flex items-center gap-1.5 rounded-lg bg-rose-50 px-3 py-2 text-[12px] text-rose-800 border border-rose-200">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
              <span>{table4Error}</span>
            </div>
          ) : null}
        </div>
      ) : null}

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
