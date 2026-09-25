"use client";

import { useCallback, useEffect, useState } from "react";

import { ItcEligibilitySection } from "@/components/filing/gstr3b/ItcEligibilitySection";
import { SupplyOutwardSection } from "@/components/filing/gstr3b/SupplyOutwardSection";
import {
  emptyGstr3bFigures,
  figuresToSaveBody,
  type Gstr3bFiguresState,
  type ItcOthSuggestion,
  type OutwardSuggestion,
  type SuggestionLoadResult,
} from "@/components/filing/gstr3b/figuresModel";
import { parseAmountInput } from "@/components/filing/gstr3b/TaxHeadTable";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { type Gstr3bTable4SuggestionResponse } from "@/lib/api";

type Props = {
  gstin: string;
  /** MMYYYY ret_period */
  retPeriod: string;
  value: Gstr3bFiguresState;
  onChange: (next: Gstr3bFiguresState) => void;
  onLoadOutwardSuggestion: () => Promise<SuggestionLoadResult<OutwardSuggestion>>;
  onLoadOthSuggestion: () => Promise<SuggestionLoadResult<ItcOthSuggestion>>;
  onLoadTable4Suggestion?: () => Promise<Gstr3bTable4SuggestionResponse>;
  readOnly?: boolean;
};

export function Gstr3bFiguresForm({
  gstin,
  retPeriod,
  value,
  onChange,
  onLoadOutwardSuggestion,
  onLoadOthSuggestion,
  onLoadTable4Suggestion,
  readOnly,
}: Props) {
  useEffect(() => {
    if (value.gstin !== gstin || value.ret_period !== retPeriod) {
      onChange({ ...value, gstin, ret_period: retPeriod });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync identity fields only
  }, [gstin, retPeriod]);

  return (
    <section className={sectionContainerClass} aria-label="GSTR-3B figures">
      <SectionHeader title="Confirm GSTR-3B figures" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        CA-owned numbers for Save. Optional drafts load only when you click
        Load suggestions — never on page open.
      </p>

      <div
        className={`mt-6 space-y-10 ${readOnly ? "pointer-events-none opacity-60" : ""}`}
      >
        <SupplyOutwardSection
          value={value.sup_details}
          onChange={(sup_details) => onChange({ ...value, sup_details })}
          onLoadOutwardSuggestion={onLoadOutwardSuggestion}
        />
        <ItcEligibilitySection
          value={value.itc_elg}
          onChange={(itc_elg) => onChange({ ...value, itc_elg })}
          onLoadOthSuggestion={onLoadOthSuggestion}
          onLoadTable4Suggestion={onLoadTable4Suggestion}
        />
        <InwardAndInterestSections value={value} onChange={onChange} readOnly={readOnly} />
      </div>
    </section>
  );
}

function InwardAndInterestSections({
  value,
  onChange,
  readOnly,
}: {
  value: Gstr3bFiguresState;
  onChange: (next: Gstr3bFiguresState) => void;
  readOnly?: boolean;
}) {
  const patchInward = useCallback(
    (index: number, field: "inter" | "intra", raw: string) => {
      const rows = [...value.inward_sup.isup_details];
      rows[index] = { ...rows[index], [field]: parseAmountInput(raw) };
      onChange({
        ...value,
        inward_sup: { ...value.inward_sup, isup_details: rows },
      });
    },
    [onChange, value]
  );

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-[14px] font-semibold text-[var(--ink)]">
          Inward supplies (isup_details)
        </h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full max-w-lg border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-[#E8E8EA] text-[11px] uppercase text-gray-400">
                <th className="py-2 text-left">Type</th>
                <th className="px-1 py-2">Inter</th>
                <th className="px-1 py-2">Intra</th>
              </tr>
            </thead>
            <tbody>
              {value.inward_sup.isup_details.map((row, i) => (
                <tr key={row.ty} className="border-b border-[#F0F0F2]">
                  <td className="py-2 font-mono text-[12px]">{row.ty}</td>
                  {(["inter", "intra"] as const).map((f) => (
                    <td key={f} className="px-1 py-1.5">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={row[f] === "" ? "" : String(row[f])}
                        onChange={(e) => patchInward(i, f, e.target.value)}
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

      <div>
        <h3 className="text-[14px] font-semibold text-[var(--ink)]">
          Interest & late fee
        </h3>
        <p className="mt-0.5 text-[12px] text-gray-500">
          Leave blank when nil.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(
            [
              ["intr_details", "iamt", "Interest IGST"],
              ["intr_details", "camt", "Interest CGST"],
              ["intr_details", "samt", "Interest SGST"],
              ["intr_details", "csamt", "Interest Cess"],
              ["ltfee_details", "camt", "Late fee CGST"],
              ["ltfee_details", "samt", "Late fee SGST"],
            ] as const
          ).map(([block, field, label]) => {
            const blockVal = value.intr_ltfee[block] as Record<
              string,
              number | ""
            >;
            const isLtfee = block === "ltfee_details";
            const isDisabled = readOnly || isLtfee;
            return (
              <label key={`${block}-${field}`} className="block">
                <span className="text-[11px] font-medium text-gray-500">
                  {label} {isLtfee ? "(GSTN System)" : ""}
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  readOnly={isDisabled}
                  disabled={isDisabled}
                  title={isLtfee ? "Late fee is system-calculated by GSTN" : undefined}
                  value={
                    blockVal[field] === "" ? "" : String(blockVal[field])
                  }
                  onChange={(e) => {
                    if (isLtfee) return;
                    onChange({
                      ...value,
                      intr_ltfee: {
                        ...value.intr_ltfee,
                        [block]: {
                          ...value.intr_ltfee[block],
                          [field]: parseAmountInput(e.target.value),
                        },
                      },
                    });
                  }}
                  className={`mt-1 h-9 w-full rounded-full border-0 px-3.5 text-[12px] font-medium outline-none focus:ring-2 focus:ring-black/10 ${
                    isDisabled
                      ? "bg-gray-200/60 text-gray-500 cursor-not-allowed"
                      : "bg-[#F5F5F6] text-[var(--ink)]"
                  }`}
                />
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function useGstr3bFigures(gstin: string, retPeriod: string) {
  const [figures, setFigures] = useState(() =>
    emptyGstr3bFigures(gstin, retPeriod)
  );
  return {
    figures,
    setFigures,
    saveBody: () => figuresToSaveBody(figures),
  };
}
