"use client";

import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";

import type { Gstr3bRunState } from "@/components/filing/gstr3b/OffsetLiabilityGate";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { gstr3bFilingApi, isApiError } from "@/lib/api";
import { isGstr3bOffsetComplete } from "@/components/filing/filingHelpers";

type Props = {
  token: string;
  period: string;
  sessionId: string | null;
  runState: Gstr3bRunState;
  onRunState: (next: Gstr3bRunState) => void;
};

export function Gstr3bEvcAndFilePanel({
  token,
  period,
  sessionId,
  runState,
  onRunState,
}: Props) {
  const [pan, setPan] = useState("");
  const [otp, setOtp] = useState("");
  const [evcBusy, setEvcBusy] = useState(false);
  const [fileBusy, setFileBusy] = useState(false);
  const [evcNote, setEvcNote] = useState<string | null>(null);
  const [ack, setAck] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const offsetOk = isGstr3bOffsetComplete(runState.serverRunStatus);

  const requestEvc = useCallback(async () => {
    setActionError(null);
    setEvcNote(null);
    if (!offsetOk) {
      setActionError(
        "EVC stays locked until Offset completes (run status offset_complete)."
      );
      return;
    }
    if (!sessionId) {
      setActionError("Active GSTN session required.");
      return;
    }
    const panClean = pan.trim().toUpperCase();
    if (panClean.length !== 10) {
      setActionError("Enter the 10-character PAN of the authorised signatory.");
      return;
    }
    setEvcBusy(true);
    try {
      await gstr3bFilingApi.evcOtp(token, period, {
        pan: panClean,
        session_id: sessionId,
        run_id: runState.runId,
      });
      onRunState({ ...runState, serverRunStatus: "evc_pending" });
      setEvcNote("EVC OTP sent to authorised signatory.");
    } catch (err) {
      setActionError(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "EVC OTP failed"
      );
    } finally {
      setEvcBusy(false);
    }
  }, [offsetOk, onRunState, pan, period, runState, sessionId, token]);

  const fileReturn = useCallback(async () => {
    setActionError(null);
    setAck(null);
    if (!offsetOk && runState.serverRunStatus !== "evc_pending") {
      setActionError("File is blocked until Offset is complete.");
      return;
    }
    if (!sessionId) {
      setActionError("Active GSTN session required.");
      return;
    }
    const panClean = pan.trim().toUpperCase();
    const otpClean = otp.trim();
    if (panClean.length !== 10 || !otpClean) {
      setActionError("PAN and EVC OTP are required.");
      return;
    }
    setFileBusy(true);
    try {
      const res = await gstr3bFilingApi.file(token, period, {
        pan: panClean,
        otp: otpClean,
        session_id: sessionId,
        run_id: runState.runId,
      });
      onRunState({ ...runState, serverRunStatus: "filed" });
      setAck(res.ack_number);
    } catch (err) {
      setActionError(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "File failed"
      );
    } finally {
      setFileBusy(false);
    }
  }, [
    offsetOk,
    onRunState,
    otp,
    pan,
    period,
    runState,
    sessionId,
    token,
  ]);

  return (
    <section className={sectionContainerClass} aria-label="EVC and File GSTR-3B">
      <SectionHeader title="EVC OTP & File" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        Only after Offset completes. File body uses post-Offset Get Details
        (including tx_pmt) on the server when omitted.
      </p>

      {!offsetOk ? (
        <p className="mt-3 text-[12px] text-gray-500">
          Locked until run status is offset_complete (or later).
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-[12px] font-medium text-gray-500">PAN</span>
          <input
            value={pan}
            onChange={(e) => setPan(e.target.value.toUpperCase())}
            maxLength={10}
            className="mt-1.5 h-10 w-full rounded-full border-0 bg-[#F5F5F6] px-4 font-mono text-[13px] outline-none focus:ring-2 focus:ring-black/10"
          />
        </label>
        <label className="block">
          <span className="text-[12px] font-medium text-gray-500">EVC OTP</span>
          <input
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            className="mt-1.5 h-10 w-full rounded-full border-0 bg-[#F5F5F6] px-4 font-mono text-[13px] outline-none focus:ring-2 focus:ring-black/10"
          />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          disabled={evcBusy || !offsetOk}
          onClick={() => void requestEvc()}
          className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white disabled:opacity-40"
        >
          {evcBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Send EVC OTP
        </button>
        <button
          type="button"
          disabled={fileBusy || !offsetOk}
          onClick={() => void fileReturn()}
          className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-5 py-2.5 text-[13px] font-semibold text-[var(--ink)] disabled:opacity-40"
        >
          {fileBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          File GSTR-3B
        </button>
      </div>

      {evcNote ? (
        <p className="mt-3 text-[12px] text-gray-500">{evcNote}</p>
      ) : null}
      {ack ? (
        <p className="mt-3 font-mono text-[12px] text-[var(--ink)]">
          Filed · ack_num={ack}
        </p>
      ) : null}
      {actionError ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] ring-1 ring-[#E8E8EA]">
          {actionError}
        </div>
      ) : null}
    </section>
  );
}
