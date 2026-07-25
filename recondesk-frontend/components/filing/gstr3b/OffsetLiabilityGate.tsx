"use client";

import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  OffsetAllocationTable,
  LedgerVsPayablePanel,
} from "@/components/filing/gstr3b/OffsetAllocationTable";
import { OffsetDeliberateConfirm } from "@/components/filing/gstr3b/OffsetDeliberateConfirm";
import { OffsetStaleBanner } from "@/components/filing/gstr3b/OffsetStaleBanner";
import { PeriodLockedProof } from "@/components/filing/gstr3b/PeriodLockedProof";
import {
  EMPTY_OFFSET_CONFIRM_STEPS,
  type OffsetConfirmSteps,
  resetOffsetConfirmSteps,
  sumPdcashTaxOutflow,
  sumPditcItc,
} from "@/components/filing/gstr3b/offsetConfirmLogic";
import {
  gstr3bFilingApi,
  isApiError,
  parseGstr3bOffsetStale,
  parseGstr3bPeriodLocked,
  type Gstr3bOffsetPreviewResponse,
  type Gstr3bOffsetStaleDetail,
  type Gstr3bPeriodLockedDetail,
  type Gstr3bStatusResponse,
} from "@/lib/api";

const POLL_MS = 2_000;
const MAX_POLLS = 45;

export type Gstr3bRunState = {
  runId: string | null;
  referenceId: string | null;
  serverRunStatus: string | null;
  gstnStatusCd: string | null;
  errorMessage: string | null;
  actionError: string | null;
};

type Props = {
  token: string;
  period: string;
  clientGstinId: string;
  sessionId: string | null;
  runState: Gstr3bRunState;
  onRunState: (next: Gstr3bRunState) => void;
};

export function OffsetLiabilityGate({
  token,
  period,
  clientGstinId,
  sessionId,
  runState,
  onRunState,
}: Props) {
  const [preview, setPreview] = useState<Gstr3bOffsetPreviewResponse | null>(
    null
  );
  const [previewBusy, setPreviewBusy] = useState(false);
  const [confirmSteps, setConfirmSteps] = useState<OffsetConfirmSteps>(
    EMPTY_OFFSET_CONFIRM_STEPS
  );
  const [locked, setLocked] = useState<Gstr3bPeriodLockedDetail | null>(null);
  const [stale, setStale] = useState<Gstr3bOffsetStaleDetail | null>(null);
  const [offsetBusy, setOffsetBusy] = useState(false);
  const [pollNote, setPollNote] = useState<string | null>(null);

  const saved = runState.serverRunStatus === "saved";
  const offsetDone =
    runState.serverRunStatus === "offset_complete" ||
    runState.serverRunStatus === "evc_pending" ||
    runState.serverRunStatus === "filed";
  const offsetFailed = runState.serverRunStatus === "offset_failed";

  const loadPreview = useCallback(async () => {
    if (!sessionId) {
      onRunState({
        ...runState,
        actionError: "Active GSTN session required before Offset preview.",
      });
      return;
    }
    setPreviewBusy(true);
    setStale(null);
    setLocked(null);
    // Full deliberate sequence restart whenever preview refreshes.
    setConfirmSteps(resetOffsetConfirmSteps());
    try {
      const res = await gstr3bFilingApi.offsetPreview(token, period, {
        client_gstin_id: clientGstinId,
        session_id: sessionId,
      });
      setPreview(res);
      onRunState({ ...runState, actionError: null });
    } catch (err) {
      const periodLock = parseGstr3bPeriodLocked(err);
      if (periodLock) {
        setLocked(periodLock);
        setPreview(null);
        return;
      }
      onRunState({
        ...runState,
        actionError: isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Offset preview failed",
      });
    } finally {
      setPreviewBusy(false);
    }
  }, [clientGstinId, onRunState, period, runState, sessionId, token]);

  const runOffsetAndPoll = useCallback(async () => {
    if (!preview || !sessionId || !runState.runId) return;
    setOffsetBusy(true);
    setPollNote(null);
    setStale(null);
    setLocked(null);

    try {
      const res = await gstr3bFilingApi.offset(token, period, {
        client_gstin_id: clientGstinId,
        session_id: sessionId,
        run_id: runState.runId,
        pdcash: preview.pdcash,
        pditc: preview.pditc,
      });

      let state: Gstr3bRunState = {
        runId: res.run_id,
        referenceId: res.reference_id,
        serverRunStatus: res.status,
        gstnStatusCd: res.gstn_status_cd ?? null,
        errorMessage: null,
        actionError: null,
      };
      onRunState(state);
      setPollNote(
        "Offset accepted for processing — waiting for GSTN Return Status (inner P). Outer status_cd alone is never enough."
      );

      if (!res.reference_id) {
        setOffsetBusy(false);
        return;
      }

      for (let i = 0; i < MAX_POLLS; i++) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        let st: Gstr3bStatusResponse;
        try {
          st = await gstr3bFilingApi.status(token, period, {
            reference_id: res.reference_id,
            session_id: sessionId,
            run_id: res.run_id,
          });
        } catch (err) {
          onRunState({
            ...state,
            actionError: isApiError(err)
              ? err.detail
              : err instanceof Error
                ? err.message
                : "Status poll failed",
          });
          setPollNote(null);
          setOffsetBusy(false);
          return;
        }

        state = {
          runId: res.run_id,
          referenceId: res.reference_id,
          serverRunStatus: st.run_status ?? state.serverRunStatus,
          gstnStatusCd: st.gstn_status_cd,
          errorMessage: st.error_message,
          actionError: null,
        };
        onRunState(state);

        if (st.gstn_success || st.run_status === "offset_complete") {
          setPollNote("GSTN confirmed Offset (inner status_cd P). Period is now locked.");
          setOffsetBusy(false);
          setConfirmSteps(resetOffsetConfirmSteps());
          return;
        }
        if (st.gstn_failed || st.run_status === "offset_failed") {
          setPollNote(null);
          setOffsetBusy(false);
          setConfirmSteps(resetOffsetConfirmSteps());
          return;
        }
        setPollNote(
          `Waiting on GSTN Offset… status_cd=${st.gstn_status_cd ?? "—"} (poll ${i + 1}/${MAX_POLLS})`
        );
      }
      setPollNote(
        "Timed out waiting for GSTN Offset confirmation. Do not File until run status is offset_complete."
      );
    } catch (err) {
      const periodLock = parseGstr3bPeriodLocked(err);
      if (periodLock) {
        setLocked(periodLock);
        setConfirmSteps(resetOffsetConfirmSteps());
        setOffsetBusy(false);
        return;
      }
      const staleDetail = parseGstr3bOffsetStale(err);
      if (staleDetail) {
        setStale(staleDetail);
        // Critical: full reset of all three confirmation steps — not just disable.
        setConfirmSteps(resetOffsetConfirmSteps());
        setOffsetBusy(false);
        return;
      }
      onRunState({
        ...runState,
        actionError: isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Offset failed",
      });
    } finally {
      setOffsetBusy(false);
    }
  }, [
    clientGstinId,
    onRunState,
    period,
    preview,
    runState,
    sessionId,
    token,
  ]);

  const cashTotal = preview ? sumPdcashTaxOutflow(preview.pdcash) : 0;
  const itcTotal = preview ? sumPditcItc(preview.pditc) : 0;

  if (!saved && !offsetDone && !offsetFailed && runState.serverRunStatus !== "offset_pending") {
    return (
      <section
        className="rounded-none border border-[#2A2722] bg-[#0E0C0A] px-5 py-5 text-[#A89F90]"
        aria-label="Offset liability (locked until Save)"
      >
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em]">
          Offset liability
        </p>
        <p className="mt-2 text-[13px]">
          Available after GSTN confirms Save (inner status_cd P). This step
          moves real ledger money and cannot be undone for this period.
        </p>
      </section>
    );
  }

  return (
    <section
      className="rounded-none border border-[#3A3630] bg-[#0E0C0A] px-5 py-6 text-[#E8E4DC] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
      aria-label="Offset liability — irreversible"
    >
      <div className="border-b border-[#3A3630] pb-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#C4B59A]">
          Offset liability — irreversible for this GSTIN · period
        </p>
        <p className="mt-2 font-mono text-[12px] text-[#A89F90]">
          {period}
          {preview?.gstin ? ` · ${preview.gstin}` : ""}
          {runState.runId ? ` · run ${runState.runId.slice(0, 8)}…` : ""}
        </p>
        <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-[#C8C0B4]">
          After Offset succeeds, Save for this period is permanently blocked.
          Confirm the exact payload below — not a summary.
        </p>
      </div>

      {locked ? (
        <div className="mt-5">
          <PeriodLockedProof detail={locked} />
        </div>
      ) : null}

      {stale ? (
        <div className="mt-5">
          <OffsetStaleBanner
            detail={stale}
            busy={previewBusy}
            onRefreshPreview={() => {
              // Banner refresh also resets steps (loadPreview does too).
              setConfirmSteps(resetOffsetConfirmSteps());
              void loadPreview();
            }}
          />
        </div>
      ) : null}

      {offsetDone ? (
        <div className="mt-5 rounded border border-[#2A4A2A] bg-[#0E160E] px-4 py-3 text-[13px] text-[#B8D8B8]">
          Offset complete for this period. Proceed to EVC / File below. Save is
          locked.
          {runState.gstnStatusCd ? (
            <span className="mt-1 block font-mono text-[11px] text-[#8ABA8A]">
              gstn status_cd={runState.gstnStatusCd}
            </span>
          ) : null}
        </div>
      ) : null}

      {!locked && !offsetDone ? (
        <>
          <div className="mt-5">
            <button
              type="button"
              disabled={previewBusy || !sessionId || offsetBusy}
              onClick={() => void loadPreview()}
              className="inline-flex items-center gap-2 rounded border border-[#5A5040] bg-[#1A160F] px-4 py-2 text-[12px] font-semibold text-[#E8E4DC] hover:bg-[#221E16] disabled:opacity-40"
            >
              {previewBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              {preview ? "Refresh offset-preview" : "Load offset-preview"}
            </button>
          </div>

          {preview ? (
            <div className="mt-5 space-y-5">
              <LedgerVsPayablePanel
                details={preview.details}
                ledger={preview.ledger}
                cashTotal={cashTotal}
                itcTotal={itcTotal}
              />
              <OffsetAllocationTable
                pdcash={preview.pdcash}
                pditc={preview.pditc}
              />
              {!stale ? (
                <OffsetDeliberateConfirm
                  expectedCashTotal={cashTotal}
                  itcTotal={itcTotal}
                  periodLabel={period}
                  steps={confirmSteps}
                  onStepsChange={setConfirmSteps}
                  onCommit={() => void runOffsetAndPoll()}
                  disabled={!!stale || offsetBusy}
                  busy={offsetBusy}
                />
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      {pollNote ? (
        <p className="mt-4 text-[12px] text-[#A89F90]">{pollNote}</p>
      ) : null}

      {runState.errorMessage ? (
        <div className="mt-4 rounded border border-[#4A3030] bg-[#160E0E] px-3 py-3 text-[13px]">
          <p className="font-semibold text-[#E8A0A0]">GSTN Offset error</p>
          <p className="mt-1 whitespace-pre-wrap text-[#E0D0D0]">
            {runState.errorMessage}
          </p>
        </div>
      ) : null}

      {runState.actionError && !locked && !stale ? (
        <div className="mt-4 rounded border border-[#4A3030] bg-[#160E0E] px-3 py-3 text-[13px]">
          <p className="font-semibold text-[#E8A0A0]">Request rejected</p>
          <p className="mt-1 whitespace-pre-wrap text-[#E0D0D0]">
            {runState.actionError}
          </p>
        </div>
      ) : null}

      {offsetFailed ? (
        <p className="mt-4 text-[12px] text-[#E8A060]">
          Offset failed — gate remains open. Refresh preview and confirm again.
        </p>
      ) : null}
    </section>
  );
}
