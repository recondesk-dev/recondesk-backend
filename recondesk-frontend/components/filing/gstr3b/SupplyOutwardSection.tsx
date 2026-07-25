"use client";

import { useCallback, useState } from "react";

import { DraftSuggestionBanner } from "@/components/filing/gstr3b/DraftSuggestionBanner";
import {
  type Gstr3bFiguresState,
  type OutwardSuggestion,
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
  onLoadOutwardSuggestion: () => Promise<OutwardSuggestion | null>;
};

export function SupplyOutwardSection({
  value,
  onChange,
  onLoadOutwardSuggestion,
}: Props) {
  const [suggestion, setSuggestion] = useState<OutwardSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(false);
  const [loadNote, setLoadNote] = useState<string | null>(null);

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
    setLoadNote(null);
    setApplied(false);
    try {
      const s = await onLoadOutwardSuggestion();
      if (!s) {
        setSuggestion(null);
        setLoadNote(
          "Suggestions not yet available in this build — GSTR-1 wiring is pending. This does not mean the figure is zero; enter the amount from the books."
        );
        return;
      }
      setSuggestion(s);
    } finally {
      setBusy(false);
    }
  }, [onLoadOutwardSuggestion]);

  const det = value.osup_det;
  const sug = suggestion?.osup_det || {};
  const differs =
    !!suggestion &&
    (["txval", "iamt", "camt", "samt", "csamt"] as const).some((k) => {
      const sv = sug[k];
      if (sv == null) return false;
      return Number(det[k] === "" ? NaN : det[k]) !== Number(sv);
    });

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[14px] font-semibold text-[var(--ink)]">
          Table 3.1 — Outward & reverse charge
        </h3>
        <p className="mt-0.5 text-[12px] text-gray-500">
          Enter what you will declare. Suggestions from GSTR-1 are optional and
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
        }}
      />
      {loadNote ? (
        <p className="text-[12px] text-gray-500">{loadNote}</p>
      ) : null}
    </div>
  );
}
