"use client";

import { useCallback, useMemo, useState } from "react";
import { FileCheck, KeyRound, Loader2, Upload } from "lucide-react";

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
  gstin?: string;
  sessionId: string | null;
  runState: Gstr3bRunState;
  onRunState: (next: Gstr3bRunState) => void;
};

export function Gstr3bEvcAndFilePanel({
  token,
  period,
  gstin,
  sessionId,
  runState,
  onRunState,
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
  const [ack, setAck] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const offsetOk = isGstr3bOffsetComplete(runState.serverRunStatus);

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
      const res = await gstr3bFilingApi.file(token, period, {
        pan: panClean,
        signing_method: signingMethod,
        otp: signingMethod === "evc" ? otp.trim() : undefined,
        signature: signingMethod === "dsc" ? signature.trim() : undefined,
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
    signature,
    signingMethod,
    token,
  ]);

  return (
    <section className={sectionContainerClass} aria-label="Sign and File GSTR-3B">
      <SectionHeader title="Sign & File GSTR-3B" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        Only after Offset completes. Supports both EVC OTP and DSC (Digital Signature Certificate) options.
      </p>

      {isDscRecommended ? (
        <div className="mt-3 rounded-xl border border-amber-300/80 bg-amber-50/50 px-4 py-2.5 text-[12px] text-amber-950">
          <p className="font-semibold">CGST Rule 26 Notice</p>
          <p className="mt-0.5">
            This GSTIN belongs to a Company / LLP. CGST Rule 26 legally mandates <strong>DSC (Digital Signature)</strong> filing for corporate taxpayers.
          </p>
        </div>
      ) : null}

      {!offsetOk ? (
        <p className="mt-3 text-[12px] text-gray-500">
          Locked until run status is offset_complete (or later).
        </p>
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

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block sm:col-span-2">
          <span className="text-[12px] font-medium text-gray-500">
            Authorised Signatory PAN
          </span>
          <input
            value={pan}
            onChange={(e) => setPan(e.target.value.toUpperCase())}
            maxLength={10}
            placeholder="10-character PAN (e.g. ABCDE1234F)"
            className="mt-1.5 h-10 w-full max-w-sm rounded-full border-0 bg-[#F5F5F6] px-4 font-mono text-[13px] outline-none focus:ring-2 focus:ring-black/10"
          />
        </label>

        {signingMethod === "evc" ? (
          <div className="sm:col-span-2">
            <label className="block max-w-sm">
              <span className="text-[12px] font-medium text-gray-500">EVC OTP</span>
              <input
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                placeholder="6-digit OTP sent to registered mobile/email"
                className="mt-1.5 h-10 w-full rounded-full border-0 bg-[#F5F5F6] px-4 font-mono text-[13px] outline-none focus:ring-2 focus:ring-black/10"
              />
            </label>
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
                File GSTR-3B with EVC
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
                disabled={fileBusy || !offsetOk || !signature.trim()}
                onClick={() => void fileReturn()}
                className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white disabled:opacity-40"
              >
                {fileBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                File GSTR-3B with DSC
              </button>
            </div>
          </div>
        )}
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

