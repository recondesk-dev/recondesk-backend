"use client";

import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { downloadBlobAsFile } from "@/lib/download";
import {
  buildDrc01bLiabilityRows,
  buildDrc01bReplyDraft,
  buildDrc01bReplyPdfBlob,
  DRC01B_REASON_OPTIONS,
  drc01bPdfFilename,
  getDrc01bReasonOption,
  type Drc01bReasonCategory,
  type Drc03DraftFields,
} from "@/lib/drc01bReplyDraft";
import { formatINR } from "@/lib/format";
import type { Gstr1TieOut } from "@/lib/gstr1Reconcile";

const DISCLAIMER_MODAL =
  "This is a system-generated DRC-01B Part B reply draft. Please review before using on the GST portal. It does not constitute legal advice and is not submitted automatically.";

export function Drc01bReplyDraftModal({
  open,
  onClose,
  tieOut,
  clientName,
  clientGstin,
}: {
  open: boolean;
  onClose: () => void;
  tieOut: Gstr1TieOut;
  clientName: string;
  clientGstin: string;
}) {
  const rows = useMemo(() => buildDrc01bLiabilityRows(tieOut), [tieOut]);
  const retPeriod = tieOut.ret_period || "—";

  const [reasonCategory, setReasonCategory] = useState<Drc01bReasonCategory | "">(
    ""
  );
  const [narrative, setNarrative] = useState("");
  const [drc03Paid, setDrc03Paid] = useState<"" | "yes" | "no">("");
  const [drc03Arn, setDrc03Arn] = useState("");
  const [drc03Date, setDrc03Date] = useState("");
  const [drc03Amount, setDrc03Amount] = useState("");
  const [body, setBody] = useState("");
  const [copyOk, setCopyOk] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const drc03: Drc03DraftFields = useMemo(
    () => ({
      paid: drc03Paid === "yes" ? true : drc03Paid === "no" ? false : null,
      arn: drc03Arn,
      date: drc03Date,
      amount: drc03Amount,
    }),
    [drc03Paid, drc03Arn, drc03Date, drc03Amount]
  );

  // Rebuild draft when inputs change (editable textarea still allows free edits;
  // regenerating on control changes keeps Part A / reason / DRC-03 in sync).
  useEffect(() => {
    if (!open) return;
    setBody(
      buildDrc01bReplyDraft({
        clientName,
        clientGstin,
        retPeriod,
        rows,
        reasonCategory,
        narrative,
        drc03,
      })
    );
  }, [
    open,
    clientName,
    clientGstin,
    retPeriod,
    rows,
    reasonCategory,
    narrative,
    drc03,
  ]);

  useEffect(() => {
    if (!open) {
      setReasonCategory("");
      setNarrative("");
      setDrc03Paid("");
      setDrc03Arn("");
      setDrc03Date("");
      setDrc03Amount("");
      setBody("");
      setCopyOk(false);
      setError(null);
    }
  }, [open]);

  const handleReasonChange = (id: Drc01bReasonCategory | "") => {
    setReasonCategory(id);
    const opt = getDrc01bReasonOption(id);
    if (opt) setNarrative(opt.narrativeStub);
    else setNarrative("");
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(body);
      setCopyOk(true);
      window.setTimeout(() => setCopyOk(false), 2000);
      setError(null);
    } catch {
      setError("Clipboard unavailable");
    }
  };

  const handleDownloadPdf = async () => {
    setError(null);
    try {
      const blob = await buildDrc01bReplyPdfBlob(body, DISCLAIMER_MODAL);
      downloadBlobAsFile(blob, drc01bPdfFilename(clientGstin, retPeriod));
    } catch {
      setError("Could not generate PDF. Please try again or use Copy message.");
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="drc01b-draft-title"
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#F0F0F0] px-5 py-4">
          <div className="min-w-0">
            <h2
              id="drc01b-draft-title"
              className="text-lg font-semibold text-gray-900"
            >
              DRC-01B Part B reply draft
            </h2>
            <p className="mt-0.5 text-[12px] text-gray-500">
              Scaffold only — not submitted to the GST portal
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-gray-500 hover:bg-gray-100"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div className="grid gap-3 text-[13px] sm:grid-cols-2">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                Client
              </p>
              <p className="font-medium text-gray-900">{clientName || "—"}</p>
              <p className="font-mono text-gray-500">{clientGstin || "—"}</p>
            </div>
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                Return period
              </p>
              <p className="font-medium text-gray-900">{retPeriod}</p>
            </div>
          </div>

          <div>
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-gray-400">
              Part A summary (declared totals — not liability paid)
            </p>
            <p className="mb-2 text-[12px] text-amber-800">
              GSTR-1 aggregates vs GSTR-3B Table 3.1(a) declared outward supply.
              Verify portal Part A and actual payment records before filing.
            </p>
            <div className="overflow-x-auto rounded-xl border border-[#E5E7EB]">
              <table className="w-full border-collapse text-left text-[12px]">
                <thead>
                  <tr className="border-b border-[#F0F0F0] bg-[#FAFAFB] text-[11px] font-medium uppercase tracking-wide text-gray-400">
                    <th className="px-3 py-2">Head</th>
                    <th className="px-3 py-2 text-right">GSTR-1</th>
                    <th className="px-3 py-2 text-right">GSTR-3B 3.1(a)</th>
                    <th className="px-3 py-2 text-right">Diff</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key} className="border-b border-[#F0F0F0] last:border-b-0">
                      <td className="px-3 py-2 font-medium text-gray-800">
                        {r.label}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                        {formatINR(r.gstr1Rupees)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                        {formatINR(r.gstr3bRupees)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-gray-800">
                        {formatINR(r.diffRupees)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <label
              htmlFor="drc01b-reason"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-400"
            >
              Part B reason (portal options)
            </label>
            <select
              id="drc01b-reason"
              value={reasonCategory}
              onChange={(e) =>
                handleReasonChange(e.target.value as Drc01bReasonCategory | "")
              }
              className="w-full rounded-xl border border-[#E5E7EB] bg-white px-3 py-2 text-[13px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            >
              <option value="">Select a reason…</option>
              {DRC01B_REASON_OPTIONS.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label.length > 120
                    ? `${opt.label.slice(0, 117)}…`
                    : opt.label}
                </option>
              ))}
            </select>
            {reasonCategory ? (
              <p className="mt-1 text-[11px] leading-snug text-gray-500">
                {getDrc01bReasonOption(reasonCategory)?.label}
              </p>
            ) : null}
          </div>

          <div>
            <label
              htmlFor="drc01b-narrative"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-400"
            >
              Narrative / details (editable · portal limit ~500 chars)
            </label>
            <textarea
              id="drc01b-narrative"
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              rows={4}
              className="w-full resize-y rounded-xl border border-[#E5E7EB] px-3 py-2 text-[13px] leading-relaxed text-gray-800 outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
              placeholder="Select a reason to seed a starter, then edit for your facts."
            />
            <p className="mt-1 text-[11px] text-gray-400">
              {narrative.length} characters
            </p>
          </div>

          <div className="rounded-xl border border-[#F0F0F0] bg-[#FAFAFB] px-4 py-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
              Optional — DRC-03 payment (Part B sub-part A)
            </p>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              <div>
                <label
                  htmlFor="drc03-paid"
                  className="mb-1 block text-[12px] text-gray-600"
                >
                  Differential liability paid via DRC-03?
                </label>
                <select
                  id="drc03-paid"
                  value={drc03Paid}
                  onChange={(e) =>
                    setDrc03Paid(e.target.value as "" | "yes" | "no")
                  }
                  className="w-full rounded-xl border border-[#E5E7EB] bg-white px-3 py-2 text-[13px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                >
                  <option value="">Not indicated</option>
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </div>
              {drc03Paid === "yes" ? (
                <>
                  <div>
                    <label
                      htmlFor="drc03-arn"
                      className="mb-1 block text-[12px] text-gray-600"
                    >
                      DRC-03 ARN
                    </label>
                    <input
                      id="drc03-arn"
                      type="text"
                      value={drc03Arn}
                      onChange={(e) => setDrc03Arn(e.target.value)}
                      className="w-full rounded-xl border border-[#E5E7EB] bg-white px-3 py-2 font-mono text-[13px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                      placeholder="Portal ARN"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="drc03-date"
                      className="mb-1 block text-[12px] text-gray-600"
                    >
                      Date
                    </label>
                    <input
                      id="drc03-date"
                      type="date"
                      value={drc03Date}
                      onChange={(e) => setDrc03Date(e.target.value)}
                      className="w-full rounded-xl border border-[#E5E7EB] bg-white px-3 py-2 text-[13px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="drc03-amount"
                      className="mb-1 block text-[12px] text-gray-600"
                    >
                      Amount (₹)
                    </label>
                    <input
                      id="drc03-amount"
                      type="text"
                      inputMode="decimal"
                      value={drc03Amount}
                      onChange={(e) => setDrc03Amount(e.target.value)}
                      className="w-full rounded-xl border border-[#E5E7EB] bg-white px-3 py-2 text-[13px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                      placeholder="e.g. 12500.00"
                    />
                  </div>
                </>
              ) : null}
            </div>
            <p className="mt-2 text-[11px] text-gray-500">
              No ARN validation — enter values for the draft only.
            </p>
          </div>

          <p className="text-[12px] text-gray-500">{DISCLAIMER_MODAL}</p>
          <p className="text-[12px] text-gray-500">
            Changing reason, narrative, or DRC-03 fields regenerates the draft
            below. Make final wording edits in the draft last, then Copy or
            Download.
          </p>

          <div>
            <label
              htmlFor="drc01b-body"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-400"
            >
              Full draft (editable)
            </label>
            <textarea
              id="drc01b-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={14}
              className="w-full resize-y rounded-xl border border-[#E5E7EB] px-3 py-2 font-mono text-[12px] leading-relaxed text-gray-800 outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </div>

          {error ? <p className="text-[13px] text-red-600">{error}</p> : null}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[#F0F0F0] px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50"
          >
            {copyOk ? "Copied!" : "Copy message"}
          </button>
          <button
            type="button"
            onClick={() => void handleDownloadPdf()}
            className="rounded-xl bg-brand px-4 py-2 text-[13px] font-semibold text-white hover:bg-brand-hover"
          >
            Download PDF
          </button>
        </div>
      </div>
    </div>
  );
}
