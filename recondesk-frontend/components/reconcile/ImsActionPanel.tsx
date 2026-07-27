"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import {
  EMPTY_IMS_CONFIRM_STEPS,
  IMS_HOLD_MS,
  applyWritebackOutcome,
  buildConfirmationSummary,
  caActionLabel,
  canStartImsHold,
  typedCountMatchesExpected,
  clearSelection,
  initRowStates,
  isHighConfidenceAccept,
  isOverride,
  overrideCountInSelection,
  resetImsConfirmSteps,
  selectHighConfidenceAccepts,
  selectedRows,
  submitMode,
  unavailableHint,
  uniformSelectedAction,
  writebackOutcomeFromPoll,
  type ImsConfirmSteps,
  type ImsInvoiceRecommendation,
  type ImsRecommendedAction,
  type ImsRecommendationsResponse,
  type ImsRowState,
} from "@/components/reconcile/imsActionLogic";
import { formatINR } from "@/lib/format";
import { imsApi, isApiError } from "@/lib/api";

const POLL_MS = 2_000;
const MAX_POLLS = 45;

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "unavailable"; reason: string }
  | { status: "available"; data: ImsRecommendationsResponse }
  | { status: "error"; message: string };

type Props = {
  runId: string;
  authToken: string;
  /** Optional bump to clear loaded recommendations (never auto-loads). */
  refreshKey?: number;
};

function actionBadgeClass(action: ImsRecommendedAction): string {
  switch (action) {
    case "accept":
      return "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200/80";
    case "reject":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "hold":
      return "bg-amber-50 text-amber-900 ring-1 ring-amber-200";
  }
}

function confidenceLabel(score: number): string {
  return `${Math.round(score * 100)}%`;
}

function amountLabel(paise: number | null | undefined): string | null {
  if (paise == null || !Number.isFinite(paise)) return null;
  return formatINR(paise / 100);
}

/**
 * CA-facing IMS Action panel — recommendations are drafts until Load;
 * GSTN writes require count-based confirm + hold-to-commit.
 * Mounted like AuditObservationsPanel (purchase results IMS tab).
 */
export function ImsActionPanel({ runId, authToken, refreshKey = 0 }: Props) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "idle" });
  const [rows, setRows] = useState<Map<string, ImsRowState>>(new Map());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmSteps, setConfirmSteps] = useState<ImsConfirmSteps>(
    EMPTY_IMS_CONFIRM_STEPS
  );
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [pollNote, setPollNote] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [phase4Note, setPhase4Note] = useState<string | null>(null);

  // Never auto-load on mount / refreshKey — only clear stale draft state.
  useEffect(() => {
    setLoadState({ status: "idle" });
    setRows(new Map());
    setConfirmOpen(false);
    setConfirmSteps(resetImsConfirmSteps());
    setPollNote(null);
    setActionError(null);
    setPhase4Note(null);
  }, [runId, refreshKey]);

  const loadRecommendations = useCallback(async () => {
    if (!runId || !authToken) return;
    setLoadState({ status: "loading" });
    setActionError(null);
    setPollNote(null);
    setConfirmOpen(false);
    setConfirmSteps(resetImsConfirmSteps());
    try {
      const data = await imsApi.getRecommendations(authToken, runId);
      if (!data.available) {
        setLoadState({
          status: "unavailable",
          reason: data.reason || "unavailable",
        });
        setRows(new Map());
        return;
      }
      setLoadState({ status: "available", data });
      setRows(initRowStates(data.invoices || []));
    } catch (err) {
      const message = isApiError(err)
        ? err.detail
        : err instanceof Error
          ? err.message
          : "Failed to load IMS recommendations";
      // 404 / not wired → unavailable (not confirmed zero)
      if (isApiError(err) && (err.status === 404 || err.status === 501)) {
        setLoadState({
          status: "unavailable",
          reason: "not_wired",
        });
      } else {
        setLoadState({ status: "error", message });
      }
      setRows(new Map());
    }
  }, [authToken, runId]);

  const invoices: ImsInvoiceRecommendation[] =
    loadState.status === "available" ? loadState.data.invoices : [];

  const selected = selectedRows(invoices, rows);
  const bulkAction = uniformSelectedAction(selected);
  const bulkOverrideCount = overrideCountInSelection(selected);

  const updateRow = useCallback(
    (invoiceId: string, patch: Partial<ImsRowState>) => {
      setRows((prev) => {
        const cur = prev.get(invoiceId);
        if (!cur) return prev;
        const next = new Map(prev);
        next.set(invoiceId, { ...cur, ...patch });
        return next;
      });
    },
    []
  );

  const openBulkConfirm = useCallback(() => {
    if (selected.length === 0 || !bulkAction) return;
    setConfirmSteps(resetImsConfirmSteps());
    setConfirmOpen(true);
    setActionError(null);
  }, [bulkAction, selected.length]);

  const openSingleConfirm = useCallback(
    (invoiceId: string) => {
      // Select only this row for confirm.
      setRows((prev) => {
        const next = clearSelection(prev);
        const cur = next.get(invoiceId);
        if (cur) next.set(invoiceId, { ...cur, selected: true });
        return next;
      });
      setConfirmSteps(resetImsConfirmSteps());
      setConfirmOpen(true);
      setActionError(null);
    },
    []
  );

  const runConfirmAndPoll = useCallback(async () => {
    const currentSelected = selectedRows(invoices, rows);
    const action = uniformSelectedAction(currentSelected);
    if (!action || currentSelected.length === 0) return;

    const summary = buildConfirmationSummary(action, currentSelected.length);
    const invoiceIds = currentSelected.map(({ inv }) => inv.invoice_id);

    setConfirmBusy(true);
    setActionError(null);
    setPollNote(null);
    setRows((prev) => applyWritebackOutcome(prev, invoiceIds, "pending"));

    try {
      const res = await imsApi.confirmActions(authToken, runId, {
        confirmed: true,
        confirmation_summary: summary,
        expected_count: currentSelected.length,
        invoices: currentSelected.map(({ inv, row }) => ({
          invoice_id: inv.invoice_id,
          chosen_action: row.chosenAction,
          recommended_action: inv.recommended_action,
          section: inv.section || "b2b",
          writeback_payload: inv.writeback_payload ?? null,
        })),
      });

      if (res.phase4_note) setPhase4Note(res.phase4_note);

      setPollNote(
        "Request accepted for processing — waiting for GSTN inner status (P). Outer accept alone is never enough."
      );

      if (!res.reference_id) {
        setRows((prev) =>
          applyWritebackOutcome(
            prev,
            invoiceIds,
            "failed",
            "Missing reference_id from confirm"
          )
        );
        setConfirmBusy(false);
        setConfirmOpen(false);
        setConfirmSteps(resetImsConfirmSteps());
        return;
      }

      let finalOutcome = writebackOutcomeFromPoll({
        is_complete: false,
        has_errors: false,
        outcome: "pending",
      });

      for (let i = 0; i < MAX_POLLS; i++) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        let st;
        try {
          st = await imsApi.actionStatus(authToken, runId, res.reference_id);
        } catch (err) {
          setActionError(
            isApiError(err)
              ? err.detail
              : err instanceof Error
                ? err.message
                : "Status poll failed"
          );
          setRows((prev) =>
            applyWritebackOutcome(prev, invoiceIds, "failed", "poll failed")
          );
          setConfirmBusy(false);
          setConfirmOpen(false);
          setConfirmSteps(resetImsConfirmSteps());
          setPollNote(null);
          return;
        }

        finalOutcome = writebackOutcomeFromPoll(st);
        setRows((prev) =>
          applyWritebackOutcome(
            prev,
            invoiceIds,
            finalOutcome === "pending" ? "pending" : finalOutcome,
            st.error_message || null
          )
        );

        if (finalOutcome === "confirmed") {
          setPollNote(
            "GSTN confirmed IMS action (inner status_cd P)."
          );
          // PHASE 4 HOOK — post-action GSTR-2B / IMS overlay sync.
          // After live UI testing, call a 2B re-fetch / overlay refresh here
          // using res.phase4_post_action_2b_sync_pending.
          break;
        }
        if (finalOutcome === "failed") {
          setPollNote(null);
          setActionError(
            st.error_message ||
              `GSTN reported errors (status_cd=${st.status_cd || "—"})`
          );
          break;
        }
        setPollNote(
          `Waiting on GSTN IMS… status_cd=${st.status_cd ?? "—"} (poll ${i + 1}/${MAX_POLLS})`
        );
      }

      if (finalOutcome === "pending") {
        setActionError(
          "Timed out waiting for GSTN IMS confirmation. Do not assume success."
        );
        setRows((prev) =>
          applyWritebackOutcome(prev, invoiceIds, "failed", "poll timeout")
        );
      }
    } catch (err) {
      setActionError(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "IMS confirm failed"
      );
      setRows((prev) =>
        applyWritebackOutcome(prev, invoiceIds, "failed", "confirm failed")
      );
    } finally {
      setConfirmBusy(false);
      setConfirmOpen(false);
      setConfirmSteps(resetImsConfirmSteps());
    }
  }, [authToken, invoices, rows, runId]);

  return (
    <section className={sectionContainerClass} aria-label="IMS actions">
      <SectionHeader
        title="IMS Actions"
        dotColor="#111111"
        actions={
          loadState.status === "available" ? (
            <span className="inline-flex rounded-full bg-[var(--ink)] px-3 py-1 text-xs font-semibold text-white">
              {invoices.length} invoice{invoices.length === 1 ? "" : "s"}
            </span>
          ) : null
        }
      />

      <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-gray-500">
        Review ReconDesk Accept / Reject / Hold recommendations, then confirm
        explicitly before anything is written back to GSTN. Nothing runs on page
        open, row click, or hover.
      </p>

      {/* Amber unconfirmed-suggestion chrome — Load never fires automatically */}
      <div className="mt-4 rounded-lg border border-dashed border-amber-300/80 bg-amber-50/40 px-3 py-2.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-900/80">
              Unconfirmed recommendations
            </p>
            <p className="mt-0.5 text-[12px] text-amber-950/70">
              Draft only until you Load, then Confirm — not a pre-filled GSTN
              decision.
            </p>
          </div>
          {loadState.status !== "available" ? (
            <button
              type="button"
              disabled={loadState.status === "loading" || !authToken}
              onClick={() => void loadRecommendations()}
              className="rounded-full border border-amber-800/20 bg-white px-3 py-1 text-[12px] font-semibold text-amber-950 hover:bg-amber-50 disabled:opacity-40"
            >
              {loadState.status === "loading" ? "Loading…" : "Load recommendations"}
            </button>
          ) : (
            <button
              type="button"
              disabled={confirmBusy}
              onClick={() => void loadRecommendations()}
              className="rounded-full px-3 py-1 text-[12px] font-medium text-amber-900/70 hover:bg-amber-100/60 disabled:opacity-40"
            >
              Reload
            </button>
          )}
        </div>

        {loadState.status === "loading" ? (
          <p className="mt-2 flex items-center gap-2 text-[12px] text-amber-950/70">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading draft recommendations…
          </p>
        ) : null}

        {loadState.status === "idle" ? (
          <p className="mt-2 text-[12px] text-amber-950/70">
            Click Load for an optional draft from reconcile + IMS overlay. This
            does not write to GSTN.
          </p>
        ) : null}

        {loadState.status === "unavailable" ? (
          <p className="mt-2 text-[12px] text-amber-950/70">
            {unavailableHint(
              loadState.reason === "not_wired"
                ? "not_wired"
                : loadState.reason
            )}
          </p>
        ) : null}

        {loadState.status === "error" ? (
          <p className="mt-2 text-[12px] text-red-700">{loadState.message}</p>
        ) : null}
      </div>

      {loadState.status === "available" && invoices.length === 0 ? (
        <p className="mt-4 text-sm text-gray-500">
          No invoices need IMS action for this period.
        </p>
      ) : null}

      {loadState.status === "available" && invoices.length > 0 ? (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[#F0F0F0] pt-4">
            <button
              type="button"
              onClick={() =>
                setRows((prev) => selectHighConfidenceAccepts(invoices, prev))
              }
              className="rounded-full border border-[#E8E8EA] bg-white px-3 py-1.5 text-[12px] font-semibold text-[var(--ink)] hover:bg-[#F7F7F8]"
            >
              Select high-confidence Accept (
              {loadState.data.high_confidence_accept_count})
            </button>
            <button
              type="button"
              onClick={() => setRows((prev) => clearSelection(prev))}
              className="rounded-full px-3 py-1.5 text-[12px] font-medium text-gray-500 hover:bg-gray-100"
            >
              Clear selection
            </button>
            <button
              type="button"
              disabled={
                selected.length === 0 || bulkAction == null || confirmBusy
              }
              onClick={openBulkConfirm}
              className="rounded-full bg-[var(--ink)] px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40"
            >
              {selected.length === 0
                ? "Confirm selected…"
                : bulkAction == null
                  ? "Mixed actions — align before bulk confirm"
                  : `Confirm ${caActionLabel(bulkAction).toLowerCase()} (${selected.length})…`}
            </button>
            {bulkOverrideCount > 0 ? (
              <span className="rounded-full bg-[#FEF3C7] px-2.5 py-1 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-300/80">
                {bulkOverrideCount} override
                {bulkOverrideCount === 1 ? "" : "s"} in selection
              </span>
            ) : null}
          </div>

          <ul className="mt-4 space-y-2">
            {invoices.map((inv) => {
              const row = rows.get(inv.invoice_id);
              if (!row) return null;
              return (
                <ImsInvoiceRow
                  key={inv.invoice_id}
                  inv={inv}
                  row={row}
                  disabled={confirmBusy}
                  onToggleSelect={() =>
                    updateRow(inv.invoice_id, { selected: !row.selected })
                  }
                  onToggleWhy={() =>
                    updateRow(inv.invoice_id, {
                      whyExpanded: !row.whyExpanded,
                    })
                  }
                  onChosenAction={(action) =>
                    updateRow(inv.invoice_id, { chosenAction: action })
                  }
                  onConfirmOne={() => openSingleConfirm(inv.invoice_id)}
                />
              );
            })}
          </ul>
        </>
      ) : null}

      {actionError ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {actionError}
        </div>
      ) : null}

      {pollNote ? (
        <p className="mt-3 flex items-center gap-2 text-[12px] text-gray-500">
          {confirmBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {pollNote}
        </p>
      ) : null}

      {phase4Note ? (
        <p className="mt-2 rounded-lg border border-dashed border-gray-300 bg-[#FAFAFB] px-3 py-2 text-[11px] text-gray-500">
          Phase 4 hook (not built): {phase4Note}
        </p>
      ) : null}

      {confirmOpen && bulkAction && selected.length > 0 ? (
        <ImsDeliberateConfirm
          action={bulkAction}
          count={selected.length}
          overrideCount={bulkOverrideCount}
          summary={buildConfirmationSummary(bulkAction, selected.length)}
          steps={confirmSteps}
          onStepsChange={setConfirmSteps}
          onCommit={() => void runConfirmAndPoll()}
          onCancel={() => {
            setConfirmOpen(false);
            setConfirmSteps(resetImsConfirmSteps());
          }}
          busy={confirmBusy}
        />
      ) : null}
    </section>
  );
}

function ImsInvoiceRow({
  inv,
  row,
  disabled,
  onToggleSelect,
  onToggleWhy,
  onChosenAction,
  onConfirmOne,
}: {
  inv: ImsInvoiceRecommendation;
  row: ImsRowState;
  disabled?: boolean;
  onToggleSelect: () => void;
  onToggleWhy: () => void;
  onChosenAction: (a: ImsRecommendedAction) => void;
  onConfirmOne: () => void;
}) {
  const overridden = isOverride(inv.recommended_action, row.chosenAction);
  const amt = amountLabel(inv.amount_paise);
  const mode = submitMode(inv.recommended_action, row.chosenAction);

  return (
    <li
      className={`rounded-xl border bg-white px-3 py-3 shadow-[var(--shadow-soft)] ${
        overridden
          ? "border-amber-300/90 ring-1 ring-amber-200/60"
          : "border-[#F0F0F0]"
      }`}
    >
      <div className="flex flex-wrap items-start gap-3">
        <label className="mt-1 flex shrink-0 items-center">
          <input
            type="checkbox"
            checked={row.selected}
            disabled={disabled || row.writeback === "pending"}
            onChange={onToggleSelect}
            onClick={(e) => e.stopPropagation()}
            className="h-4 w-4 rounded border-gray-300 text-[var(--ink)] focus:ring-[var(--ink)]"
            aria-label={`Select ${inv.invoice_number}`}
          />
        </label>

        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${actionBadgeClass(inv.recommended_action)}`}
            >
              Rec: {caActionLabel(inv.recommended_action)}
            </span>
            <span className="inline-flex rounded-full bg-[#F0F0F0] px-2.5 py-0.5 font-mono text-[11px] font-medium text-gray-700">
              {confidenceLabel(inv.confidence_score)}
            </span>
            {isHighConfidenceAccept(inv) ? (
              <span className="text-[11px] font-medium text-emerald-700">
                High-confidence Accept
              </span>
            ) : null}
            {overridden ? (
              <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[11px] font-semibold text-amber-900">
                Override → {caActionLabel(row.chosenAction)}
              </span>
            ) : (
              <span className="text-[11px] text-gray-400">
                Straight confirm
              </span>
            )}
            <WritebackBadge outcome={row.writeback} />
          </div>

          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <p className="font-mono text-[13px] font-semibold text-[var(--ink)]">
              {inv.invoice_number}
            </p>
            <p className="font-mono text-[12px] text-gray-500">
              {inv.supplier_gstin}
            </p>
            {inv.supplier_name ? (
              <p className="text-[12px] text-gray-500">{inv.supplier_name}</p>
            ) : null}
            {amt ? (
              <p className="font-mono text-[12px] text-gray-700">{amt}</p>
            ) : null}
          </div>

          <button
            type="button"
            onClick={onToggleWhy}
            className="flex w-full items-center justify-between gap-2 text-left text-[12px] font-medium text-gray-600 hover:text-[var(--ink)]"
            aria-expanded={row.whyExpanded}
          >
            <span className="min-w-0 truncate">
              {row.whyExpanded
                ? "Hide why"
                : inv.human_readable_why || "Why this recommendation"}
            </span>
            <ChevronDown
              className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${
                row.whyExpanded ? "rotate-180" : ""
              }`}
            />
          </button>
          {row.whyExpanded ? (
            <div className="rounded-lg border border-[#E8E8EA] bg-[#FAFAFB] px-3 py-2.5">
              <p className="text-[13px] leading-relaxed text-gray-700">
                {inv.human_readable_why}
              </p>
              {inv.reason_codes?.length ? (
                <p className="mt-2 font-mono text-[11px] text-gray-400">
                  {inv.reason_codes.join(" · ")}
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
              Your action
            </span>
            {(["accept", "reject", "hold"] as ImsRecommendedAction[]).map(
              (a) => (
                <button
                  key={a}
                  type="button"
                  disabled={disabled || row.writeback === "pending"}
                  onClick={() => onChosenAction(a)}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-semibold disabled:opacity-40 ${
                    row.chosenAction === a
                      ? overridden && a !== inv.recommended_action
                        ? "bg-amber-900 text-white"
                        : "bg-[var(--ink)] text-white"
                      : "bg-[#F0F0F0] text-gray-600 hover:bg-[#E8E8EA]"
                  }`}
                >
                  {caActionLabel(a)}
                </button>
              )
            )}
            <button
              type="button"
              disabled={
                disabled ||
                row.writeback === "pending" ||
                row.writeback === "confirmed"
              }
              onClick={onConfirmOne}
              className="ml-auto rounded-full border border-[#E8E8EA] px-3 py-1 text-[11px] font-semibold text-[var(--ink)] hover:bg-[#F7F7F8] disabled:opacity-40"
            >
              Confirm {caActionLabel(row.chosenAction).toLowerCase()}…
            </button>
          </div>
          {overridden ? (
            <p className="text-[11px] text-amber-900/80">
              Logged as <span className="font-semibold">{mode}</span> — CA
              changed ReconDesk&apos;s recommendation before confirm.
            </p>
          ) : null}
          {row.writebackError ? (
            <p className="text-[11px] text-red-600">{row.writebackError}</p>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function WritebackBadge({
  outcome,
}: {
  outcome: ImsRowState["writeback"];
}) {
  if (outcome === "idle") return null;
  const tone =
    outcome === "confirmed"
      ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
      : outcome === "failed"
        ? "bg-red-50 text-red-700 ring-red-200"
        : "bg-gray-100 text-gray-600 ring-gray-200";
  const label =
    outcome === "confirmed"
      ? "GSTN confirmed"
      : outcome === "failed"
        ? "Failed"
        : "Pending GSTN";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${tone}`}
    >
      {label}
    </span>
  );
}

/**
 * Dark portal-write friction — count-based confirm + hold-to-commit.
 * Mirrors OffsetDeliberateConfirm; never a vague single Confirm button.
 */
function ImsDeliberateConfirm({
  action,
  count,
  overrideCount,
  summary,
  steps,
  onStepsChange,
  onCommit,
  onCancel,
  busy,
}: {
  action: ImsRecommendedAction;
  count: number;
  overrideCount: number;
  summary: string;
  steps: ImsConfirmSteps;
  onStepsChange: (next: ImsConfirmSteps) => void;
  onCommit: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const [holding, setHolding] = useState(false);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);
  const committedRef = useRef(false);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  const stopHold = useCallback(() => {
    setHolding(false);
    startRef.current = null;
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (!committedRef.current) {
      onStepsChange({ ...stepsRef.current, holdProgressMs: 0 });
    }
  }, [onStepsChange]);

  const tick = useCallback(() => {
    if (startRef.current == null) return;
    const elapsed = performance.now() - startRef.current;
    const next = {
      ...stepsRef.current,
      holdProgressMs: Math.min(elapsed, IMS_HOLD_MS),
    };
    onStepsChange(next);
    stepsRef.current = next;
    if (elapsed >= IMS_HOLD_MS) {
      if (!committedRef.current) {
        committedRef.current = true;
        setHolding(false);
        onCommit();
      }
      return;
    }
    rafRef.current = requestAnimationFrame(tick);
  }, [onCommit, onStepsChange]);

  const beginHold = useCallback(() => {
    if (busy) return;
    if (!canStartImsHold(stepsRef.current, count)) return;
    committedRef.current = false;
    setHolding(true);
    startRef.current = performance.now();
    rafRef.current = requestAnimationFrame(tick);
  }, [busy, count, tick]);

  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const typedOk = typedCountMatchesExpected(steps.typedCount, count);
  const holdReady = canStartImsHold(steps, count);
  const progress = Math.min(1, steps.holdProgressMs / IMS_HOLD_MS);

  return (
    <div
      className="mt-5 rounded-none border border-[#3A3630] bg-[#0E0C0A] px-5 py-6 text-[#E8E4DC] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
      role="dialog"
      aria-label="Confirm IMS writeback"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#C4B59A]">
        Write to GSTN IMS — irreversible for these invoices
      </p>
      <p className="mt-2 text-[15px] font-semibold tracking-tight text-[#F5F0E8]">
        {summary}
      </p>
      <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-[#C8C0B4]">
        This calls the confirmed-action writeback client only after you finish
        all steps below. Release the hold button to cancel.
      </p>
      {overrideCount > 0 ? (
        <p className="mt-3 rounded-lg border border-amber-700/40 bg-amber-950/40 px-3 py-2 text-[12px] text-amber-100">
          {overrideCount} invoice{overrideCount === 1 ? "" : "s"} override
          ReconDesk&apos;s recommendation — logged as{" "}
          <span className="font-semibold">override</span>, not a straight
          confirm.
        </p>
      ) : (
        <p className="mt-3 text-[12px] text-[#A89F90]">
          Straight confirm of recommended {caActionLabel(action).toLowerCase()}{" "}
          — no overrides in this batch.
        </p>
      )}

      <div className="mt-6 space-y-6 border-t border-[#3A3630] pt-6">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#A89F90]">
            Step 1 of 3 — Review
          </p>
          <label className="mt-3 flex cursor-pointer items-start gap-3 text-[13px] text-[#E8E4DC]">
            <input
              type="checkbox"
              checked={steps.reviewed}
              disabled={busy}
              onChange={(e) =>
                onStepsChange({ ...steps, reviewed: e.target.checked })
              }
              className="mt-0.5 h-4 w-4 rounded border-[#5A564E] bg-[#1A1814] text-[#E8E4DC]"
            />
            <span>
              I reviewed the {count} invoice{count === 1 ? "" : "s"} and
              understand this writes {caActionLabel(action)} to the government
              portal.
            </span>
          </label>
        </div>

        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#A89F90]">
            Step 2 of 3 — Type the count
          </p>
          <p className="mt-2 text-[12px] text-[#A89F90]">
            Type <span className="font-mono text-[#E8E4DC]">{count}</span> to
            match &ldquo;{summary}&rdquo;.
          </p>
          <input
            type="text"
            inputMode="numeric"
            value={steps.typedCount}
            disabled={busy || !steps.reviewed}
            onChange={(e) =>
              onStepsChange({ ...steps, typedCount: e.target.value })
            }
            placeholder={String(count)}
            className="mt-2 w-full max-w-xs rounded-md border border-[#3A3630] bg-[#1A1814] px-3 py-2 font-mono text-[14px] text-[#F5F0E8] placeholder:text-[#5A564E] disabled:opacity-40"
          />
          {steps.typedCount && !typedOk ? (
            <p className="mt-1 text-[11px] text-red-300">Count does not match.</p>
          ) : null}
        </div>

        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#A89F90]">
            Step 3 of 3 — Hold to commit
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={!holdReady || busy}
              onMouseDown={beginHold}
              onMouseUp={stopHold}
              onMouseLeave={stopHold}
              onTouchStart={(e) => {
                e.preventDefault();
                beginHold();
              }}
              onTouchEnd={stopHold}
              className="relative overflow-hidden rounded-full bg-[#E8E4DC] px-5 py-2.5 text-[13px] font-semibold text-[#0E0C0A] disabled:opacity-40"
            >
              <span
                className="absolute inset-y-0 left-0 bg-[#C4B59A]/70"
                style={{ width: `${progress * 100}%` }}
                aria-hidden
              />
              <span className="relative">
                {busy
                  ? "Writing…"
                  : holding
                    ? "Keep holding…"
                    : `Hold to ${caActionLabel(action).toLowerCase()} ${count}`}
              </span>
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="rounded-full px-3 py-2 text-[12px] font-medium text-[#A89F90] hover:text-[#E8E4DC] disabled:opacity-40"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
