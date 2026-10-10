"use client";

import { useCallback, useState } from "react";
import { FileCheck, KeyRound, Loader2, Upload } from "lucide-react";

import { filingApi, isApiError } from "@/lib/api";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { isGstnSaveConfirmed } from "@/components/filing/filingHelpers";
import type { SaveServerState } from "@/components/filing/SaveToGstnAction";

type Props = {
  token: string;
  period: string;
  gstin?: string;
  sessionId: string | null;
  /** Latest Save/status lifecycle from the backend — not readiness. */
  saveState: SaveServerState;
  onSaveState: (next: SaveServerState) => void;
};

export function EvcAndFilePanel({
  token,
  period,
  gstin,
  sessionId,
  saveState,
  onSaveState,
}: Props) {
  // Detect company / LLP from GSTIN 6th character (4th char of PAN)
  // C = Company (Pvt Ltd / Public Ltd), F = Firm / LLP
  const panChar4 = (gstin || "").trim().toUpperCase()[5] || "";
  const isDscRecommended = panChar4 === "C" || panChar4 === "F";

  const [signingMethod, setSigningMethod] = useState<"evc" | "dsc">(
    isDscRecommended ? "dsc" : "evc"
  );
  const [pan, setPan] = useState("");
  const [otp, setOtp] = useState("");
  const [signature, setSignature] = useState("");
  const [sigFileName, setSigFileName] = useState<string | null>(null);

  const [evcBusy, setEvcBusy] = useState(false);
  const [fileBusy, setFileBusy] = useState(false);
  const [evcNote, setEvcNote] = useState<string | null>(null);
  const [fileResult, setFileResult] = useState<{
    status: string;
    ack_number: string | null;
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Gate on the last backend Save/status response only.
  const saveOk = isGstnSaveConfirmed(saveState.serverRunStatus);

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSigFileName(file.name);
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result;
      if (typeof content === "string") {
        setSignature(content.trim());
      }
    };
    reader.readAsText(file);
  }, []);

  const requestEvc = useCallback(async () => {
    setActionError(null);
    setEvcNote(null);
    if (!saveOk) {
      setActionError(
        "File / EVC stay locked until a GSTN-confirmed Save (backend run status “saved”)."
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
      await filingApi.evcOtp(token, period, {
        pan: panClean,
        session_id: sessionId,
        run_id: saveState.runId,
      });
      // HTTP 200 from EVC is the gate; keep prior Save status (still unlocks File).
      // Do not invent run_status — a 409 would have thrown above.
      setEvcNote("EVC OTP sent to authorised signatory.");
    } catch (err) {
      const detail = isApiError(err)
        ? err.detail
        : err instanceof Error
          ? err.message
          : "EVC OTP failed";
      setActionError(detail);
      // Do not change saveState on failure / 409 gate rejection.
    } finally {
      setEvcBusy(false);
    }
  }, [pan, period, saveOk, saveState.runId, sessionId, token]);

  const fileReturn = useCallback(async () => {
    setActionError(null);
    setFileResult(null);
    if (!saveOk) {
      setActionError(
        "File is blocked until the backend reports a GSTN-confirmed Save."
      );
      return;
    }
    if (!sessionId) {
      setActionError("Active GSTN session required.");
      return;
    }
    const panClean = pan.trim().toUpperCase();
    if (panClean.length !== 10) {
      setActionError("10-character PAN of authorised signatory is required.");
      return;
    }

    if (signingMethod === "evc") {
      const otpClean = otp.trim();
      if (!otpClean) {
        setActionError("EVC OTP is required for EVC filing.");
        return;
      }
    } else {
      const sigClean = signature.trim();
      if (!sigClean) {
        setActionError("PKCS7 Digital Signature (DSC) payload is required.");
        return;
      }
    }

    setFileBusy(true);
    try {
      const res = await filingApi.file(token, period, {
        pan: panClean,
        signing_method: signingMethod,
        otp: signingMethod === "evc" ? otp.trim() : undefined,
        signature: signingMethod === "dsc" ? signature.trim() : undefined,
        session_id: sessionId,
        run_id: saveState.runId,
      });
      // Trust File response only.
      if (res.status === "filed") {
        setFileResult({
          status: res.status,
          ack_number: res.ack_number,
        });
        onSaveState({
          ...saveState,
          serverRunStatus: "filed",
          gstnStatusCd: res.gstn_status_cd ?? saveState.gstnStatusCd,
          actionError: null,
          errorMessage: null,
        });
      } else {
        setActionError(
          `File response status was “${res.status}” — not treating as filed.`
        );
      }
    } catch (err) {
      const detail = isApiError(err)
        ? err.detail
        : err instanceof Error
          ? err.message
          : "File failed";
      setActionError(detail);
      // Leave prior saveState untouched on 409 / GSTN failure — no silent retry.
    } finally {
      setFileBusy(false);
    }
  }, [onSaveState, otp, pan, period, saveOk, saveState, sessionId, signature, signingMethod, token]);

  return (
    <section className={sectionContainerClass} aria-label="Sign and File GSTR-1">
      <SectionHeader title="Sign & File GSTR-1" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        Filing stays locked until Save’s status poll reports a genuine GSTN-confirmed Save. Supports both EVC OTP and DSC (Digital Signature Certificate) options.
      </p>

      {isDscRecommended ? (
        <div className="mt-3 rounded-xl border border-amber-300/80 bg-amber-50/50 px-4 py-2.5 text-[12px] text-amber-950">
          <p className="font-semibold">CGST Rule 26 Notice</p>
          <p className="mt-0.5">
            This GSTIN belongs to a Company / LLP. CGST Rule 26 legally mandates <strong>DSC (Digital Signature)</strong> filing for corporate taxpayers.
          </p>
        </div>
      ) : null}

      {!saveOk ? (
        <div className="mt-4 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-gray-600">
          Waiting for backend Save confirmation
          {saveState.serverRunStatus
            ? ` (current run status: ${saveState.serverRunStatus})`
            : ""}
          . Complete Save to GSTN above first.
        </div>
      ) : null}

      {/* Signing Method Selector */}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            setSigningMethod("evc");
            setActionError(null);
          }}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[12px] font-semibold transition ${
            signingMethod === "evc"
              ? "bg-[var(--ink)] text-white shadow-sm"
              : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/70"
          }`}
        >
          <KeyRound className="h-3.5 w-3.5" />
          File via EVC OTP
        </button>
        <button
          type="button"
          onClick={() => {
            setSigningMethod("dsc");
            setActionError(null);
          }}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[12px] font-semibold transition ${
            signingMethod === "dsc"
              ? "bg-[var(--ink)] text-white shadow-sm"
              : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/70"
          }`}
        >
          <FileCheck className="h-3.5 w-3.5" />
          File via DSC (Digital Signature)
        </button>
      </div>

      <div
        className={`mt-4 grid gap-3 sm:grid-cols-2 ${
          saveOk ? "" : "pointer-events-none opacity-40"
        }`}
      >
        <label className="block sm:col-span-2">
          <span className="text-[12px] font-medium text-gray-500">
            Authorised signatory PAN
          </span>
          <input
            value={pan}
            onChange={(e) => setPan(e.target.value.toUpperCase())}
            maxLength={10}
            disabled={!saveOk}
            className="mt-1.5 h-10 w-full max-w-sm rounded-full border-0 bg-[#F5F5F6] px-4 font-mono text-[13px] text-[var(--ink)] outline-none focus:ring-2 focus:ring-black/10"
            placeholder="ABCDE1234F"
            autoComplete="off"
          />
        </label>

        {signingMethod === "evc" ? (
          <div className="sm:col-span-2">
            <label className="block max-w-sm">
              <span className="text-[12px] font-medium text-gray-500">EVC OTP</span>
              <input
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                disabled={!saveOk}
                className="mt-1.5 h-10 w-full rounded-full border-0 bg-[#F5F5F6] px-4 font-mono text-[13px] text-[var(--ink)] outline-none focus:ring-2 focus:ring-black/10"
                placeholder="6-digit OTP from SMS / email"
                autoComplete="one-time-code"
              />
            </label>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={!saveOk || evcBusy || fileBusy}
                onClick={() => void requestEvc()}
                className="inline-flex items-center gap-2 rounded-full bg-[#F5F5F6] px-5 py-2.5 text-[13px] font-semibold text-gray-700 transition-colors hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {evcBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Send EVC OTP
              </button>
              <button
                type="button"
                disabled={!saveOk || fileBusy || evcBusy || !otp.trim()}
                onClick={() => void fileReturn()}
                className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {fileBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                File GSTR-1 with EVC
              </button>
            </div>
          </div>
        ) : (
          <div className="sm:col-span-2 space-y-3">
            <label className="block">
              <span className="text-[12px] font-medium text-gray-500">
                PKCS7 Digital Signature (Base64)
              </span>
              <textarea
                value={signature}
                onChange={(e) => {
                  setSignature(e.target.value);
                  setSigFileName(null);
                }}
                disabled={!saveOk}
                rows={3}
                placeholder="Paste PKCS7 detached signature (Base64 string) generated from USB Token / emSigner"
                className="mt-1.5 w-full rounded-2xl border-0 bg-[#F5F5F6] p-3 font-mono text-[12px] outline-none focus:ring-2 focus:ring-black/10"
              />
            </label>

            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-gray-200 bg-white px-4 py-2 text-[12px] font-semibold text-[var(--ink)] hover:bg-gray-50">
                <Upload className="h-3.5 w-3.5" />
                Upload Signature (.sig / .p7s / .txt)
                <input
                  type="file"
                  accept=".sig,.p7s,.txt,.json"
                  onChange={handleFileUpload}
                  disabled={!saveOk}
                  className="hidden"
                />
              </label>
              {sigFileName ? (
                <span className="text-[12px] font-mono text-gray-500">
                  Loaded: {sigFileName}
                </span>
              ) : null}
            </div>

            <p className="text-[11px] text-gray-400">
              Generate the signature using your local emSigner / USB Token utility for the return digest, then paste or upload the signature above.
            </p>

            <div className="pt-2">
              <button
                type="button"
                disabled={!saveOk || fileBusy || !signature.trim()}
                onClick={() => void fileReturn()}
                className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {fileBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                File GSTR-1 with DSC
              </button>
            </div>
          </div>
        )}
      </div>

      {evcNote ? (
        <p className="mt-3 text-[12px] text-gray-500">{evcNote}</p>
      ) : null}

      {fileResult?.status === "filed" ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)]">
          <p className="font-semibold">Filed (backend confirmed)</p>
          <p className="mt-1 font-mono text-[12px] text-gray-600">
            ack: {fileResult.ack_number || "—"}
          </p>
        </div>
      ) : null}

      {actionError ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)] ring-1 ring-[#E8E8EA]">
          <p className="font-semibold">Request rejected</p>
          <p className="mt-1 whitespace-pre-wrap">{actionError}</p>
          <p className="mt-2 text-[12px] text-gray-500">
            No automatic retry — fix the session / Save state and try again.
          </p>
        </div>
      ) : null}
    </section>
  );
}
