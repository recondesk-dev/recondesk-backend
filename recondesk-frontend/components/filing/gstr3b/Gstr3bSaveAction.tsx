"use client";

import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";

import type { Gstr3bRunState } from "@/components/filing/gstr3b/OffsetLiabilityGate";
import { figuresToSaveBody, type Gstr3bFiguresState } from "@/components/filing/gstr3b/figuresModel";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import {
  gstr3bFilingApi,
  isApiError,
  parseGstr3bPeriodLocked,
  type Gstr3bPeriodLockedDetail,
  type Gstr3bStatusResponse,
} from "@/lib/api";
import { PeriodLockedProof } from "@/components/filing/gstr3b/PeriodLockedProof";
import { isGstr3bSaveConfirmed, isGstr3bSaveFailed } from "@/components/filing/filingHelpers";

const POLL_MS = 2_000;
const MAX_POLLS = 45;

type Props = {
  token: string;
  period: string;
  clientGstinId: string;
  sessionId: string | null;
  figures: Gstr3bFiguresState;
  runState: Gstr3bRunState;
  onRunState: (next: Gstr3bRunState) => void;
};

export function Gstr3bSaveAction({
  token,
  period,
  clientGstinId,
  sessionId,
  figures,
  runState,
  onRunState,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [pollNote, setPollNote] = useState<string | null>(null);
  const [locked, setLocked] = useState<Gstr3bPeriodLockedDetail | null>(null);

  const runSaveAndPoll = useCallback(async () => {
    if (!sessionId) {
      onRunState({
        ...runState,
        actionError: "Complete GSTN OTP login before Save.",
      });
      return;
    }
    setBusy(true);
    setPollNote(null);
    setLocked(null);
    onRunState({
      runId: null,
      referenceId: null,
      serverRunStatus: null,
      gstnStatusCd: null,
      errorMessage: null,
      actionError: null,
    });

    const save_body = figuresToSaveBody(figures);
    let saveRes;
    try {
      saveRes = await gstr3bFilingApi.save(token, period, {
        client_gstin_id: clientGstinId,
        period,
        session_id: sessionId,
        save_body,
      });
    } catch (err) {
      const periodLock = parseGstr3bPeriodLocked(err);
      if (periodLock) {
        setLocked(periodLock);
        setBusy(false);
        return;
      }
      onRunState({
        runId: null,
        referenceId: null,
        serverRunStatus: null,
        gstnStatusCd: null,
        errorMessage: null,
        actionError: isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Save failed",
      });
      setBusy(false);
      return;
    }

    let state: Gstr3bRunState = {
      runId: saveRes.run_id,
      referenceId: saveRes.reference_id,
      serverRunStatus: saveRes.status,
      gstnStatusCd: saveRes.gstn_status_cd ?? null,
      errorMessage: null,
      actionError: null,
    };
    onRunState(state);
    setPollNote(
      "Save accepted by Sandbox — waiting for GSTN Return Status (inner P)…"
    );

    if (!saveRes.reference_id) {
      setBusy(false);
      return;
    }

    for (let i = 0; i < MAX_POLLS; i++) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      let st: Gstr3bStatusResponse;
      try {
        st = await gstr3bFilingApi.status(token, period, {
          reference_id: saveRes.reference_id,
          session_id: sessionId,
          run_id: saveRes.run_id,
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
        setBusy(false);
        return;
      }

      state = {
        runId: saveRes.run_id,
        referenceId: saveRes.reference_id,
        serverRunStatus: st.run_status ?? state.serverRunStatus,
        gstnStatusCd: st.gstn_status_cd,
        errorMessage: st.error_message,
        actionError: null,
      };
      onRunState(state);

      if (st.gstn_success || st.run_status === "saved") {
        setPollNote("GSTN confirmed Save (inner status_cd P).");
        setBusy(false);
        return;
      }
      if (st.gstn_failed || isGstr3bSaveFailed(st.run_status)) {
        setPollNote(null);
        setBusy(false);
        return;
      }
      setPollNote(
        `Waiting on GSTN… status_cd=${st.gstn_status_cd ?? "—"} (poll ${i + 1}/${MAX_POLLS})`
      );
    }

    setPollNote(
      "Timed out waiting for GSTN Save confirmation. Do not Offset until status is saved."
    );
    setBusy(false);
  }, [
    clientGstinId,
    figures,
    onRunState,
    period,
    runState,
    sessionId,
    token,
  ]);

  const confirmed = isGstr3bSaveConfirmed(runState.serverRunStatus);
  const failed = isGstr3bSaveFailed(runState.serverRunStatus);

  return (
    <section className={sectionContainerClass} aria-label="Save GSTR-3B">
      <SectionHeader title="Save to GSTN" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        Posts the figures you confirmed above. Success means Return Status
        inner <span className="font-medium text-[var(--ink)]">status_cd P</span>{" "}
        — not Sandbox outer acceptance alone.
      </p>

      {locked ? (
        <div className="mt-4">
          <PeriodLockedProof detail={locked} />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || !sessionId || !!locked}
          onClick={() => void runSaveAndPoll()}
          className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {busy ? "Saving…" : "Save GSTR-3B"}
        </button>
        <span className="inline-flex items-center rounded-full bg-[#F5F5F6] px-3 py-1 text-[12px] font-semibold text-[var(--ink)]">
          {confirmed
            ? "GSTN Save confirmed"
            : failed
              ? "Save failed"
              : runState.serverRunStatus || "Not saved"}
        </span>
      </div>

      {pollNote ? (
        <p className="mt-3 text-[12px] text-gray-500">{pollNote}</p>
      ) : null}
      {runState.errorMessage ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] ring-1 ring-[#E8E8EA]">
          <p className="font-semibold">GSTN Save error</p>
          <p className="mt-1 whitespace-pre-wrap">{runState.errorMessage}</p>
        </div>
      ) : null}
      {runState.actionError ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] ring-1 ring-[#E8E8EA]">
          <p className="font-semibold">Request rejected</p>
          <p className="mt-1 whitespace-pre-wrap">{runState.actionError}</p>
        </div>
      ) : null}
      {runState.runId ? (
        <p className="mt-3 font-mono text-[11px] text-gray-400">
          run_id={runState.runId}
          {runState.referenceId ? ` · ref=${runState.referenceId}` : null}
        </p>
      ) : null}
    </section>
  );
}
