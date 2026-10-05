"use client";

import { useCallback, useEffect, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { gstnApi, isApiError } from "@/lib/api";

type Step = 1 | 2 | "success";

const inputClassName =
  "min-h-[44px] w-full rounded-full border-0 bg-[#F5F5F6] px-4 text-sm font-medium text-[var(--ink)] placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-black/10 disabled:cursor-not-allowed disabled:opacity-60";

function apiErrorMessage(err: unknown, fallback: string): string {
  if (isApiError(err)) return err.detail;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

export function ConnectGstnModal({
  open,
  onClose,
  clientGstinId,
  defaultGstin,
  authToken,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  clientGstinId: string;
  defaultGstin: string;
  authToken: string;
  onSuccess: () => void;
}) {
  const [step, setStep] = useState<Step>(1);
  const [gstin, setGstin] = useState(defaultGstin);
  const [username, setUsername] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const reset = useCallback(() => {
    setStep(1);
    setGstin(defaultGstin);
    setUsername("");
    setOtp("");
    setError(null);
    setLoading(false);
  }, [defaultGstin]);

  useEffect(() => {
    if (open) {
      reset();
    }
  }, [open, reset]);

  useEffect(() => {
    if (step !== "success") return;
    const timer = window.setTimeout(() => {
      onSuccess();
      onClose();
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [step, onSuccess, onClose]);

  const handleSendOtp = async () => {
    setError(null);
    setLoading(true);
    try {
      await gstnApi.sendOtp(authToken, clientGstinId, {
        gstin: gstin.trim(),
        username: username.trim(),
      });
      setStep(2);
    } catch (err) {
      setError(apiErrorMessage(err, "Failed to send OTP. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async () => {
    setError(null);
    setLoading(true);
    try {
      await gstnApi.verifyOtp(authToken, clientGstinId, {
        gstin: gstin.trim(),
        username: username.trim(),
        otp: otp.trim(),
      });
      setStep("success");
    } catch (err) {
      setError(apiErrorMessage(err, "Failed to verify OTP. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleResendOtp = async () => {
    setOtp("");
    setError(null);
    setLoading(true);
    try {
      await gstnApi.sendOtp(authToken, clientGstinId, {
        gstin: gstin.trim(),
        username: username.trim(),
      });
    } catch (err) {
      setError(apiErrorMessage(err, "Failed to resend OTP. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const canSend =
    gstin.trim().length > 0 && username.trim().length > 0 && !loading;
  const canVerify = /^\d{6}$/.test(otp.trim()) && !loading;

  return (
    <Modal
      open={open}
      onClose={() => !loading && onClose()}
      title="Connect GSTN"
      ariaLabel="Connect GSTN via OTP"
      footer={
        step === "success" ? null : step === 1 ? (
          <>
            <button
              type="button"
              disabled={loading}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-[#F5F5F6] px-4 text-sm font-medium text-[var(--ink)] disabled:opacity-50"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canSend}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              onClick={() => void handleSendOtp()}
            >
              {loading ? "Sending…" : "Send OTP"}
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={loading}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-[#F5F5F6] px-4 text-sm font-medium text-[var(--ink)] disabled:opacity-50"
              onClick={() => {
                setStep(1);
                setOtp("");
                setError(null);
              }}
            >
              Back
            </button>
            <button
              type="button"
              disabled={!canVerify}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              onClick={() => void handleVerifyOtp()}
            >
              {loading ? "Verifying…" : "Verify"}
            </button>
          </>
        )
      }
    >
      {step === "success" ? (
        <div className="py-6 text-center">
          <p className="text-lg font-semibold text-[var(--success)]">GSTN connected ✓</p>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            You can now auto-fetch GSTR-2B for this client.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {error}
            </div>
          )}

          {step === 1 && (
            <>
              <p className="text-sm text-[var(--text-secondary)]">
                Authenticate with the GST portal to enable automatic GSTR-2B fetch.
              </p>
              <div>
                <label
                  htmlFor="connect-gstin"
                  className="mb-1 block text-sm font-medium text-[var(--text-primary)]"
                >
                  GSTIN
                </label>
                <input
                  id="connect-gstin"
                  type="text"
                  value={gstin}
                  onChange={(e) => setGstin(e.target.value.toUpperCase())}
                  readOnly={Boolean(defaultGstin)}
                  className={`${inputClassName} font-mono ${defaultGstin ? "bg-gray-50" : ""}`}
                  autoComplete="off"
                />
              </div>
              <div>
                <label
                  htmlFor="connect-username"
                  className="mb-1 block text-sm font-medium text-[var(--text-primary)]"
                >
                  GST Portal username
                </label>
                <input
                  id="connect-username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={loading}
                  className={inputClassName}
                  placeholder="Portal login username"
                  autoComplete="username"
                />
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <p className="text-sm text-[var(--text-secondary)]">
                Enter the 6-digit OTP sent to the registered mobile for{" "}
                <span className="font-mono font-medium text-[var(--text-primary)]">
                  {gstin}
                </span>
                .
              </p>
              <div>
                <label
                  htmlFor="connect-otp"
                  className="mb-1 block text-sm font-medium text-[var(--text-primary)]"
                >
                  OTP
                </label>
                <input
                  id="connect-otp"
                  type="text"
                  inputMode="numeric"
                  pattern="\d{6}"
                  maxLength={6}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  disabled={loading}
                  className={`${inputClassName} font-mono tracking-widest`}
                  placeholder="000000"
                  autoComplete="one-time-code"
                />
              </div>
              <button
                type="button"
                disabled={loading}
                className="text-sm font-semibold text-[var(--ink)] underline disabled:opacity-50"
                onClick={() => void handleResendOtp()}
              >
                Resend OTP
              </button>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}

export function isGstnConnected(client: {
  gstn_access_token?: string | null;
  has_gstn_token?: boolean | null;
  gstn_token_expiry?: string | null;
} | null | undefined): boolean {
  if (!client?.has_gstn_token && !client?.gstn_access_token) return false;
  if (client.gstn_token_expiry) {
    return new Date(client.gstn_token_expiry) > new Date();
  }
  return true;
}
