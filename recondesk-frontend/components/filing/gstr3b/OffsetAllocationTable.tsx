"use client";

import type { ReactNode } from "react";

import type { Gstr3bPdcashRow, Gstr3bPditc } from "@/lib/api";
import { formatInr } from "@/components/filing/gstr3b/offsetConfirmLogic";

type Props = {
  pdcash: Gstr3bPdcashRow[];
  pditc: Gstr3bPditc;
};

export function OffsetAllocationTable({ pdcash, pditc }: Props) {
  return (
    <div className="space-y-4 font-mono text-[12px] text-[#E8E4DC]">
      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#A89F90]">
          pdcash — exact rows GSTN will receive
        </p>
        <div className="overflow-x-auto rounded border border-[#3A3630] bg-[#12100E]">
          <table className="w-full min-w-[40rem] border-collapse">
            <thead>
              <tr className="border-b border-[#3A3630] text-left text-[10px] uppercase text-[#8A8278]">
                <th className="px-2 py-2">#</th>
                <th className="px-2 py-2">liab_ldg_id</th>
                <th className="px-2 py-2">trans_typ</th>
                <th className="px-2 py-2">ipd</th>
                <th className="px-2 py-2">cpd</th>
                <th className="px-2 py-2">spd</th>
                <th className="px-2 py-2">cspd</th>
              </tr>
            </thead>
            <tbody>
              {pdcash.map((row, i) => (
                <tr key={i} className="border-b border-[#2A2722]">
                  <td className="px-2 py-1.5 text-[#8A8278]">{i}</td>
                  <td className="px-2 py-1.5">{String(row.liab_ldg_id)}</td>
                  <td className="px-2 py-1.5">{String(row.trans_typ)}</td>
                  <td className="px-2 py-1.5">{formatCell(row.ipd)}</td>
                  <td className="px-2 py-1.5">{formatCell(row.cpd)}</td>
                  <td className="px-2 py-1.5">{formatCell(row.spd)}</td>
                  <td className="px-2 py-1.5">{formatCell(row.cspd)}</td>
                </tr>
              ))}
              {pdcash.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-2 py-3 text-[#8A8278]">
                    (empty pdcash)
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#A89F90]">
          pditc — exact object GSTN will receive
        </p>
        <div className="rounded border border-[#3A3630] bg-[#12100E] px-3 py-3">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            {(
              [
                "liab_ldg_id",
                "trans_typ",
                "i_pdi",
                "i_pdc",
                "i_pds",
                "c_pdi",
                "c_pdc",
                "s_pdi",
                "s_pds",
                "cs_pdcs",
              ] as const
            ).map((k) => (
              <div key={k} className="flex justify-between gap-2">
                <dt className="text-[#8A8278]">{k}</dt>
                <dd className="text-[#E8E4DC]">{formatCell(pditc[k])}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return formatInr(v).replace("₹", "").trim();
  return String(v);
}

export function LedgerVsPayablePanel({
  details,
  ledger,
  cashTotal,
  itcTotal,
}: {
  details: Record<string, unknown>;
  ledger: Record<string, unknown>;
  cashTotal: number;
  itcTotal: number;
}) {
  const txPmt =
    details.tx_pmt && typeof details.tx_pmt === "object"
      ? (details.tx_pmt as Record<string, unknown>)
      : {};
  const net = Array.isArray(txPmt.net_tax_pay) ? txPmt.net_tax_pay : [];
  const itcBal =
    ledger.itc_bal && typeof ledger.itc_bal === "object"
      ? (ledger.itc_bal as Record<string, unknown>)
      : {};
  const cashBal =
    ledger.cash_bal && typeof ledger.cash_bal === "object"
      ? (ledger.cash_bal as Record<string, unknown>)
      : {};

  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <MiniCol title="Tax payable (Get Details)">
        {net.length === 0 ? (
          <p className="text-[#8A8278]">No net_tax_pay in details</p>
        ) : (
          net.map((row, i) => {
            if (!row || typeof row !== "object") return null;
            const r = row as Record<string, unknown>;
            return (
              <p key={i} className="leading-relaxed">
                typ {String(r.trans_typ)} · I{" "}
                {headTx(r.igst)} / C {headTx(r.cgst)} / S {headTx(r.sgst)}
              </p>
            );
          })
        )}
      </MiniCol>
      <MiniCol title="Ledger available">
        <p>
          ITC I/C/S: {num(itcBal.igst_bal)} / {num(itcBal.cgst_bal)} /{" "}
          {num(itcBal.sgst_bal)}
        </p>
        <p className="mt-1">
          Cash I/C/S: {cashHead(cashBal.igst)} / {cashHead(cashBal.cgst)} /{" "}
          {cashHead(cashBal.sgst)}
        </p>
      </MiniCol>
      <MiniCol title="This offset (preview)">
        <p>Cash outflow: {formatInr(cashTotal)}</p>
        <p className="mt-1">ITC utilised: {formatInr(itcTotal)}</p>
      </MiniCol>
    </div>
  );
}

function MiniCol({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded border border-[#3A3630] bg-[#16140F] px-3 py-3 font-mono text-[11px] text-[#E8E4DC]">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#A89F90]">
        {title}
      </p>
      {children}
    </div>
  );
}

function headTx(v: unknown): string {
  if (v && typeof v === "object" && "tx" in v) {
    return String((v as { tx: unknown }).tx ?? 0);
  }
  return "0";
}

function cashHead(v: unknown): string {
  if (v && typeof v === "object" && "tx" in v) {
    return String((v as { tx: unknown }).tx ?? 0);
  }
  return "0";
}

function num(v: unknown): string {
  return v == null ? "0" : String(v);
}
