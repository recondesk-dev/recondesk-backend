"use client";

import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";

import { filingApi, isApiError } from "@/lib/api";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";

type Props = {
  token: string;
  gstin: string;
  clientGstinId: string;
  sessionId: string | null;
  onSessionId: (id: string | null) => void;
};

export function GstnSessionPanel({
  token,
  gstin,
  clientGstinId,
  sessionId,
  onSessionId,
}: Props) {
  const [username, setUsername] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [busy, setBusy] = useState<"generate" | "verify" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const generate = useCallback(async () => {
    setError(null);
    setNote(null);
    if (!gstin || !username.trim()) {
      setError("GSTIN and GST portal username are required.");
      return;
    }
    setBusy("generate");
    try {
      await filingApi.generateOtp(token, {
        gstin,
        username: username.trim(),
        client_gstin_id: clientGstinId,
      });
      setOtpSent(true);
      setNote("OTP sent to the registered mobile / email for this username.");
    } catch (err) {
      setError(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "OTP generate failed"
      );
    } finally {
      setBusy(null);
    }
  }, [clientGstinId, gstin, token, username]);

  const verify = useCallback(async () => {
    setError(null);
    setNote(null);
    if (!otp.trim()) {
      setError("Enter the OTP.");
      return;
    }
    setBusy("verify");
    try {
      const res = await filingApi.verifyOtp(token, {
        gstin,
        username: username.trim(),
        otp: otp.trim(),
        client_gstin_id: clientGstinId,
      });
      onSessionId(res.session_id);
      setNote(
        `Session active until ${
          res.token_expires_at
            ? new Date(res.token_expires_at).toLocaleString("en-IN")
            : "expiry"
        }.`
      );
    } catch (err) {
      onSessionId(null);
      setError(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "OTP verify failed"
      );
    } finally {
      setBusy(null);
    }
  }, [clientGstinId, gstin, onSessionId, otp, token, username]);

  return (
    <section className={sectionContainerClass} aria-label="GSTN session">
      <SectionHeader title="GSTN login (OTP)" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        Taxpayer session for this GSTIN. Required before Save / File.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block sm:col-span-2">
          <span className="text-[12px] font-medium text-gray-500">GSTIN</span>
          <input
            value={gstin}
            readOnly
            className="mt-1.5 h-10 w-full rounded-full border-0 bg-[#F5F5F6] px-4 font-mono text-[13px] font-medium text-gray-600 outline-none"
          />
        </label>
        <label className="block">
          <span className="text-[12px] font-medium text-gray-500">
            GST portal username
          </span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1.5 h-10 w-full rounded-full border-0 bg-[#F5F5F6] px-4 text-[13px] font-medium text-[var(--ink)] outline-none focus:ring-2 focus:ring-black/10"
            placeholder="e.g. recondesk_gst"
            autoComplete="username"
          />
        </label>
        <label className="block">
          <span className="text-[12px] font-medium text-gray-500">OTP</span>
          <input
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            disabled={!otpSent && !sessionId}
            className="mt-1.5 h-10 w-full rounded-full border-0 bg-[#F5F5F6] px-4 text-[13px] font-medium text-[var(--ink)] outline-none focus:ring-2 focus:ring-black/10 disabled:opacity-50"
            placeholder="6-digit OTP"
            autoComplete="one-time-code"
          />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy != null}
          onClick={() => void generate()}
          className="inline-flex items-center gap-2 rounded-full bg-[#F5F5F6] px-5 py-2.5 text-[13px] font-semibold text-gray-700 hover:bg-gray-200/70 disabled:opacity-40"
        >
          {busy === "generate" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : null}
          Send OTP
        </button>
        <button
          type="button"
          disabled={busy != null || (!otpSent && !sessionId)}
          onClick={() => void verify()}
          className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy === "verify" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : null}
          Verify &amp; start session
        </button>
        {sessionId ? (
          <span className="inline-flex items-center rounded-full bg-[#F5F5F6] px-3 py-1 text-[12px] font-semibold text-[var(--ink)]">
            Session active
          </span>
        ) : null}
      </div>

      {note ? <p className="mt-3 text-[12px] text-gray-500">{note}</p> : null}
      {error ? (
        <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)] ring-1 ring-[#E8E8EA]">
          {error}
        </div>
      ) : null}
      {sessionId ? (
        <p className="mt-2 font-mono text-[11px] text-gray-400">
          session_id={sessionId}
        </p>
      ) : null}
    </section>
  );
}
