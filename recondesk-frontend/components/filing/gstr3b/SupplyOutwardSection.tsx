"use client";

import { useCallback, useState } from "react";

import { DraftSuggestionBanner } from "@/components/filing/gstr3b/DraftSuggestionBanner";
import {
  type Gstr3bFiguresState,
  type OutwardSuggestion,
  type RcmSuggestion,
  type SuggestionLoadResult,
  type Gstr3bTaxHeadFields,
} from "@/components/filing/gstr3b/figuresModel";
import {
  TaxHeadTable,
  parseAmountInput,
} from "@/components/filing/gstr3b/TaxHeadTable";

type Props = {
  value: Gstr3bFiguresState["sup_details"];
  onChange: (next: Gstr3bFiguresState["sup_details"]) => void;
  /** Explicit load only — never auto-runs on mount. */
  onLoadOutwardSuggestion: () => Promise<SuggestionLoadResult<OutwardSuggestion>>;
  onLoadRcmSuggestion?: () => Promise<SuggestionLoadResult<RcmSuggestion>>;
};

const UNAVAILABLE_HINTS: Record<string, string> = {
  no_gstr1_reconcile_run:
    "No GSTR-1 reconcile run for this period — suggestions unavailable. This does not mean the figure is zero; enter the amount from the books.",
  no_gstr1_aggregate:
    "GSTR-1 reconcile has no 3.1(a) aggregate for this period — suggestions unavailable. This does not mean the figure is zero; enter the amount from the books.",
  no_rcm_inward_supplies:
    "No reverse charge inward supplies detected in the Purchase Register for this period.",
};

export function SupplyOutwardSection({
  value,
  onChange,
  onLoadOutwardSuggestion,
  onLoadRcmSuggestion,
}: Props) {
  const [suggestion, setSuggestion] = useState<OutwardSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(false);
  const [emptyHint, setEmptyHint] = useState<string | null>(null);

  const [rcmSuggestion, setRcmSuggestion] = useState<RcmSuggestion | null>(null);
  const [rcmBusy, setRcmBusy] = useState(false);
  const [rcmApplied, setRcmApplied] = useState(false);
  const [rcmEmptyHint, setRcmEmptyHint] = useState<string | null>(null);

  const patchRow = useCallback(
    (rowKey: string, field: keyof Gstr3bTaxHeadFields, raw: string) => {
      const parsed = parseAmountInput(raw);
      onChange({
        ...value,
        [rowKey]: { ...value[rowKey as keyof typeof value], [field]: parsed },
      });
    },
    [onChange, value]
  );

  const load = useCallback(async () => {
    setBusy(true);
    setEmptyHint(null);
    setApplied(false);
    try {
      const result = await onLoadOutwardSuggestion();
      if (result.status === "unavailable") {
        setSuggestion(null);
        setEmptyHint(
          UNAVAILABLE_HINTS[result.reason] ||
            "No outward suggestion available for this period. This does not mean the figure is zero; enter the amount from the books."
        );
        return;
      }
      setSuggestion(result.suggestion);
      setEmptyHint(null);
    } catch {
      setSuggestion(null);
      setEmptyHint(
        "Could not load GSTR-1 suggestions. Try again, or enter the amount from the books."
      );
    } finally {
      setBusy(false);
    }
  }, [onLoadOutwardSuggestion]);

  const loadRcm = useCallback(async () => {
    if (!onLoadRcmSuggestion) return;
    setRcmBusy(true);
    setRcmEmptyHint(null);
    setRcmApplied(false);
    try {
      const result = await onLoadRcmSuggestion();
      if (result.status === "unavailable") {
        setRcmSuggestion(null);
        setRcmEmptyHint(
          UNAVAILABLE_HINTS[result.reason] ||
            "No RCM inward supply suggestions available for this period."
        );
        return;
      }
      setRcmSuggestion(result.suggestion);
      setRcmEmptyHint(null);
    } catch {
      setRcmSuggestion(null);
      setRcmEmptyHint(
        "Could not load Purchase Register RCM suggestions. Try again, or enter the amount from the books."
      );
    } finally {
      setRcmBusy(false);
    }
  }, [onLoadRcmSuggestion]);

  const det = value.osup_det;
  const sug = suggestion?.osup_det || {};
  const differs =
    !!suggestion &&
    (["txval", "iamt", "camt", "samt", "csamt"] as const).some((k) => {
      const sv = sug[k];
      if (sv == null) return false;
      return Number(det[k] === "" ? NaN : det[k]) !== Number(sv);
    });

  const revDet = value.isup_rev;
  const rcmSug = rcmSuggestion?.isup_rev || {};
  const rcmDiffers =
    !!rcmSuggestion &&
    (["txval", "iamt", "camt", "samt", "csamt"] as const).some((k) => {
      const sv = rcmSug[k];
      if (sv == null) return false;
      return Number(revDet[k] === "" ? NaN : revDet[k]) !== Number(sv);
    });

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[14px] font-semibold text-[var(--ink)]">
          Table 3.1 — Outward & reverse charge
        </h3>
        <p className="mt-0.5 text-[12px] text-gray-500">
          Enter what you will declare. Suggestions from GSTR-1 and Purchase Register RCM are optional and
          never auto-applied.
        </p>
      </div>

      <TaxHeadTable
        rows={[
          { key: "osup_det", label: "3.1(a) Outward taxable", values: value.osup_det },
          { key: "osup_zero", label: "3.1(b) Zero-rated", values: value.osup_zero },
          {
            key: "osup_nil_exmp",
            label: "3.1(c) Nil / exempt",
            values: value.osup_nil_exmp,
          },
          { key: "osup_nongst", label: "3.1(e) Non-GST", values: value.osup_nongst },
          {
            key: "isup_rev",
            label: "3.1(d) Inward reverse charge",
            values: value.isup_rev,
          },
        ]}
        onChange={patchRow}
      />

      <DraftSuggestionBanner
        sourceLabel={suggestion?.source || "GSTR-1 Table 3.1(a)"}
        values={{
          txval: typeof sug.txval === "number" ? sug.txval : undefined,
          iamt: typeof sug.iamt === "number" ? sug.iamt : undefined,
          camt: typeof sug.camt === "number" ? sug.camt : undefined,
          samt: typeof sug.samt === "number" ? sug.samt : undefined,
          csamt: typeof sug.csamt === "number" ? sug.csamt : undefined,
        }}
        fieldLabels={{
          txval: "Taxable",
          iamt: "IGST",
          camt: "CGST",
          samt: "SGST",
          csamt: "Cess",
        }}
        applied={applied}
        differsFromInput={differs && !applied}
        busy={busy}
        emptyHint={emptyHint}
        onLoad={() => void load()}
        loadLabel="Load suggestions (GSTR-1 3.1(a))"
        onUse={() => {
          if (!suggestion) return;
          onChange({
            ...value,
            osup_det: {
              txval: sug.txval ?? "",
              iamt: sug.iamt ?? "",
              camt: sug.camt ?? "",
              samt: sug.samt ?? "",
              csamt: sug.csamt ?? "",
            },
          });
          setApplied(true);
        }}
        onDismiss={() => {
          setSuggestion(null);
          setApplied(false);
          setEmptyHint(null);
        }}
      />

      {onLoadRcmSuggestion && (
        <DraftSuggestionBanner
          sourceLabel={
            rcmSuggestion
              ? `${rcmSuggestion.source}${rcmSuggestion.inward_rcm_count ? ` (${rcmSuggestion.inward_rcm_count} invoices)` : ""} — Note: Sec 49(4) Cash ledger discharge required`
              : "Purchase Register Table 3.1(d) (RCM Inward Supplies)"
          }
          values={{
            txval: typeof rcmSug.txval === "number" ? rcmSug.txval : undefined,
            iamt: typeof rcmSug.iamt === "number" ? rcmSug.iamt : undefined,
            camt: typeof rcmSug.camt === "number" ? rcmSug.camt : undefined,
            samt: typeof rcmSug.samt === "number" ? rcmSug.samt : undefined,
            csamt: typeof rcmSug.csamt === "number" ? rcmSug.csamt : undefined,
          }}
          fieldLabels={{
            txval: "Taxable",
            iamt: "IGST",
            camt: "CGST",
            samt: "SGST",
            csamt: "Cess",
          }}
          applied={rcmApplied}
          differsFromInput={rcmDiffers && !rcmApplied}
          busy={rcmBusy}
          emptyHint={rcmEmptyHint}
          onLoad={() => void loadRcm()}
          loadLabel="Load suggestions (Table 3.1(d) RCM)"
          onUse={() => {
            if (!rcmSuggestion) return;
            onChange({
              ...value,
              isup_rev: {
                txval: rcmSug.txval ?? "",
                iamt: rcmSug.iamt ?? "",
                camt: rcmSug.camt ?? "",
                samt: rcmSug.samt ?? "",
                csamt: rcmSug.csamt ?? "",
              },
            });
            setRcmApplied(true);
          }}
          onDismiss={() => {
            setRcmSuggestion(null);
            setRcmApplied(false);
            setRcmEmptyHint(null);
          }}
        />
      )}
    </div>
  );
}
