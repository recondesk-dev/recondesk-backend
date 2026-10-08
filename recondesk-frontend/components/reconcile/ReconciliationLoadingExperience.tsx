"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";

export interface ReconciliationLoadingProps {
  /** Optional override for preview/snapshot demonstration */
  previewState?: "in_progress" | "longer_wait" | "completed";
  /** Current progress percentage (0 - 100) */
  progressPct?: number;
  /** Server status message (e.g. "Comparing invoice numbers, dates, and amounts.") */
  statusMessage?: string;
  /** Elapsed time in seconds. If omitted, internal timer counts automatically */
  elapsedSeconds?: number;
  /** Matched count so far */
  matchedCount?: number;
  /** Discrepancies / review items count so far */
  reviewCount?: number;
  /** Total processed count on completion */
  totalProcessedCount?: number;
  /** Missing from 2B count on completion */
  missingCount?: number;
  /** Client or Run metadata */
  clientName?: string;
  periodLabel?: string;
  runId?: string;
  /** Action callbacks */
  onCancelRun?: () => void;
  onContinueBackground?: () => void;
  onViewReport?: () => void;
  /** Toggle whether cancel confirmation is showing */
  isCancelling?: boolean;
}

export function ReconciliationLoadingExperience({
  previewState,
  progressPct = 42,
  statusMessage,
  elapsedSeconds: controlledElapsed,
  matchedCount = 142,
  reviewCount = 3,
  totalProcessedCount = 1442,
  missingCount = 4,
  clientName = "Acme Industrial Ltd",
  periodLabel = "October 2024",
  runId,
  onCancelRun,
  onContinueBackground,
  onViewReport,
  isCancelling = false,
}: ReconciliationLoadingProps) {
  // Timer state
  const [internalElapsed, setInternalElapsed] = useState(
    previewState === "longer_wait" ? 64 : previewState === "completed" ? 84 : 28
  );
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [whileWeWorkExpanded, setWhileWeWorkExpanded] = useState(
    previewState === "longer_wait"
  );
  const [activeMatchedIndex, setActiveMatchedIndex] = useState(1);

  // Automatic elapsed timer if not controlled
  useEffect(() => {
    if (previewState || controlledElapsed !== undefined) return;
    const interval = setInterval(() => {
      setInternalElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [previewState, controlledElapsed]);

  const elapsed = controlledElapsed ?? internalElapsed;

  // Gentle cycle of sample matching rows for restrained, slow motion
  useEffect(() => {
    if (previewState === "completed") return;
    const interval = setInterval(() => {
      setActiveMatchedIndex((prev) => (prev + 1) % 3);
    }, 3600);
    return () => clearInterval(interval);
  }, [previewState]);

  // Longer wait threshold (30 seconds)
  const isLongerWait =
    previewState === "longer_wait" || (previewState === undefined && elapsed >= 30);
  const isCompleted = previewState === "completed" || progressPct >= 100;

  // Formatting elapsed time as mm:ss
  const formattedTime = useMemo(() => {
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
  }, [elapsed]);

  // Stage calculations (compact 4 stages)
  const currentStageIndex = useMemo(() => {
    if (isCompleted) return 4;
    if (progressPct >= 75 || previewState === "longer_wait") return 3;
    if (progressPct >= 20 || previewState === "in_progress") return 2;
    return 1;
  }, [isCompleted, progressPct, previewState]);

  // Sample illustrative rows for the single matching animation focal point
  const sampleInvoices = [
    {
      prNum: "INV-2024-0892",
      prAmt: "₹42,500",
      gstrNum: "INV-2024-0892",
      gstrAmt: "₹42,500",
      status: "matched",
    },
    {
      prNum: "INV-2024-0914",
      prAmt: "₹1,18,400",
      gstrNum: "INV-2024-0914",
      gstrAmt: "₹1,18,400",
      status: "comparing",
    },
    {
      prNum: "INV-2024-0941",
      prAmt: "₹15,200",
      gstrNum: "INV-2024-0941",
      gstrAmt: "₹15,200",
      status: "queued",
    },
  ];

  return (
    <div className="w-full max-w-[620px] mx-auto transition-all duration-300">
      {/* Focused Reconciliation Card (Single panel, no nested cards) */}
      <div className="bg-white rounded-[22px] border border-[#E8E2EE] shadow-[0_8px_30px_-8px_rgba(52,43,64,0.06)] p-7 sm:p-8">
        
        {/* Top Metadata Row */}
        <div className="flex items-center justify-between text-xs text-[#777083] pb-4 mb-5 border-b border-[#F4EEF8]">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                isCompleted ? "bg-[#10B981]" : "bg-[#8054ED]"
              }`}
            />
            <span className="font-medium text-[#483B59]">{clientName}</span>
            <span className="text-[#A499B3]">·</span>
            <span className="text-[#777083]">{periodLabel}</span>
          </div>
          <span className="font-mono text-[#777083] font-medium">
            {isCompleted ? "Finished in 1m 24s" : `${formattedTime} elapsed`}
          </span>
        </div>

        {/* IN-PROGRESS / LONGER-WAIT CONTENT */}
        {!isCompleted ? (
          <>
            {/* Main Heading & Supporting Text (No repetition) */}
            <div>
              <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-[#342B40] leading-snug">
                Finding the right match
              </h1>
              <p className="text-sm text-[#777083] mt-1">
                {statusMessage ||
                  (currentStageIndex === 3
                    ? "Comparing tax splits and checking for invoice rounding tolerances."
                    : "We’re comparing invoice numbers, dates, and amounts.")}
              </p>
            </div>

            {/* Compact 4-Stage Progress Indicator */}
            <div className="mt-6 mb-4">
              <div className="flex items-center justify-between relative px-1">
                {/* Stage 1: Files checked */}
                <div className="flex items-center gap-1.5 z-10">
                  <span className="w-4 h-4 rounded-full bg-[#342B40] text-white flex items-center justify-center text-[10px]">
                    ✓
                  </span>
                  <span className="text-xs font-medium text-[#544766]">
                    Files checked
                  </span>
                </div>

                <div
                  className={`flex-1 mx-2 h-[1px] ${
                    currentStageIndex > 1 ? "bg-[#342B40]" : "bg-[#8054ED]"
                  }`}
                />

                {/* Stage 2: Matching */}
                <div className="flex items-center gap-1.5 z-10">
                  {currentStageIndex > 2 ? (
                    <span className="w-4 h-4 rounded-full bg-[#342B40] text-white flex items-center justify-center text-[10px]">
                      ✓
                    </span>
                  ) : (
                    <span className="w-4 h-4 rounded-full bg-[#8054ED] text-white flex items-center justify-center text-[9px] font-bold">
                      ●
                    </span>
                  )}
                  <span
                    className={`text-xs ${
                      currentStageIndex === 2
                        ? "font-semibold text-[#342B40]"
                        : "font-medium text-[#544766]"
                    }`}
                  >
                    Matching
                  </span>
                </div>

                <div
                  className={`flex-1 mx-2 h-[1px] ${
                    currentStageIndex >= 3 ? "bg-[#8054ED]" : "bg-[#EAE2F2]"
                  }`}
                />

                {/* Stage 3: Reviewing */}
                <div
                  className={`flex items-center gap-1.5 z-10 ${
                    currentStageIndex < 3 ? "opacity-60" : ""
                  }`}
                >
                  {currentStageIndex >= 3 ? (
                    <span className="w-4 h-4 rounded-full bg-[#8054ED] text-white flex items-center justify-center text-[9px] font-bold">
                      ●
                    </span>
                  ) : (
                    <span className="w-4 h-4 rounded-full border border-[#D5C9E2] text-[#8C7E9D] flex items-center justify-center text-[9px]">
                      3
                    </span>
                  )}
                  <span
                    className={`text-xs ${
                      currentStageIndex === 3
                        ? "font-semibold text-[#342B40]"
                        : "text-[#777083]"
                    }`}
                  >
                    Reviewing
                  </span>
                </div>

                <div className="flex-1 mx-2 h-[1px] bg-[#EAE2F2]" />

                {/* Stage 4: Report ready */}
                <div className="flex items-center gap-1.5 z-10 opacity-60">
                  <span className="w-4 h-4 rounded-full border border-[#D5C9E2] text-[#8C7E9D] flex items-center justify-center text-[9px]">
                    4
                  </span>
                  <span className="text-xs text-[#777083]">Report ready</span>
                </div>
              </div>

              {/* Single Real Progress Bar with label below */}
              <div className="mt-4">
                <div className="w-full h-1.5 rounded-full bg-[#F2ECF7] overflow-hidden">
                  <div
                    className="h-full bg-[#8054ED] rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(100, Math.max(4, progressPct))}%`,
                    }}
                  />
                </div>
                <div className="flex items-center justify-between text-[11px] text-[#8E839E] mt-1.5">
                  <span>{Math.round(progressPct)}% completed</span>
                  <span>Real-time backend progress</span>
                </div>
              </div>
            </div>

            {/* CREATIVE FOCAL POINT: Restrained Invoice-Matching Visualization */}
            <div className="mt-5 p-4 rounded-xl bg-[#FAF8FD] border border-[#EBE4F4]">
              <div className="flex items-center justify-between text-[11px] font-semibold text-[#6E6180] tracking-wide uppercase pb-2 border-b border-[#F0EAF6]">
                <span>Purchase register</span>
                <span className="font-normal font-mono text-[10px] text-[#A69BB5] lowercase tracking-normal">
                  illustrative activity
                </span>
                <span>Supplier records</span>
              </div>

              {/* Aligning Invoice Rows */}
              <div className="space-y-2 mt-3 text-xs">
                {sampleInvoices.map((inv, idx) => {
                  const isMatchingNow = activeMatchedIndex === idx;
                  const isMatched = activeMatchedIndex > idx || (activeMatchedIndex === 0 && idx === 0);

                  return (
                    <div
                      key={inv.prNum}
                      className={`flex items-center justify-between p-2 rounded-lg border transition-all duration-300 ${
                        isMatchingNow
                          ? "bg-white border-[#CBB8ED] shadow-xs"
                          : "bg-white border-[#EAE3F2]"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[#342B40] font-medium">
                          {inv.prNum}
                        </span>
                        <span className="text-[#777083]">{inv.prAmt}</span>
                      </div>

                      {/* Central connector */}
                      {isMatchingNow ? (
                        <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#8054ED] text-white text-[10px] font-medium">
                          <span>comparing…</span>
                        </div>
                      ) : isMatched ? (
                        <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#F4EEFB] text-[#8054ED] text-[11px] font-medium">
                          <span>✓</span>
                          <span>matched</span>
                        </div>
                      ) : (
                        <div className="w-4 h-[1px] bg-[#DDD4E7]" />
                      )}

                      <div className="flex items-center gap-2">
                        <span className="text-[#777083]">{inv.gstrAmt}</span>
                        <span className="font-mono text-[#342B40] font-medium">
                          {inv.gstrNum}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Two Quiet Preliminary Counts */}
              <div className="mt-3.5 pt-2.5 border-t border-[#F0EAF6] flex items-center justify-between text-xs text-[#777083]">
                <span className="text-[11px] font-medium text-[#8E839E]">
                  Preliminary results
                </span>
                <div className="flex items-center gap-3">
                  <span>
                    Matched so far:{" "}
                    <strong className="text-[#342B40] font-mono font-semibold">
                      {matchedCount.toLocaleString("en-IN")}
                    </strong>
                  </span>
                  <span>·</span>
                  <span>
                    Needs review:{" "}
                    <strong className="text-[#342B40] font-mono font-semibold">
                      {reviewCount}
                    </strong>
                  </span>
                </div>
              </div>
            </div>

            {/* ONE OPTIONAL EXPANDABLE REPORT EXPLANATION (WITHOUT nested cards) */}
            {isLongerWait && (
              <div className="mt-4 pt-3 border-t border-[#F4EEF8]">
                <button
                  type="button"
                  onClick={() => setWhileWeWorkExpanded(!whileWeWorkExpanded)}
                  className="w-full flex items-center justify-between text-xs py-1 text-[#483B59] font-medium hover:text-[#8054ED] transition-colors"
                >
                  <span className="flex items-center gap-1.5">
                    <span className="text-[#8054ED]">
                      {whileWeWorkExpanded ? "▾" : "▸"}
                    </span>
                    <span>While we work: How your report is organized</span>
                  </span>
                  <span className="text-[11px] text-[#8E839E]">
                    {whileWeWorkExpanded ? "Hide" : "Optional preview"}
                  </span>
                </button>

                {whileWeWorkExpanded && (
                  <div className="mt-2 pl-3 py-2 text-xs text-[#777083] space-y-1.5 border-l-2 border-[#E3D9F0]">
                    <p>
                      <strong className="text-[#342B40] font-semibold">
                        Exact matches:
                      </strong>{" "}
                      Invoices where document number, date, and tax amounts match
                      between your register and supplier filings.
                    </p>
                    <p>
                      <strong className="text-[#342B40] font-semibold">
                        Amount differences:
                      </strong>{" "}
                      Invoices matching on document number with minor differences
                      in taxable value or GST splits for your review.
                    </p>
                    <p>
                      <strong className="text-[#342B40] font-semibold">
                        Missing invoices:
                      </strong>{" "}
                      Purchases recorded in your books that do not appear in
                      supplier filings, or vice versa.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Bottom Actions */}
            <div className="mt-6 pt-5 border-t border-[#F4EEF8] flex items-center justify-between">
              <div>
                {onContinueBackground ? (
                  <button
                    type="button"
                    onClick={onContinueBackground}
                    className="px-5 py-2.5 rounded-full bg-[#342B40] text-white text-xs font-semibold shadow-xs hover:bg-[#433752] transition-colors"
                  >
                    Continue working →
                  </button>
                ) : (
                  <Link
                    href="/dashboard"
                    className="inline-block px-5 py-2.5 rounded-full bg-[#342B40] text-white text-xs font-semibold shadow-xs hover:bg-[#433752] transition-colors"
                  >
                    Continue working →
                  </Link>
                )}
                <p className="text-[11px] text-[#8E839E] mt-1">
                  You can safely leave this page. We’ll notify you when ready.
                </p>
              </div>

              {showCancelModal ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[#DC2626] font-medium">
                    Cancel run?
                  </span>
                  <button
                    type="button"
                    disabled={isCancelling}
                    onClick={() => {
                      setShowCancelModal(false);
                      onCancelRun?.();
                    }}
                    className="px-2.5 py-1 rounded-md text-xs font-semibold bg-red-50 text-red-700 hover:bg-red-100 transition-colors"
                  >
                    {isCancelling ? "Cancelling…" : "Yes, cancel"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCancelModal(false)}
                    className="px-2 py-1 rounded-md text-xs text-[#777083] hover:text-[#342B40]"
                  >
                    Dismiss
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowCancelModal(true)}
                  className="text-xs text-[#8E839E] hover:text-[#DC2626] font-medium transition-colors"
                >
                  Cancel run
                </button>
              )}
            </div>
          </>
        ) : (
          /* COMPLETION STATE: Simple heading, compact summary, View report */
          <>
            <div>
              <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-[#342B40] leading-snug">
                Your reconciliation is ready
              </h1>
              <p className="text-sm text-[#777083] mt-1">
                {totalProcessedCount.toLocaleString("en-IN")} invoices processed across purchase register and supplier records.
              </p>
            </div>

            {/* COMPACT RESULT SUMMARY (Verified backend status only) */}
            <div className="mt-6 p-5 rounded-xl bg-[#FAF8FD] border border-[#EBE4F4]">
              <div className="grid grid-cols-3 gap-4 text-left">
                <div>
                  <span className="text-xs text-[#777083] font-medium block">
                    Matched records
                  </span>
                  <span className="text-2xl font-semibold font-mono text-[#342B40] mt-1 block">
                    {matchedCount.toLocaleString("en-IN")}
                  </span>
                  <span className="text-[11px] text-[#6E6180] mt-0.5 block">
                    Identical details
                  </span>
                </div>
                <div className="border-l border-[#EDE5F4] pl-4">
                  <span className="text-xs text-[#777083] font-medium block">
                    Amount differences
                  </span>
                  <span className="text-2xl font-semibold font-mono text-[#342B40] mt-1 block">
                    {reviewCount}
                  </span>
                  <span className="text-[11px] text-[#6E6180] mt-0.5 block">
                    Value discrepancies
                  </span>
                </div>
                <div className="border-l border-[#EDE5F4] pl-4">
                  <span className="text-xs text-[#777083] font-medium block">
                    Missing in GSTR-2B
                  </span>
                  <span className="text-2xl font-semibold font-mono text-[#342B40] mt-1 block">
                    {missingCount}
                  </span>
                  <span className="text-[11px] text-[#6E6180] mt-0.5 block">
                    Supplier unfiled
                  </span>
                </div>
              </div>
            </div>

            {/* Bottom Actions (Single prominent "View report" CTA + secondary dashboard return) */}
            <div className="mt-7 pt-5 border-t border-[#F4EEF8] flex items-center justify-between">
              <span className="text-xs text-[#777083]">
                Ready for review and filing tie-out.
              </span>
              <div className="flex items-center gap-3">
                <Link
                  href="/dashboard"
                  className="text-xs text-[#777083] hover:text-[#342B40] font-medium transition-colors"
                >
                  Back to Dashboard
                </Link>
                {onViewReport ? (
                  <button
                    type="button"
                    onClick={onViewReport}
                    className="px-6 py-2.5 rounded-full bg-[#342B40] text-white text-xs font-semibold shadow-xs hover:bg-[#433752] transition-colors"
                  >
                    View report →
                  </button>
                ) : (
                  <Link
                    href={runId ? `/reconcile/runs/${runId}/results` : "/reconciliations"}
                    className="px-6 py-2.5 rounded-full bg-[#342B40] text-white text-xs font-semibold shadow-xs hover:bg-[#433752] transition-colors"
                  >
                    View report →
                  </Link>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
