"use client";

import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Download,
  ExternalLink,
  FileCheck,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";

import { formatINR } from "@/lib/format";
import {
  analyzeNoticeDefense,
  downloadDefenseExcel,
  getMatchingRuns,
  parseNoticePdf,
  saveNoticeRecord,
  type MatchingReconRun,
  type NoticeDataInput,
  type NoticeDefenseResult,
} from "@/lib/noticeDefenseApi";

interface NoticeDefenseModalProps {
  open: boolean;
  onClose: () => void;
  clientId: string;
  clientName: string;
  clientGstin: string;
  onSaved?: () => void;
}

export function NoticeDefenseModal({
  open,
  onClose,
  clientId,
  clientName,
  clientGstin,
  onSaved,
}: NoticeDefenseModalProps) {
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Notice input state
  const [noticeData, setNoticeData] = useState<NoticeDataInput>({
    notice_reference: "",
    notice_type: "DRC-01C",
    tax_period: "",
    financial_year: "2023-24",
    issue_date: new Date().toISOString().split("T")[0],
    reply_due_date: "",
    issuing_authority: "Office of the Assistant Commissioner, GST",
    alleged_tax_demand: 500000,
    alleged_igst: 300000,
    alleged_cgst: 100000,
    alleged_sgst: 100000,
    alleged_cess: 0,
    discrepancy_category: "ITC_EXCESS_3B_VS_2B",
  });

  const [parsingPdf, setParsingPdf] = useState(false);
  const [parseNoticeMsg, setParseNoticeMsg] = useState<string | null>(null);

  // Step 2: Recon run matching
  const [matchingRuns, setMatchingRuns] = useState<MatchingReconRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(false);

  // Step 3: Analysis result
  const [analyzing, setAnalyzing] = useState(false);
  const [defenseResult, setDefenseResult] = useState<NoticeDefenseResult | null>(null);
  const [activeTab, setActiveTab] = useState<"summary" | "invoices" | "reply">("summary");
  const [copySuccess, setCopySuccess] = useState(false);
  const [downloadingExcel, setDownloadingExcel] = useState(false);
  const [savingNotice, setSavingNotice] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [certifiedByCa, setCertifiedByCa] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Reset when modal opens
  useEffect(() => {
    if (open) {
      setStep(1);
      setErrorMsg(null);
      setDefenseResult(null);
      setSaveSuccess(false);
      setCertifiedByCa(false);
    }
  }, [open]);

  if (!open) return null;

  // Handle PDF Upload & Auto-parsing
  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setParsingPdf(true);
    setErrorMsg(null);
    setParseNoticeMsg("Parsing notice document with AI OCR & regex extractor...");

    try {
      const res = await parseNoticePdf(file);
      if (res.success && res.notice) {
        const n = res.notice;
        setNoticeData((prev) => ({
          ...prev,
          notice_reference: n.notice_reference || prev.notice_reference,
          notice_type: n.notice_type || prev.notice_type,
          tax_period: n.tax_period || prev.tax_period,
          financial_year: n.financial_year || prev.financial_year,
          issue_date: n.issue_date || prev.issue_date,
          reply_due_date: n.reply_due_date || prev.reply_due_date,
          issuing_authority: n.issuing_authority || prev.issuing_authority,
          alleged_tax_demand: n.alleged_tax_demand || prev.alleged_tax_demand,
          alleged_igst: n.alleged_igst || prev.alleged_igst,
          alleged_cgst: n.alleged_cgst || prev.alleged_cgst,
          alleged_sgst: n.alleged_sgst || prev.alleged_sgst,
          alleged_cess: n.alleged_cess || prev.alleged_cess,
        }));
        setParseNoticeMsg(`Extracted ${n.notice_type || "Notice"} (${n.notice_reference || "Ref"}) successfully!`);
      }
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to parse PDF notice");
      setParseNoticeMsg(null);
    } finally {
      setParsingPdf(false);
    }
  }

  // Go to Step 2: Fetch runs
  async function handleProceedToRuns() {
    if (!noticeData.notice_reference.trim()) {
      setErrorMsg("Please specify the Notice Reference / DIN.");
      return;
    }
    setErrorMsg(null);
    setLoadingRuns(true);
    setStep(2);

    try {
      const res = await getMatchingRuns(clientId, noticeData.tax_period, noticeData.financial_year);
      setMatchingRuns(res.runs || []);
      if (res.runs && res.runs.length > 0) {
        setSelectedRunId(res.runs[0].id);
      }
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to load reconciliation runs");
    } finally {
      setLoadingRuns(false);
    }
  }

  // Go to Step 3: Run Defense Analysis
  async function handleRunDefense() {
    setAnalyzing(true);
    setErrorMsg(null);

    try {
      const res = await analyzeNoticeDefense(clientId, noticeData, selectedRunId);
      if (res.success && res.defense) {
        setDefenseResult(res.defense);
        setStep(3);
      } else {
        setErrorMsg("Failed to generate notice defense analysis");
      }
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to compute defense reconciliation");
    } finally {
      setAnalyzing(false);
    }
  }

  // Copy formal reply
  function handleCopyReply() {
    if (!defenseResult?.formal_reply_text) return;
    if (!certifiedByCa) {
      setErrorMsg("Please certify that you have reviewed the underlying vouchers and Table 4 figures prior to copying the formal reply.");
      return;
    }
    setErrorMsg(null);
    navigator.clipboard.writeText(defenseResult.formal_reply_text);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2500);
  }

  // Download Excel Annexure
  async function handleDownloadExcel() {
    if (!defenseResult) return;
    setDownloadingExcel(true);
    try {
      await downloadDefenseExcel(defenseResult);
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to download Excel annexure");
    } finally {
      setDownloadingExcel(false);
    }
  }

  // Save notice record to DB
  async function handleSaveNotice() {
    if (!defenseResult) return;
    setSavingNotice(true);
    try {
      await saveNoticeRecord({
        client_id: clientId,
        notice_data: noticeData,
        reconciliation_run_id: selectedRunId,
        defense_summary: defenseResult.defense_summary,
        invoices_schedule: defenseResult.invoices_schedule,
        formal_reply_text: defenseResult.formal_reply_text,
        status: "DEFENSE_READY",
      });
      setSaveSuccess(true);
      if (onSaved) onSaved();
      setTimeout(() => {
        onClose();
      }, 1500);
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to save notice record");
    } finally {
      setSavingNotice(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-5xl max-h-[92vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Top Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/80">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white flex items-center justify-center font-bold shadow-md shadow-indigo-100">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                Notice Defense & Reconciliation Engine
                <span className="text-xs px-2.5 py-0.5 rounded-full font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
                  Step {step} of 3
                </span>
              </h2>
              <p className="text-xs text-slate-500 font-medium">
                {clientName} • <span className="font-mono text-slate-700">{clientGstin}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200/60 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto flex-1 space-y-6">
          {errorMsg && (
            <div className="p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs font-medium flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* STEP 1: NOTICE INGESTION & DATA ENTRY */}
          {step === 1 && (
            <div className="space-y-6">
              {/* PDF Drag & Drop Banner */}
              <div className="border-2 border-dashed border-indigo-200 rounded-2xl p-6 bg-indigo-50/40 text-center hover:bg-indigo-50/70 transition-colors">
                <input
                  type="file"
                  id="notice-pdf-upload"
                  accept="application/pdf"
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={parsingPdf}
                />
                <label
                  htmlFor="notice-pdf-upload"
                  className="cursor-pointer flex flex-col items-center justify-center space-y-2"
                >
                  <div className="w-12 h-12 rounded-xl bg-white shadow-sm border border-indigo-100 flex items-center justify-center text-indigo-600">
                    {parsingPdf ? (
                      <Loader2 className="w-6 h-6 animate-spin" />
                    ) : (
                      <Upload className="w-6 h-6" />
                    )}
                  </div>
                  <div className="text-sm font-semibold text-slate-800">
                    {parsingPdf ? "Analyzing Notice PDF..." : "Upload Official Department Notice (PDF)"}
                  </div>
                  <p className="text-xs text-slate-500 max-w-md">
                    Drag and drop or browse your official notice (Form GST DRC-01C, ASMT-10, DRC-01B, DRC-01).
                    ReconDesk automatically extracts DIN, periods, and demand figures.
                  </p>
                </label>

                {parseNoticeMsg && (
                  <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {parseNoticeMsg}
                  </div>
                )}
              </div>

              {/* Notice Metadata Form */}
              <div className="bg-slate-50/60 p-5 rounded-xl border border-slate-200 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  Notice Details & Discrepancy Figures
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">
                      Notice Form / Type
                    </label>
                    <select
                      className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2.5 font-medium text-slate-800 focus:ring-2 focus:ring-indigo-500"
                      value={noticeData.notice_type}
                      onChange={(e) =>
                        setNoticeData({ ...noticeData, notice_type: e.target.value })
                      }
                    >
                      <option value="DRC-01C">Form GST DRC-01C (Rule 88D ITC Mismatch)</option>
                      <option value="ASMT-10">Form GST ASMT-10 (Section 61 Scrutiny)</option>
                      <option value="DRC-01B">Form GST DRC-01B (Rule 88C Liability Mismatch)</option>
                      <option value="DRC-01A">Form GST DRC-01A (Sec 73/74 Pre-SCN)</option>
                      <option value="DRC-01">Form GST DRC-01 (Show Cause Notice)</option>
                      <option value="OTHER">Other Department Notice / Letter</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">
                      Notice Reference / DIN *
                    </label>
                    <input
                      type="text"
                      className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2.5 font-mono text-slate-800 focus:ring-2 focus:ring-indigo-500"
                      placeholder="e.g. DIN202409250001"
                      value={noticeData.notice_reference}
                      onChange={(e) =>
                        setNoticeData({ ...noticeData, notice_reference: e.target.value })
                      }
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">
                      Tax Period / Month
                    </label>
                    <input
                      type="text"
                      className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2.5 font-medium text-slate-800 focus:ring-2 focus:ring-indigo-500"
                      placeholder="e.g. 032024 or March 2024"
                      value={noticeData.tax_period}
                      onChange={(e) =>
                        setNoticeData({ ...noticeData, tax_period: e.target.value })
                      }
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">
                      Notice Date
                    </label>
                    <input
                      type="date"
                      className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2.5 font-medium text-slate-800 focus:ring-2 focus:ring-indigo-500"
                      value={noticeData.issue_date}
                      onChange={(e) =>
                        setNoticeData({ ...noticeData, issue_date: e.target.value })
                      }
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">
                      Reply Due Date
                    </label>
                    <input
                      type="date"
                      className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2.5 font-medium text-slate-800 focus:ring-2 focus:ring-indigo-500"
                      value={noticeData.reply_due_date}
                      onChange={(e) =>
                        setNoticeData({ ...noticeData, reply_due_date: e.target.value })
                      }
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">
                      Issuing Authority
                    </label>
                    <input
                      type="text"
                      className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2.5 font-medium text-slate-800 focus:ring-2 focus:ring-indigo-500"
                      value={noticeData.issuing_authority}
                      onChange={(e) =>
                        setNoticeData({ ...noticeData, issuing_authority: e.target.value })
                      }
                    />
                  </div>
                </div>

                {/* Alleged Tax Demand Grid */}
                <div className="pt-2 border-t border-slate-200">
                  <label className="block text-xs font-bold text-slate-800 mb-2">
                    Department Alleged Discrepancy / Demand (₹)
                  </label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div>
                      <span className="text-[11px] text-slate-500 font-medium">IGST (₹)</span>
                      <input
                        type="number"
                        className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2 text-right font-mono"
                        value={noticeData.alleged_igst}
                        onChange={(e) => {
                          const v = parseFloat(e.target.value) || 0;
                          setNoticeData({
                            ...noticeData,
                            alleged_igst: v,
                            alleged_tax_demand: v + noticeData.alleged_cgst + noticeData.alleged_sgst,
                          });
                        }}
                      />
                    </div>
                    <div>
                      <span className="text-[11px] text-slate-500 font-medium">CGST (₹)</span>
                      <input
                        type="number"
                        className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2 text-right font-mono"
                        value={noticeData.alleged_cgst}
                        onChange={(e) => {
                          const v = parseFloat(e.target.value) || 0;
                          setNoticeData({
                            ...noticeData,
                            alleged_cgst: v,
                            alleged_tax_demand: noticeData.alleged_igst + v + noticeData.alleged_sgst,
                          });
                        }}
                      />
                    </div>
                    <div>
                      <span className="text-[11px] text-slate-500 font-medium">SGST (₹)</span>
                      <input
                        type="number"
                        className="w-full text-xs rounded-lg border border-slate-300 bg-white p-2 text-right font-mono"
                        value={noticeData.alleged_sgst}
                        onChange={(e) => {
                          const v = parseFloat(e.target.value) || 0;
                          setNoticeData({
                            ...noticeData,
                            alleged_sgst: v,
                            alleged_tax_demand: noticeData.alleged_igst + noticeData.alleged_cgst + v,
                          });
                        }}
                      />
                    </div>
                    <div>
                      <span className="text-[11px] font-bold text-indigo-900">Total Alleged Demand (₹)</span>
                      <input
                        type="number"
                        className="w-full text-xs rounded-lg border border-indigo-300 bg-indigo-50/50 p-2 text-right font-mono font-bold text-indigo-900"
                        value={noticeData.alleged_tax_demand}
                        onChange={(e) =>
                          setNoticeData({
                            ...noticeData,
                            alleged_tax_demand: parseFloat(e.target.value) || 0,
                          })
                        }
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: RECONCILIATION RUN LINKAGE */}
          {step === 2 && (
            <div className="space-y-4">
              <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">
                      Link with Reconciliation Run ({noticeData.tax_period || "All Periods"})
                    </h3>
                    <p className="text-xs text-slate-500">
                      Select the verified GSTR-2B ↔ Purchase Register run for this client to mathematically cross-examine the officer’s allegation.
                    </p>
                  </div>
                  <span className="text-xs font-semibold px-2.5 py-1 rounded bg-indigo-100 text-indigo-800">
                    Demand: {formatINR(noticeData.alleged_tax_demand)}
                  </span>
                </div>
              </div>

              {loadingRuns ? (
                <div className="py-12 flex flex-col items-center justify-center text-slate-400">
                  <Loader2 className="w-8 h-8 animate-spin mb-2 text-indigo-600" />
                  <p className="text-xs font-medium">Finding matching reconciliation workpapers...</p>
                </div>
              ) : matchingRuns.length === 0 ? (
                <div className="p-6 text-center border-2 border-dashed border-amber-200 rounded-2xl bg-amber-50/50 space-y-3">
                  <div className="w-12 h-12 rounded-xl bg-amber-100 text-amber-800 flex items-center justify-center mx-auto shadow-sm">
                    <AlertCircle className="w-6 h-6" />
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-900">
                      No reconciliation workpaper found for period {noticeData.tax_period || "specified"}
                    </h4>
                    <p className="text-xs text-slate-600 max-w-md mx-auto mt-1">
                      To compile an exact invoice-by-invoice mathematical defense annexure from your client's actual books, run a GSTR-2B reconciliation first.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
                    <a
                      href={`/reconcile/${clientId}/new?period=${encodeURIComponent(noticeData.tax_period || "")}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm transition-colors"
                    >
                      <span>Start GSTR-2B Reconciliation for {noticeData.tax_period || "Period"}</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                    <button
                      onClick={handleRunDefense}
                      className="px-4 py-2 rounded-xl bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-bold"
                    >
                      Proceed with Statutory Defense Grounds Only →
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 max-h-72 overflow-y-auto">
                  {matchingRuns.map((r) => {
                    const isSelected = selectedRunId === r.id;
                    const periodMatch = r.period === noticeData.tax_period;
                    return (
                      <div
                        key={r.id}
                        onClick={() => setSelectedRunId(r.id)}
                        className={`p-3.5 rounded-xl border cursor-pointer flex items-center justify-between transition-all ${
                          isSelected
                            ? "border-indigo-600 bg-indigo-50/50 shadow-sm"
                            : "border-slate-200 hover:border-slate-300 bg-white"
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <input
                            type="radio"
                            checked={isSelected}
                            onChange={() => setSelectedRunId(r.id)}
                            className="text-indigo-600 focus:ring-indigo-500"
                          />
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-bold text-slate-900 font-mono">
                                Period: {r.period}
                              </span>
                              {periodMatch && (
                                <span className="text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-100 text-emerald-800">
                                  Exact Period Match
                                </span>
                              )}
                              <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-600 uppercase font-bold">
                                {r.status}
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-500 mt-0.5">
                              {r.gstr_records_imported} GSTR Invoices • {r.pr_records_imported} Books Invoices • Run ID: {r.id.slice(0, 8)}...
                            </p>
                          </div>
                        </div>
                        <div className="text-right">
                          <span className="text-xs font-mono font-semibold text-slate-700">
                            Verified Workpaper
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* STEP 3: DEFENSE WORKPAPER & REPLY GENERATOR */}
          {step === 3 && defenseResult && (
            <div className="space-y-5">
              {/* Defense Mathematical Summary Card */}
              <div className="p-5 rounded-2xl bg-gradient-to-br from-slate-900 to-indigo-950 text-white shadow-lg space-y-4">
                <div className="flex items-center justify-between border-b border-indigo-900/60 pb-3">
                  <div>
                    <span className="text-[10px] font-bold tracking-widest uppercase text-indigo-300">
                      Reconciliation Defense Summary
                    </span>
                    <h3 className="text-base font-bold text-white flex items-center gap-2">
                      Notice Discrepancy Defense: {defenseResult.notice_type}
                    </h3>
                  </div>
                  <div className="flex items-center gap-2">
                    {defenseResult.defense_summary.reconciliation_status === "FULLY_RECONCILED" ? (
                      <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5">
                        <Check className="w-3.5 h-3.5" /> 100% Fully Reconciled
                      </span>
                    ) : (
                      <span className="px-3 py-1 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                        {defenseResult.defense_summary.reconciled_pct}% Reconciled
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                  <div className="bg-white/5 p-3 rounded-xl border border-white/10">
                    <span className="text-slate-400 block mb-1">Alleged Demand</span>
                    <span className="text-base font-bold font-mono text-rose-300">
                      {formatINR(defenseResult.defense_summary.alleged_total)}
                    </span>
                  </div>
                  <div className="bg-white/5 p-3 rounded-xl border border-white/10">
                    <span className="text-slate-400 block mb-1">Timing Diffs (Sec 16(4))</span>
                    <span className="text-base font-bold font-mono text-emerald-300">
                      {formatINR(defenseResult.defense_summary.timing_diff_itc)}
                    </span>
                  </div>
                  <div className="bg-white/5 p-3 rounded-xl border border-white/10">
                    <span className="text-slate-400 block mb-1">Rule 37 Re-credits</span>
                    <span className="text-base font-bold font-mono text-indigo-300">
                      {formatINR(defenseResult.defense_summary.reclaimed_rule37_itc)}
                    </span>
                  </div>
                  <div className="bg-white/5 p-3 rounded-xl border border-white/10">
                    <span className="text-slate-400 block mb-1">Unexplained / DRC-03</span>
                    <span className="text-base font-bold font-mono text-amber-300">
                      {formatINR(defenseResult.defense_summary.unexplained_balance)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Navigation Tabs */}
              <div className="flex border-b border-slate-200 gap-4">
                <button
                  onClick={() => setActiveTab("summary")}
                  className={`pb-2 text-xs font-bold transition-colors border-b-2 ${
                    activeTab === "summary"
                      ? "border-indigo-600 text-indigo-600"
                      : "border-transparent text-slate-500 hover:text-slate-800"
                  }`}
                >
                  Mathematical Breakdown
                </button>
                <button
                  onClick={() => setActiveTab("invoices")}
                  className={`pb-2 text-xs font-bold transition-colors border-b-2 flex items-center gap-1.5 ${
                    activeTab === "invoices"
                      ? "border-indigo-600 text-indigo-600"
                      : "border-transparent text-slate-500 hover:text-slate-800"
                  }`}
                >
                  Annexure A (Invoices Schedule)
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-700">
                    {defenseResult.invoices_schedule.length}
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab("reply")}
                  className={`pb-2 text-xs font-bold transition-colors border-b-2 ${
                    activeTab === "reply"
                      ? "border-indigo-600 text-indigo-600"
                      : "border-transparent text-slate-500 hover:text-slate-800"
                  }`}
                >
                  Formal Legal Reply Letter
                </button>
              </div>

              {/* TAB 1: SUMMARY TABLE */}
              {activeTab === "summary" && (
                <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm">
                  <table className="w-full text-xs text-left border-collapse">
                    <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200 uppercase text-[10px]">
                      <tr>
                        <th className="p-3 w-12 text-center">Sr.</th>
                        <th className="p-3">Defense Component / Reason</th>
                        <th className="p-3">Statutory Basis / Circular</th>
                        <th className="p-3 text-right">Amount (₹)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      <tr>
                        <td className="p-3 text-center text-slate-400">1</td>
                        <td className="p-3 font-semibold text-rose-700">
                          Notice Alleged Excess Discrepancy
                        </td>
                        <td className="p-3 text-slate-500">Notice Allegation ({defenseResult.notice_type})</td>
                        <td className="p-3 text-right font-mono font-bold text-rose-700">
                          {formatINR(defenseResult.defense_summary.alleged_total)}
                        </td>
                      </tr>
                      <tr>
                        <td className="p-3 text-center text-slate-400">2</td>
                        <td className="p-3 font-medium text-slate-800">
                          Less: Inward supplies where supplier filed GSTR-1 in subsequent tax period
                        </td>
                        <td className="p-3 text-slate-600">
                          CGST Sec 16(4) & CBIC Circular 183/15/2022
                        </td>
                        <td className="p-3 text-right font-mono text-emerald-700">
                          ({formatINR(defenseResult.defense_summary.timing_diff_itc)})
                        </td>
                      </tr>
                      <tr>
                        <td className="p-3 text-center text-slate-400">3</td>
                        <td className="p-3 font-medium text-slate-800">
                          Less: Rule 37 180-Day Reversal re-availed upon payment to supplier
                        </td>
                        <td className="p-3 text-slate-600">Proviso to Rule 37 / Table 4(D)(1)</td>
                        <td className="p-3 text-right font-mono text-emerald-700">
                          ({formatINR(defenseResult.defense_summary.reclaimed_rule37_itc)})
                        </td>
                      </tr>
                      <tr>
                        <td className="p-3 text-center text-slate-400">4</td>
                        <td className="p-3 font-medium text-slate-800">
                          Less: Ineligible ITC already reversed under Table 4(B)
                        </td>
                        <td className="p-3 text-slate-600">Circular No. 170/02/2022-GST</td>
                        <td className="p-3 text-right font-mono text-emerald-700">
                          ({formatINR(defenseResult.defense_summary.table4b_reversals_itc)})
                        </td>
                      </tr>
                      <tr className="bg-slate-50/80 font-bold border-t-2 border-slate-300">
                        <td className="p-3 text-center">5</td>
                        <td className="p-3 text-indigo-950">
                          BALANCE UNEXPLAINED / PROPOSED FOR VOLUNTARY DRC-03
                        </td>
                        <td className="p-3 text-slate-500">Voluntary DRC-03 Settlement</td>
                        <td className="p-3 text-right font-mono text-indigo-900 text-sm">
                          {formatINR(defenseResult.defense_summary.unexplained_balance)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {/* TAB 2: INVOICES SCHEDULE */}
              {activeTab === "invoices" && (
                <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm max-h-72 overflow-y-auto">
                  <table className="w-full text-xs text-left border-collapse">
                    <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200 text-[10px] uppercase sticky top-0">
                      <tr>
                        <th className="p-2.5">Supplier GSTIN</th>
                        <th className="p-2.5">Supplier Name</th>
                        <th className="p-2.5">Invoice No</th>
                        <th className="p-2.5">Date</th>
                        <th className="p-2.5 text-right">Taxable (₹)</th>
                        <th className="p-2.5 text-right">Total Tax (₹)</th>
                        <th className="p-2.5">Defense Ground</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
                      {defenseResult.invoices_schedule.map((inv, idx) => (
                        <tr key={idx} className="hover:bg-slate-50/60">
                          <td className="p-2.5 font-bold text-slate-800">{inv.supplier_gstin}</td>
                          <td className="p-2.5 font-sans font-medium text-slate-700 truncate max-w-[140px]">
                            {inv.supplier_name}
                          </td>
                          <td className="p-2.5 text-slate-700">{inv.invoice_number}</td>
                          <td className="p-2.5 text-slate-500">{inv.invoice_date}</td>
                          <td className="p-2.5 text-right">{formatINR(inv.taxable_value)}</td>
                          <td className="p-2.5 text-right font-bold text-indigo-700">
                            {formatINR(inv.total_tax)}
                          </td>
                          <td className="p-2.5 font-sans text-slate-600 max-w-[200px] truncate" title={inv.defense_ground}>
                            {inv.defense_ground}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* TAB 3: FORMAL REPLY LETTER */}
              {activeTab === "reply" && (
                <div className="space-y-3">
                  {/* CA Statutory Review Gate Banner */}
                  <div className="p-3.5 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-start gap-2.5">
                    <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                    <div className="space-y-0.5">
                      <div className="font-bold text-amber-950">
                        Statutory Practitioner Review Gate (CGST Rule 26)
                      </div>
                      <p className="text-amber-800 leading-relaxed text-[11px]">
                        This reply draft and mathematical Annexure A have been compiled from client reconciliation records.
                        Under ICAI standards and CGST rules, a Chartered Accountant / Tax Practitioner must review supporting
                        vouchers and certify calculations prior to filing on the GST portal.
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50 p-2.5 rounded-xl border border-slate-200">
                    <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-slate-700 select-none">
                      <input
                        type="checkbox"
                        checked={certifiedByCa}
                        onChange={(e) => setCertifiedByCa(e.target.checked)}
                        className="w-4 h-4 rounded text-indigo-600 border-slate-300 focus:ring-indigo-500"
                      />
                      <span>I certify that I have verified the underlying vouchers and figures prior to submission.</span>
                    </label>

                    <button
                      onClick={handleCopyReply}
                      className={`px-3 py-1.5 rounded-lg text-white font-sans text-xs font-bold flex items-center justify-center gap-1.5 shadow-sm transition-all shrink-0 ${
                        certifiedByCa ? "bg-indigo-600 hover:bg-indigo-700" : "bg-slate-400 opacity-70"
                      }`}
                    >
                      {copySuccess ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                      {copySuccess ? "Copied Reply!" : "Copy Full Text"}
                    </button>
                  </div>

                  <div className="relative border border-slate-200 rounded-xl p-4 bg-slate-900 text-slate-100 font-mono text-xs max-h-80 overflow-y-auto leading-relaxed whitespace-pre-wrap selection:bg-indigo-600">
                    {defenseResult.formal_reply_text}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer Controls */}
        <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-between">
          <div>
            {step > 1 && step < 3 && (
              <button
                onClick={() => setStep(1)}
                className="px-4 py-2 rounded-xl text-xs font-bold text-slate-600 hover:bg-slate-200 transition-colors"
              >
                Back
              </button>
            )}
            {step === 3 && (
              <button
                onClick={() => setStep(2)}
                className="px-4 py-2 rounded-xl text-xs font-bold text-slate-600 hover:bg-slate-200 transition-colors"
              >
                Re-link Run
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            {step === 1 && (
              <button
                onClick={handleProceedToRuns}
                className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold flex items-center gap-2 shadow-md shadow-indigo-100 transition-all"
              >
                <span>Find Matching Runs</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            )}

            {step === 2 && (
              <button
                onClick={handleRunDefense}
                disabled={analyzing}
                className="px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold flex items-center gap-2 shadow-md shadow-indigo-100 transition-all disabled:opacity-50"
              >
                {analyzing ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                <span>{analyzing ? "Computing Defense..." : "Generate Defense Workpaper"}</span>
              </button>
            )}

            {step === 3 && defenseResult && (
              <>
                <button
                  onClick={handleDownloadExcel}
                  disabled={downloadingExcel}
                  className="px-4 py-2.5 rounded-xl bg-white border border-slate-300 hover:bg-slate-100 text-slate-800 text-xs font-bold flex items-center gap-2 transition-colors"
                >
                  {downloadingExcel ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4 text-emerald-600" />}
                  <span>Export Excel Annexure</span>
                </button>

                <button
                  onClick={handleSaveNotice}
                  disabled={savingNotice || saveSuccess}
                  className={`px-5 py-2.5 rounded-xl text-white text-xs font-bold flex items-center gap-2 shadow-md transition-all ${
                    saveSuccess
                      ? "bg-emerald-600 shadow-emerald-100"
                      : "bg-indigo-600 hover:bg-indigo-700 shadow-indigo-100"
                  }`}
                >
                  {savingNotice ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : saveSuccess ? (
                    <Check className="w-4 h-4" />
                  ) : (
                    <FileCheck className="w-4 h-4" />
                  )}
                  <span>{saveSuccess ? "Saved to Client!" : "Save Notice Defense"}</span>
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
