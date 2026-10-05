"use client";

import React, {
  useEffect,
  useMemo,
  useState,
  useCallback,
  useRef,
  memo,
} from "react";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  HelpCircle,
  FileCheck,
  ShieldCheck,
  AlertTriangle,
  Search,
  AlertCircle,
  FileText,
} from "lucide-react";

import {
  recordAmountRupees,
  recordGstin,
  recordInvoiceNumber,
  mismatchTypeShort,
  type Gstr1ReconcileResult,
} from "@/lib/gstr1Reconcile";
import { GstinCell } from "@/components/ui/GstinCell";
import { AccessibleTooltip } from "@/components/ui/AccessibleTooltip";
import { safeStorageGet, safeStorageSet } from "@/lib/safeStorage";

export {
  type DecisionStatus,
  type ReviewDecisionRecord,
  type ReviewQueueItem,
  paiseToRupees,
  formatInr,
  formatInrPlain,
  generateReviewScopeKey,
  buildReviewQueueItems,
} from "./gstr1ReviewLogic";

import {
  type DecisionStatus,
  type ReviewDecisionRecord,
  type ReviewQueueItem,
  formatInr,
  formatInrPlain,
  generateReviewScopeKey,
  buildReviewQueueItems,
} from "./gstr1ReviewLogic";

// ── Memoized Queue Item Row ──────────────────────────────────────────────────
interface QueueItemRowProps {
  item: ReviewQueueItem;
  isActive: boolean;
  isSelected: boolean;
  latestDecision?: ReviewDecisionRecord;
  onSelect: (id: string, e: React.MouseEvent) => void;
  onCompare: (id: string) => void;
  compareButtonRef?: (el: HTMLButtonElement | null) => void;
}

const QueueItemRow = memo(function QueueItemRow({
  item,
  isActive,
  isSelected,
  latestDecision,
  onSelect,
  onCompare,
  compareButtonRef,
}: QueueItemRowProps) {
  return (
    <div
      onClick={() => onCompare(item.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onCompare(item.id);
        }
      }}
      className={`group relative flex flex-col gap-2 p-3.5 cursor-pointer transition-colors outline-none focus-visible:ring-2 focus-visible:ring-purple-500 ${
        isActive
          ? "bg-[#F7F3FC] border-l-4 border-l-purple-600"
          : "hover:bg-[#FAF9FD]"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => {}}
            onClick={(e) => onSelect(item.id, e)}
            className="h-3.5 w-3.5 rounded border-gray-300 text-purple-600 focus:ring-purple-500 cursor-pointer"
            aria-label={`Select invoice ${item.invoiceNumber}`}
          />
          <span className="text-[13px] font-bold text-gray-900 group-hover:text-purple-900">
            {item.invoiceNumber}
          </span>
        </div>

        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${
            latestDecision?.status === "reviewed"
              ? "bg-purple-100 text-purple-800"
              : latestDecision?.status === "awaiting_clarification"
                ? "bg-amber-100 text-amber-800"
                : latestDecision?.status === "queued_gstr1a"
                  ? "bg-blue-100 text-blue-800"
                  : latestDecision?.status === "corrected_verified"
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-gray-100 text-gray-600"
          }`}
        >
          {latestDecision?.label || "Unreviewed"}
        </span>
      </div>

      <div className="flex items-center justify-between text-xs text-gray-500">
        <GstinCell gstin={item.gstin} truncate={false} className="font-mono text-[11px]" />
        <span>{item.invoiceDate}</span>
      </div>

      <div className="flex items-center justify-between gap-2 mt-1">
        <div className="flex items-center gap-1.5">
          <span className="rounded bg-purple-50 px-1.5 py-0.5 text-[10px] font-bold text-purple-700">
            {item.issueCode}
          </span>
          {item.taxableDiff !== 0 && (
            <span className="text-[11px] font-semibold text-amber-800 tabular-nums">
              Δ {formatInrPlain(Math.abs(item.taxableDiff))}
            </span>
          )}
        </div>

        <button
          ref={compareButtonRef}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onCompare(item.id);
          }}
          className="rounded-md border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-medium text-gray-700 shadow-xs hover:border-purple-300 hover:text-purple-700 transition-colors"
          aria-label={`Compare invoice ${item.invoiceNumber}`}
        >
          Compare →
        </button>
      </div>
    </div>
  );
});

// ── Memoized Isolated Decision Action Panel ──────────────────────────────────
// Keeps noteInput isolated so typing never re-renders the 5,000 item queue!
interface DecisionActionPanelProps {
  itemId: string;
  latestDecision?: ReviewDecisionRecord;
  history: ReviewDecisionRecord[];
  onRecord: (status: DecisionStatus, label: string, note?: string) => void;
}

const DecisionActionPanel = memo(function DecisionActionPanel({
  itemId,
  latestDecision,
  history,
  onRecord,
}: DecisionActionPanelProps) {
  const [localNote, setLocalNote] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  // Reset note input when item changes
  useEffect(() => {
    setLocalNote("");
    setValidationError(null);
  }, [itemId]);

  const handleAction = (status: DecisionStatus, label: string) => {
    // Audit integrity: Require evidence/rationale before marking "Corrected & Verified"
    if (status === "corrected_verified") {
      const trimmed = localNote.trim();
      if (!trimmed || trimmed.length < 5) {
        setValidationError(
          "Verification evidence is required. Please specify the revised ERP entry, credit note reference, or GSTR-1A IRN before verifying."
        );
        return;
      }
    }

    setValidationError(null);
    onRecord(status, label, localNote.trim() || undefined);
    setLocalNote("");
  };

  return (
    <div className="rounded-2xl border border-[#E6E0ED] bg-white p-5 shadow-xs space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-700">
          Record Audit Decision
        </h3>
        {latestDecision && (
          <span className="text-xs text-gray-500">
            Current: <strong className="text-purple-900">{latestDecision.label}</strong>
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <button
          type="button"
          onClick={() => handleAction("reviewed", "Accepted Variance")}
          className="flex items-center justify-center gap-1.5 rounded-xl border border-purple-200 bg-purple-50/70 p-2.5 text-xs font-semibold text-purple-900 hover:bg-purple-100 transition-colors shadow-2xs"
        >
          <CheckCircle2 className="h-3.5 w-3.5 text-purple-700" />
          <span>Accept Variance</span>
        </button>

        <button
          type="button"
          onClick={() => handleAction("awaiting_clarification", "Awaiting Clarification")}
          className="flex items-center justify-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50/70 p-2.5 text-xs font-semibold text-amber-900 hover:bg-amber-100 transition-colors shadow-2xs"
        >
          <HelpCircle className="h-3.5 w-3.5 text-amber-700" />
          <span>Clarification</span>
        </button>

        <button
          type="button"
          onClick={() => handleAction("queued_gstr1a", "Queued for GSTR-1A")}
          className="flex items-center justify-center gap-1.5 rounded-xl border border-blue-200 bg-blue-50/70 p-2.5 text-xs font-semibold text-blue-900 hover:bg-blue-100 transition-colors shadow-2xs"
        >
          <FileCheck className="h-3.5 w-3.5 text-blue-700" />
          <span>Queue GSTR-1A</span>
        </button>

        <button
          type="button"
          onClick={() => handleAction("corrected_verified", "Corrected & Verified")}
          className="flex items-center justify-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50/70 p-2.5 text-xs font-semibold text-emerald-900 hover:bg-emerald-100 transition-colors shadow-2xs"
        >
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-700" />
          <span>Verified</span>
        </button>
      </div>

      {validationError && (
        <div className="flex items-start gap-2 rounded-xl bg-rose-50 p-3 text-xs text-rose-800 border border-rose-200">
          <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <span>{validationError}</span>
        </div>
      )}

      <div className="pt-2">
        <label htmlFor="audit-note-input" className="sr-only">
          Audit note or verification rationale
        </label>
        <textarea
          id="audit-note-input"
          rows={2}
          value={localNote}
          onChange={(e) => {
            setLocalNote(e.target.value);
            if (validationError) setValidationError(null);
          }}
          placeholder="Add audit note or rationale (required for 'Verified' — e.g. 'Within ₹10 rounding tolerance', 'Amended in Tally v4')..."
          className="w-full rounded-xl border border-gray-200 p-2.5 text-xs text-gray-800 placeholder-gray-400 focus:border-purple-500 focus:outline-none"
        />
      </div>

      {/* Local audit decision history for this invoice */}
      {history.length > 0 && (
        <div className="pt-2 border-t border-gray-100">
          <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2">
            Session Decision Trail ({history.length})
          </p>
          <div className="space-y-1.5">
            {history.map((hist, idx) => (
              <div
                key={idx}
                className="flex items-start justify-between gap-2 rounded-lg bg-gray-50 px-3 py-1.5 text-xs text-gray-600"
              >
                <div>
                  <span className="font-semibold text-gray-900">{hist.label}</span>
                  {hist.note && (
                    <span className="text-gray-500 ml-1.5">
                      — &quot;{hist.note}&quot;
                    </span>
                  )}
                </div>
                <span className="text-[10px] text-gray-400 tabular-nums shrink-0">
                  {new Date(hist.decidedAt).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

// ── Main Review Workspace Component ──────────────────────────────────────────
interface Gstr1ReviewWorkspaceProps {
  result: Gstr1ReconcileResult;
  periodLabel?: string;
  runId?: string | null;
  userEmail?: string | null;
  onExit: () => void;
  initialInvoiceId?: string | null;
}

export function Gstr1ReviewWorkspace({
  result,
  periodLabel = "Current Period",
  runId,
  userEmail,
  onExit,
  initialInvoiceId,
}: Gstr1ReviewWorkspaceProps) {
  // Scoped key ensures new uploads / other runs never inherit stale decisions
  const scopeKey = useMemo(
    () => generateReviewScopeKey(result, runId, userEmail),
    [result, runId, userEmail]
  );

  const decisionsKey = useMemo(() => `${scopeKey}_decisions`, [scopeKey]);
  const sessionKey = useMemo(() => `${scopeKey}_session`, [scopeKey]);

  const allItems = useMemo(() => buildReviewQueueItems(result), [result]);

  // Selected item for comparison
  const [activeInvoiceId, setActiveInvoiceId] = useState<string | null>(
    () => initialInvoiceId || allItems[0]?.id || null
  );

  // Checkbox multi-selection (strictly independent from comparison!)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Filter tab for the queue
  const [filterTab, setFilterTab] = useState<
    "all" | "review_required" | "missing_in_gstr1" | "extra_in_gstr1" | "unreviewed" | "reviewed"
  >("all");

  const [searchQuery, setSearchQuery] = useState("");

  // Audit decision records per invoice ID
  const [decisions, setDecisions] = useState<Record<string, ReviewDecisionRecord[]>>({});

  // Save failure notice
  const [saveError, setSaveError] = useState<string | null>(null);

  // Focus preservation refs
  const lastCompareButtonRef = useRef<HTMLButtonElement | null>(null);

  // Responsive narrow check (laptop / tablet vs wide monitor)
  const [isNarrowScreen, setIsNarrowScreen] = useState(false);

  // Incremental rendering limit for ultra-smooth 60fps/120fps queue scrolling
  const [visibleLimit, setVisibleLimit] = useState(40);

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 1279px)");
    const onChange = () => setIsNarrowScreen(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  // Safe load of decision history
  useEffect(() => {
    const stored = safeStorageGet<Record<string, ReviewDecisionRecord[]>>(decisionsKey, {});
    setDecisions(stored);
  }, [decisionsKey]);

  // Persist decisions with explicit error handling
  const persistDecisions = useCallback(
    (updated: Record<string, ReviewDecisionRecord[]>) => {
      setDecisions(updated);
      const success = safeStorageSet(decisionsKey, updated);
      if (!success) {
        setSaveError("Browser storage is full. Review decisions could not be saved to localStorage.");
      } else {
        setSaveError(null);
      }
    },
    [decisionsKey]
  );

  // Save "Resume Review" session pointer
  useEffect(() => {
    if (!allItems.length) return;
    const reviewedCount = Object.keys(decisions).filter(
      (k) => decisions[k]?.length > 0 && decisions[k][decisions[k].length - 1].status !== "unreviewed"
    ).length;
    const remainingCount = allItems.length - reviewedCount;

    safeStorageSet(sessionKey, {
      periodLabel,
      remainingCount,
      totalCount: allItems.length,
      lastInvoiceId: activeInvoiceId,
      filterTab,
      searchQuery,
      lastReviewedAt: new Date().toISOString(),
    });
  }, [decisions, activeInvoiceId, allItems.length, sessionKey, periodLabel, filterTab, searchQuery]);

  // Filtered list
  const filteredItems = useMemo(() => {
    return allItems.filter((item) => {
      const history = decisions[item.id] || [];
      const currentDecision = history[history.length - 1];
      const hasDecision = currentDecision && currentDecision.status !== "unreviewed";

      if (filterTab === "review_required" && item.category !== "review_required") return false;
      if (filterTab === "missing_in_gstr1" && item.category !== "missing_in_gstr1") return false;
      if (filterTab === "extra_in_gstr1" && item.category !== "extra_in_gstr1") return false;
      if (filterTab === "unreviewed" && hasDecision) return false;
      if (filterTab === "reviewed" && !hasDecision) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        return (
          item.invoiceNumber.toLowerCase().includes(q) ||
          item.gstin.toLowerCase().includes(q) ||
          item.recipientName.toLowerCase().includes(q)
        );
      }

      return true;
    });
  }, [allItems, filterTab, searchQuery, decisions]);

  // Reset pagination limit when filter or search changes
  useEffect(() => {
    setVisibleLimit(40);
  }, [filterTab, searchQuery]);

  const activeIndex = useMemo(() => {
    return filteredItems.findIndex((it) => it.id === activeInvoiceId);
  }, [filteredItems, activeInvoiceId]);

  const activeItem = useMemo(() => {
    return allItems.find((it) => it.id === activeInvoiceId) || null;
  }, [allItems, activeInvoiceId]);

  // Accurate, internally consistent progress counts
  const progressMetrics = useMemo(() => {
    let reviewed = 0;
    let awaiting = 0;
    let queued = 0;
    let corrected = 0;

    allItems.forEach((it) => {
      const hist = decisions[it.id] || [];
      const last = hist[hist.length - 1];
      if (!last || last.status === "unreviewed") return;

      if (last.status === "reviewed") reviewed++;
      else if (last.status === "awaiting_clarification") awaiting++;
      else if (last.status === "queued_gstr1a") queued++;
      else if (last.status === "corrected_verified") corrected++;
    });

    const totalResolvedOrFlagged = reviewed + awaiting + queued + corrected;
    const remaining = Math.max(0, allItems.length - totalResolvedOrFlagged);

    return {
      total: allItems.length,
      reviewed,
      awaiting,
      queued,
      corrected,
      remaining,
    };
  }, [allItems, decisions]);

  // Handle recorded decision from the isolated panel
  const handleRecordDecision = useCallback(
    (status: DecisionStatus, label: string, note?: string) => {
      if (!activeItem) return;

      const record: ReviewDecisionRecord = {
        status,
        label,
        note,
        decidedBy: userEmail || "Auditor",
        decidedAt: new Date().toISOString(),
      };

      const existingHist = decisions[activeItem.id] || [];
      const updated = {
        ...decisions,
        [activeItem.id]: [...existingHist, record],
      };

      persistDecisions(updated);

      // Smoothly advance to next item in queue
      if (activeIndex >= 0 && activeIndex < filteredItems.length - 1) {
        setActiveInvoiceId(filteredItems[activeIndex + 1].id);
      }
    },
    [activeItem, userEmail, decisions, persistDecisions, activeIndex, filteredItems]
  );

  // Esc key hierarchy and keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeEl = document.activeElement;
      const isInput =
        activeEl instanceof HTMLInputElement ||
        activeEl instanceof HTMLTextAreaElement ||
        activeEl instanceof HTMLSelectElement ||
        (activeEl as HTMLElement)?.isContentEditable;

      if (e.key === "Escape") {
        if (isInput) {
          (activeEl as HTMLElement)?.blur();
          return;
        }
        if (isNarrowScreen && activeInvoiceId) {
          e.preventDefault();
          setActiveInvoiceId(null);
          // Restore focus to compare button
          setTimeout(() => lastCompareButtonRef.current?.focus(), 50);
        } else {
          e.preventDefault();
          onExit();
        }
        return;
      }

      // J / K queue navigation when not focused on an input
      if (!isInput && !e.metaKey && !e.ctrlKey) {
        if (e.key.toLowerCase() === "j" || e.key === "ArrowDown") {
          e.preventDefault();
          if (activeIndex >= 0 && activeIndex < filteredItems.length - 1) {
            setActiveInvoiceId(filteredItems[activeIndex + 1].id);
          }
        } else if (e.key.toLowerCase() === "k" || e.key === "ArrowUp") {
          e.preventDefault();
          if (activeIndex > 0) {
            setActiveInvoiceId(filteredItems[activeIndex - 1].id);
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isNarrowScreen, activeInvoiceId, activeIndex, filteredItems, onExit]);

  // Checkbox toggle (strictly independent from comparison)
  const toggleSelect = useCallback((id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleOpenCompare = useCallback((id: string) => {
    setActiveInvoiceId(id);
  }, []);

  const currentItemHistory = activeItem ? decisions[activeItem.id] || [] : [];
  const latestDecision = currentItemHistory[currentItemHistory.length - 1];

  return (
    <div className="flex flex-col min-h-screen -mx-4 sm:-mx-6 -mt-2 bg-[#F6F5FA] text-[var(--text-primary)]">
      {/* ── Top Focus Strip ── */}
      <header className="sticky top-0 z-30 flex flex-wrap items-center justify-between gap-3 border-b border-[#E6E0ED] bg-white/95 px-5 py-3 shadow-xs backdrop-blur-md">
        <div className="flex items-center gap-3">
          <AccessibleTooltip content="Return to overview results" shortcut="Esc" side="bottom">
            <button
              type="button"
              onClick={onExit}
              className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3.5 py-1.5 text-xs font-semibold text-gray-700 shadow-xs hover:bg-gray-50 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span>Back to Results</span>
            </button>
          </AccessibleTooltip>

          <div className="hidden sm:block h-4 w-px bg-gray-200" />

          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold tracking-tight text-[var(--ink)]">
                Review Workspace
              </span>
              <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-semibold text-purple-800">
                {periodLabel}
              </span>
            </div>
            <p className="text-[11px] font-medium text-gray-500">
              <span className="text-purple-700 font-semibold">{progressMetrics.reviewed}</span> reviewed ·{" "}
              <span className="text-amber-700 font-semibold">{progressMetrics.awaiting}</span> awaiting clarification ·{" "}
              <span className="font-semibold text-gray-700">{progressMetrics.remaining}</span> remaining
            </p>
          </div>
        </div>

        {/* Clear batch action wording */}
        {selectedIds.size > 0 && (
          <div className="flex items-center gap-2 rounded-full bg-purple-50 px-3 py-1 border border-purple-200">
            <span className="text-xs font-semibold text-purple-900">
              {selectedIds.size} selected
            </span>
            <button
              type="button"
              onClick={() => {
                const updated = { ...decisions };
                selectedIds.forEach((id) => {
                  const hist = updated[id] || [];
                  updated[id] = [
                    ...hist,
                    {
                      status: "reviewed",
                      label: "Batch Accepted Variance",
                      note: `Batch accepted for ${selectedIds.size} selected records`,
                      decidedBy: userEmail || "Auditor",
                      decidedAt: new Date().toISOString(),
                    },
                  ];
                });
                persistDecisions(updated);
                setSelectedIds(new Set());
              }}
              className="text-[11px] font-semibold text-purple-700 hover:text-purple-900 underline ml-1"
            >
              Accept variance for {selectedIds.size} selected
            </button>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              className="text-[11px] text-gray-500 hover:text-gray-700 ml-1"
            >
              Clear
            </button>
          </div>
        )}
      </header>

      {/* Storage failure notice banner */}
      {saveError && (
        <div className="flex items-center gap-2 bg-rose-600 px-5 py-2 text-xs font-medium text-white shadow-xs">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{saveError}</span>
        </div>
      )}

      {/* ── Main Workspace Body ── */}
      <div className="flex flex-1 min-h-[calc(100vh-60px)]">
        {/* Left Column: Issue Queue */}
        <aside
          className={`flex flex-col border-r border-[#E6E0ED] bg-white transition-all duration-200 ${
            isNarrowScreen
              ? activeInvoiceId
                ? "hidden"
                : "w-full"
              : "w-[360px] xl:w-[400px] shrink-0"
          }`}
        >
          {/* Filter tabs */}
          <div className="p-3 border-b border-[#F0EBF5] space-y-2">
            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-gray-400" />
              <input
                type="text"
                placeholder="Search invoice # or GSTIN..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-xl border border-gray-200 bg-[#FAFAFC] pl-8 pr-3 py-1.5 text-xs text-gray-800 focus:border-purple-500 focus:outline-none"
              />
            </div>

            <div className="flex flex-wrap gap-1">
              {[
                { id: "all", label: `All (${allItems.length})` },
                {
                  id: "review_required",
                  label: `Review (${allItems.filter((i) => i.category === "review_required").length})`,
                },
                {
                  id: "missing_in_gstr1",
                  label: `Missing (${allItems.filter((i) => i.category === "missing_in_gstr1").length})`,
                },
                {
                  id: "unreviewed",
                  label: `Remaining (${progressMetrics.remaining})`,
                },
                {
                  id: "reviewed",
                  label: `Done (${progressMetrics.reviewed + progressMetrics.awaiting})`,
                },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setFilterTab(tab.id as any)}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    filterTab === tab.id
                      ? "bg-[var(--ink)] text-white shadow-xs"
                      : "bg-[#F4F2F7] text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {/* Queue list with incremental rendering for silky-smooth 60fps/120fps scrolling */}
          <div className="flex-1 overflow-y-auto divide-y divide-[#F0EBF5] pb-20">
            {filteredItems.length === 0 ? (
              <div className="p-8 text-center text-gray-400 text-xs">
                No invoices found in this view.
              </div>
            ) : (
              <>
                {filteredItems.slice(0, visibleLimit).map((item) => {
                  const isActive = activeInvoiceId === item.id;
                  const isSelected = selectedIds.has(item.id);
                  const history = decisions[item.id] || [];
                  const latest = history[history.length - 1];

                  return (
                    <QueueItemRow
                      key={item.id}
                      item={item}
                      isActive={isActive}
                      isSelected={isSelected}
                      latestDecision={latest}
                      onSelect={toggleSelect}
                      onCompare={handleOpenCompare}
                      compareButtonRef={(el) => {
                        if (isActive) lastCompareButtonRef.current = el;
                      }}
                    />
                  );
                })}

                {filteredItems.length > visibleLimit && (
                  <div className="p-3 text-center">
                    <button
                      type="button"
                      onClick={() => setVisibleLimit((v) => v + 40)}
                      className="rounded-full bg-gray-100 px-4 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-200 transition-colors"
                    >
                      Load more ({visibleLimit} of {filteredItems.length})
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </aside>

        {/* Right Column: Comparison Workspace */}
        <main
          className={`flex-1 flex flex-col overflow-y-auto bg-[#F6F5FA] p-4 sm:p-6 pb-28 ${
            isNarrowScreen && !activeInvoiceId ? "hidden" : "block"
          }`}
        >
          {activeItem ? (
            <div className="max-w-4xl mx-auto w-full space-y-4">
              {/* Back to queue button on mobile/laptop */}
              {isNarrowScreen && (
                <button
                  type="button"
                  onClick={() => {
                    setActiveInvoiceId(null);
                    setTimeout(() => lastCompareButtonRef.current?.focus(), 50);
                  }}
                  className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3.5 py-1.5 text-xs font-semibold text-gray-700 shadow-xs hover:bg-gray-50"
                >
                  <ChevronLeft className="h-4 w-4" />
                  <span>Back to Queue</span>
                </button>
              )}

              {/* Comparison Header Card */}
              <div className="rounded-2xl border border-[#E6E0ED] bg-white p-5 shadow-xs">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2.5">
                      <h2 className="text-xl font-bold tracking-tight text-gray-900">
                        {activeItem.invoiceNumber}
                      </h2>
                      <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-800">
                        {activeItem.issueCode}
                      </span>
                      <span className="text-xs text-gray-500">{activeItem.invoiceDate}</span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-gray-600">
                      <span className="font-medium text-gray-400">Counterparty:</span>
                      <GstinCell gstin={activeItem.gstin} truncate={false} className="font-mono font-semibold" />
                      {activeItem.recipientName && <span>· {activeItem.recipientName}</span>}
                    </div>
                  </div>

                  {/* Previous / Next buttons with accessible tooltips */}
                  <div className="flex items-center gap-1.5">
                    <AccessibleTooltip content="Previous invoice" shortcut="K" side="bottom">
                      <button
                        type="button"
                        disabled={activeIndex <= 0}
                        onClick={() => {
                          if (activeIndex > 0) setActiveInvoiceId(filteredItems[activeIndex - 1].id);
                        }}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-xs hover:bg-gray-50 disabled:opacity-40"
                        aria-label="Previous invoice (K)"
                      >
                        <ChevronLeft className="h-3.5 w-3.5" />
                        <span>Prev</span>
                      </button>
                    </AccessibleTooltip>

                    <span className="text-xs text-gray-400 tabular-nums px-1">
                      {activeIndex + 1} of {filteredItems.length}
                    </span>

                    <AccessibleTooltip content="Next invoice" shortcut="J" side="bottom">
                      <button
                        type="button"
                        disabled={activeIndex >= filteredItems.length - 1}
                        onClick={() => {
                          if (activeIndex < filteredItems.length - 1) {
                            setActiveInvoiceId(filteredItems[activeIndex + 1].id);
                          }
                        }}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-xs hover:bg-gray-50 disabled:opacity-40"
                        aria-label="Next invoice (J)"
                      >
                        <span>Next</span>
                        <ChevronRight className="h-3.5 w-3.5" />
                      </button>
                    </AccessibleTooltip>
                  </div>
                </div>

                {/* Evidence Explanation Banner */}
                <div className="mt-4 rounded-xl border border-amber-200/70 bg-amber-50/50 p-3.5 text-xs text-amber-950">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-amber-900">{activeItem.what}</p>
                      {activeItem.why && (
                        <p className="mt-0.5 text-amber-800 leading-relaxed">{activeItem.why}</p>
                      )}
                      {activeItem.next && (
                        <p className="mt-1 font-medium text-amber-900">
                          Recommended next action: {activeItem.next}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Side-by-Side Comparison Table */}
              <div className="overflow-hidden rounded-2xl border border-[#E6E0ED] bg-white shadow-xs">
                <div className="border-b border-gray-100 px-5 py-3.5 bg-gray-50/50">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">
                    Field Comparison: Books (Sales Register) vs Portal (GSTR-1)
                  </h3>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-gray-100 bg-[#FBF9FD] text-[11px] font-semibold text-gray-500">
                        <th className="px-5 py-2.5">Field</th>
                        <th className="px-5 py-2.5">Sales Register (Books)</th>
                        <th className="px-5 py-2.5">GSTR-1 (Portal)</th>
                        <th className="px-5 py-2.5">Variance / Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {/* Taxable Value */}
                      <tr className={activeItem.taxableDiff !== 0 ? "bg-amber-50/30" : ""}>
                        <td className="px-5 py-2.5 font-medium text-gray-900">Taxable Value</td>
                        <td className="px-5 py-2.5 font-semibold text-gray-800 tabular-nums">
                          {formatInr(activeItem.books.taxable)}
                        </td>
                        <td className="px-5 py-2.5 font-semibold text-gray-800 tabular-nums">
                          {formatInr(activeItem.portal.taxable)}
                        </td>
                        <td className="px-5 py-2.5">
                          {activeItem.taxableDiff === 0 ? (
                            <span className="inline-flex items-center gap-1 text-emerald-700 font-medium">
                              <CheckCircle2 className="h-3 w-3" /> Matched
                            </span>
                          ) : (
                            <span className="inline-flex rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-800 tabular-nums">
                              Δ {formatInr(activeItem.taxableDiff)}
                            </span>
                          )}
                        </td>
                      </tr>

                      {/* IGST */}
                      <tr>
                        <td className="px-5 py-2.5 font-medium text-gray-700">Integrated Tax (IGST)</td>
                        <td className="px-5 py-2.5 tabular-nums text-gray-700">{formatInr(activeItem.books.igst)}</td>
                        <td className="px-5 py-2.5 tabular-nums text-gray-700">{formatInr(activeItem.portal.igst)}</td>
                        <td className="px-5 py-2.5">
                          {activeItem.books.igst === activeItem.portal.igst ? (
                            <span className="text-gray-400">Match</span>
                          ) : (
                            <span className="font-semibold text-amber-800 tabular-nums">
                              Δ {formatInr(activeItem.portal.igst - activeItem.books.igst)}
                            </span>
                          )}
                        </td>
                      </tr>

                      {/* CGST */}
                      <tr>
                        <td className="px-5 py-2.5 font-medium text-gray-700">Central Tax (CGST)</td>
                        <td className="px-5 py-2.5 tabular-nums text-gray-700">{formatInr(activeItem.books.cgst)}</td>
                        <td className="px-5 py-2.5 tabular-nums text-gray-700">{formatInr(activeItem.portal.cgst)}</td>
                        <td className="px-5 py-2.5">
                          {activeItem.books.cgst === activeItem.portal.cgst ? (
                            <span className="text-gray-400">Match</span>
                          ) : (
                            <span className="font-semibold text-amber-800 tabular-nums">
                              Δ {formatInr(activeItem.portal.cgst - activeItem.books.cgst)}
                            </span>
                          )}
                        </td>
                      </tr>

                      {/* SGST */}
                      <tr>
                        <td className="px-5 py-2.5 font-medium text-gray-700">State Tax (SGST)</td>
                        <td className="px-5 py-2.5 tabular-nums text-gray-700">{formatInr(activeItem.books.sgst)}</td>
                        <td className="px-5 py-2.5 tabular-nums text-gray-700">{formatInr(activeItem.portal.sgst)}</td>
                        <td className="px-5 py-2.5">
                          {activeItem.books.sgst === activeItem.portal.sgst ? (
                            <span className="text-gray-400">Match</span>
                          ) : (
                            <span className="font-semibold text-amber-800 tabular-nums">
                              Δ {formatInr(activeItem.portal.sgst - activeItem.books.sgst)}
                            </span>
                          )}
                        </td>
                      </tr>

                      {/* Total Tax */}
                      <tr className="bg-gray-50/40 font-semibold">
                        <td className="px-5 py-2.5 text-gray-900">Total Tax Liability</td>
                        <td className="px-5 py-2.5 text-gray-900 tabular-nums">{formatInr(activeItem.books.totalTax)}</td>
                        <td className="px-5 py-2.5 text-gray-900 tabular-nums">{formatInr(activeItem.portal.totalTax)}</td>
                        <td className="px-5 py-2.5">
                          {activeItem.totalTaxDiff === 0 ? (
                            <span className="inline-flex items-center gap-1 text-emerald-700 font-medium">
                              <CheckCircle2 className="h-3 w-3" /> Matched
                            </span>
                          ) : (
                            <span className="inline-flex rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-800 tabular-nums">
                              Δ {formatInr(activeItem.totalTaxDiff)}
                            </span>
                          )}
                        </td>
                      </tr>

                      {/* Place of Supply */}
                      <tr>
                        <td className="px-5 py-2.5 font-medium text-gray-700">Place of Supply (PoS)</td>
                        <td className="px-5 py-2.5 text-gray-700">{activeItem.books.pos || "—"}</td>
                        <td className="px-5 py-2.5 text-gray-700">{activeItem.portal.pos || "—"}</td>
                        <td className="px-5 py-2.5">
                          {activeItem.books.pos === activeItem.portal.pos ? (
                            <span className="text-gray-400">Match</span>
                          ) : (
                            <span className="rounded bg-rose-100 px-2 py-0.5 font-semibold text-rose-800">
                              PoS Mismatch
                            </span>
                          )}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Isolated Decision Action Panel */}
              <DecisionActionPanel
                itemId={activeItem.id}
                latestDecision={latestDecision}
                history={currentItemHistory}
                onRecord={handleRecordDecision}
              />

              <p className="text-[11px] text-gray-400 text-center pb-6">
                Audit notes and decisions are stored in your session workspace and do not modify external GST portal returns.
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center flex-1 text-center text-gray-400 text-xs">
              <FileText className="h-8 w-8 text-gray-300 mb-2" />
              <p>Select an invoice from the queue to compare books with portal values.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
