"use client";

import type { Gstr3bTaxHeadFields } from "@/components/filing/gstr3b/figuresModel";

const COLS: { key: keyof Gstr3bTaxHeadFields; label: string }[] = [
  { key: "txval", label: "Taxable" },
  { key: "iamt", label: "IGST" },
  { key: "camt", label: "CGST" },
  { key: "samt", label: "SGST" },
  { key: "csamt", label: "Cess" },
];

type RowDef = {
  key: string;
  label: string;
  values: Gstr3bTaxHeadFields;
};

type Props = {
  rows: RowDef[];
  onChange: (
    rowKey: string,
    field: keyof Gstr3bTaxHeadFields,
    value: string
  ) => void;
  readOnly?: boolean;
};

export function TaxHeadTable({ rows, onChange, readOnly }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] border-collapse text-left text-[13px]">
        <thead>
          <tr className="border-b border-[#E8E8EA] text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            <th className="py-2 pr-3 font-medium">Line</th>
            {COLS.map((c) => (
              <th key={c.key} className="px-1 py-2 font-medium">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-[#F0F0F2]">
              <td className="py-2 pr-3 text-[12px] font-medium text-[var(--ink)]">
                {row.label}
              </td>
              {COLS.map((c) => (
                <td key={c.key} className="px-1 py-1.5">
                  <input
                    type="text"
                    inputMode="decimal"
                    readOnly={readOnly}
                    value={
                      row.values[c.key] === "" ? "" : String(row.values[c.key])
                    }
                    onChange={(e) => onChange(row.key, c.key, e.target.value)}
                    className="h-9 w-full rounded-lg border-0 bg-[#F5F5F6] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:ring-2 focus:ring-black/10 read-only:opacity-60"
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function parseAmountInput(raw: string): number | "" {
  const s = raw.trim().replace(/,/g, "");
  if (!s) return "";
  const n = Number(s);
  return Number.isFinite(n) ? n : "";
}
