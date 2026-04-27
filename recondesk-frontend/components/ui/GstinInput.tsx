"use client";

import { useState, useCallback } from "react";

const GSTIN_REGEX = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
const STATE_REGEX = /^(0[1-9]|[1-2][0-9]|3[0-8])$/;

export type GstinFieldStatus = "idle" | "valid" | "invalid";

export function validateGstin(value: string): {
  status: GstinFieldStatus;
  message: string | null;
} {
  const v = value.trim().toUpperCase();
  if (!v) return { status: "idle", message: null };
  if (v.length !== 15) {
    return { status: "invalid", message: "Must be 15 characters" };
  }
  const state = v.slice(0, 2);
  if (!STATE_REGEX.test(state)) {
    return { status: "invalid", message: "Invalid state code" };
  }
  if (!GSTIN_REGEX.test(v)) {
    return { status: "invalid", message: "Invalid format" };
  }
  return { status: "valid", message: "Valid GSTIN" };
}

export function GstinInput({
  value,
  onChange,
  id,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  id?: string;
  disabled?: boolean;
}) {
  const [touched, setTouched] = useState(false);
  const upper = value.toUpperCase().replace(/[^0-9A-Z]/g, "").slice(0, 15);
  const { status, message } = touched ? validateGstin(upper) : { status: "idle" as const, message: null as string | null };

  const showMsg = touched && upper.length > 0;

  const onBlur = useCallback(() => {
    setTouched(true);
  }, []);

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-[var(--text-primary)]">
        GSTIN
      </label>
      <input
        id={id}
        type="text"
        autoComplete="off"
        disabled={disabled}
        value={upper}
        onChange={(e) => onChange(e.target.value.toUpperCase().replace(/[^0-9A-Z]/g, "").slice(0, 15))}
        onBlur={onBlur}
        className="w-full rounded-lg border border-[var(--border)] px-3 py-2 font-mono text-sm tracking-wide text-[var(--text-primary)] outline-none focus:ring-2 focus:ring-[var(--accent)]"
        maxLength={15}
        placeholder="15-character GSTIN"
      />
      {showMsg && message && (
        <p
          className={`mt-1 flex items-center gap-1 text-xs ${
            status === "valid" ? "text-[var(--success)]" : "text-[var(--danger)]"
          }`}
        >
          {status === "valid" ? (
            <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                clipRule="evenodd"
              />
            </svg>
          ) : (
            <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                clipRule="evenodd"
              />
            </svg>
          )}
          {message}
        </p>
      )}
    </div>
  );
}
