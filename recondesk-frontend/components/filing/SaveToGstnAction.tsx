"use client";

import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  filingApi,
  isApiError,
  type FilingSaveResponse,
  type FilingStatusResponse,
} from "@/lib/api";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import {
  isGstnSaveConfirmed,
  isSaveTerminalFailure,
} from "@/components/filing/filingHelpers";

const POLL_MS = 2_000;
const MAX_POLLS = 45;

export type SaveServerState = {
  runId: string | null;
  referenceId: string | null;
  /** Last run_status (or save response status) returned by the backend. */
  serverRunStatus: string | null;
  gstnStatusCd: string | null;
  errorMessage: string | null;
  /** 409 / other API rejection detail from the last action. */
  actionError: string | null;
};

type Props = {
  token: string;
  period: string;
  clientGstinId: string;
  srFile: File | null;
  sessionId: string | null;
  canSaveHint: boolean;
  serverState: SaveServerState;
  onServerState: (next: SaveServerState) => void;
  patches?: Array<Record<string, unknown>>;
};

export function SaveToGstnAction({
  token,
  period,
  clientGstinId,
  srFile,
  sessionId,
  canSaveHint,
  serverState,
  onServerState,
  patches,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [pollNote, setPollNote] = useState<string | null>(null);

  const patch = useCallback(
    (partial: Partial<SaveServerState>) => {
      onServerState({ ...serverState, ...partial });
    },
    [onServerState, serverState]
  );

  const runSaveAndPoll = useCallback(async () => {
    if (!srFile) {
      patch({ actionError: "Upload a Sales Register before Save." });
      return;
    }
    if (!sessionId) {
      patch({
        actionError:
          "Complete GSTN OTP login first — Save needs an active filing session.",
      });
      return;
    }

    setBusy(true);
    setPollNote(null);
    // Clear prior success assumptions — only fresh backend replies count.
    onServerState({
      runId: null,
      referenceId: null,
      serverRunStatus: null,
      gstnStatusCd: null,
      errorMessage: null,
      actionError: null,
    });

    let saveRes: FilingSaveResponse;
    try {
      saveRes = await filingApi.saveUpload(token, period, {
        client_gstin_id: clientGstinId,
        sales_register_file: srFile,
        session_id: sessionId,
        patches,
      });
    } catch (err) {
      const detail = isApiError(err)
        ? err.detail
        : err instanceof Error
          ? err.message
          : "Save failed";
      onServerState({
        runId: null,
        referenceId: null,
        serverRunStatus: null,
        gstnStatusCd: null,
        errorMessage: null,
        actionError: detail,
      });
      setBusy(false);
      return;
    }

    // Trust Save response only (outer accept → save_pending).
    let state: SaveServerState = {
      runId: saveRes.run_id,
      referenceId: saveRes.reference_id,
      serverRunStatus: saveRes.status,
      gstnStatusCd: null,
      errorMessage: null,
      actionError: null,
    };
    onServerState(state);

    if (saveRes.status !== "save_pending" && saveRes.status !== "saved") {
      // Unexpected — surface whatever the backend said; do not invent success.
      setPollNote(`Save returned status “${saveRes.status}”. Polling Return Status…`);
    } else {
      setPollNote("Save accepted by Sandbox — waiting for GSTN Return Status (inner P)…");
    }

    for (let i = 0; i < MAX_POLLS; i++) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      let st: FilingStatusResponse;
      try {
        st = await filingApi.status(token, period, {
          reference_id: saveRes.reference_id,
          session_id: sessionId,
          run_id: saveRes.run_id,
        });
      } catch (err) {
        const detail = isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Status poll failed";
        // Keep last known Save ids; show poll error — do not claim saved.
        onServerState({
          ...state,
          actionError: detail,
        });
        setPollNote(null);
        setBusy(false);
        return;
      }

      // Update exclusively from this poll response.
      state = {
        runId: saveRes.run_id,
        referenceId: saveRes.reference_id,
        serverRunStatus: st.run_status ?? state.serverRunStatus,
        gstnStatusCd: st.gstn_status_cd,
        errorMessage: st.error_message,
        actionError: null,
      };
      onServerState(state);

      if (st.gstn_success || st.run_status === "saved") {
        setPollNote("GSTN confirmed Save (inner status_cd P).");
        setBusy(false);
        return;
      }
      if (st.gstn_failed || isSaveTerminalFailure(st.run_status)) {
        setPollNote(null);
        setBusy(false);
        return;
      }
      setPollNote(
        `Waiting on GSTN… status_cd=${st.gstn_status_cd ?? "—"} (poll ${i + 1}/${MAX_POLLS})`
      );
    }

    setPollNote(
      "Timed out waiting for GSTN Save confirmation. Use the status on the run — do not File until status is saved."
    );
    setBusy(false);
  }, [
    clientGstinId,
    onServerState,
    patch,
    period,
    sessionId,
    srFile,
    token,
  ]);

  const confirmed = isGstnSaveConfirmed(serverState.serverRunStatus);
  const failed = isSaveTerminalFailure(serverState.serverRunStatus);

  return (
    <section className={sectionContainerClass} aria-label="Save to GSTN">
      <SectionHeader title="Save to GSTN" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        Save maps your Sales Register through the filing orchestrator and posts
        to GSTN. Success means the Return Status poll returns inner{" "}
        <span className="font-medium text-[var(--ink)]">status_cd P</span> —
        not Sandbox’s outer acceptance alone.
      </p>

      {!canSaveHint ? (
        <p className="mt-3 text-[12px] text-gray-500">
          Readiness currently reports Save may be blocked — you can still attempt
          Save; the backend response is authoritative.
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || !srFile || !sessionId}
          onClick={() => void runSaveAndPoll()}
          className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {busy ? "Saving…" : "Save to GSTN"}
        </button>
        <ServerStatusBadge
          serverRunStatus={serverState.serverRunStatus}
          gstnStatusCd={serverState.gstnStatusCd}
          confirmed={confirmed}
          failed={failed}
        />
      </div>

      {pollNote ? (
        <p className="mt-3 text-[12px] text-gray-500">{pollNote}</p>
      ) : null}

      {serverState.errorMessage ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)] ring-1 ring-[#E8E8EA]">
          <p className="font-semibold">GSTN Save error</p>
          <p className="mt-1 whitespace-pre-wrap">{serverState.errorMessage}</p>
        </div>
      ) : null}

      {serverState.actionError ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)] ring-1 ring-[#E8E8EA]">
          <p className="font-semibold">Request rejected</p>
          <p className="mt-1 whitespace-pre-wrap">{serverState.actionError}</p>
        </div>
      ) : null}

      {serverState.runId ? (
        <p className="mt-3 font-mono text-[11px] text-gray-400">
          run_id={serverState.runId}
          {serverState.referenceId
            ? ` · ref=${serverState.referenceId}`
            : null}
        </p>
      ) : null}
    </section>
  );
}

function ServerStatusBadge({
  serverRunStatus,
  gstnStatusCd,
  confirmed,
  failed,
}: {
  serverRunStatus: string | null;
  gstnStatusCd: string | null;
  confirmed: boolean;
  failed: boolean;
}) {
  if (!serverRunStatus && !gstnStatusCd) {
    return (
      <span className="text-[12px] text-gray-400">Not saved this session</span>
    );
  }
  const label = confirmed
    ? "GSTN Save confirmed"
    : failed
      ? "Save failed"
      : serverRunStatus || "…";
  return (
    <span className="inline-flex flex-col gap-0.5">
      <span className="inline-flex items-center rounded-full bg-[#F5F5F6] px-3 py-1 text-[12px] font-semibold text-[var(--ink)]">
        {label}
      </span>
      {gstnStatusCd ? (
        <span className="pl-1 font-mono text-[11px] text-gray-400">
          gstn status_cd={gstnStatusCd}
        </span>
      ) : null}
    </span>
  );
}
