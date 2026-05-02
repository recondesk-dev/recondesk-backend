"use client";

import { useState, useCallback } from "react";

/** 15-char GSTIN pattern (user-specified). */
const GSTIN_REGEX =
  /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9][Z][0-9A-Z]$/;

export type GstinFieldStatus = "idle" | "valid" | "invalid";

export function validateGstin(value: string): {
  status: GstinFieldStatus;
  message: string | null;
} {
  const v = value.trim().toUpperCase();
  if (!v) return { status: "idle", message: null };
  if (v.length !== 15) {
    return { status: "invalid", message: "Invalid GSTIN format" };
  }
  if (!GSTIN_REGEX.test(v)) {
    return { status: "invalid", message: "Invalid GSTIN format" };
  }
  return { status: "valid", message: null };
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
  const { status, message } = touched
    ? validateGstin(upper)
    : { status: "idle" as const, message: null as string | null };

  const showFeedback = touched && upper.length > 0;
  const showValidInline = showFeedback && status === "valid";
  const showInvalidInline = showFeedback && status === "invalid";

  const onBlur = useCallback(() => {
    setTouched(true);
  }, []);

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-[var(--text-primary)]">
        GSTIN
      </label>
      <div className="relative">
        <input
          id={id}
          type="text"
          autoComplete="off"
          disabled={disabled}
          value={upper}
          onChange={(e) =>
            onChange(e.target.value.toUpperCase().replace(/[^0-9A-Z]/g, "").slice(0, 15))
          }
          onBlur={onBlur}
          className={`w-full rounded-lg border border-[var(--border)] px-3 py-2 font-mono text-sm tracking-wide text-[var(--text-primary)] outline-none focus:ring-2 focus:ring-[var(--accent)] ${
            showValidInline ? "pr-10" : showInvalidInline ? "pr-10" : ""
          }`}
          maxLength={15}
          placeholder="15-character GSTIN"
          aria-invalid={showInvalidInline}
        />
        {showValidInline && (
          <span
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-lg font-semibold text-[var(--success)]"
            aria-hidden
          >
            ✓
          </span>
        )}
        {showInvalidInline && (
          <span
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-lg font-semibold text-[var(--danger)]"
            aria-hidden
          >
            ✕
          </span>
        )}
      </div>
      {showInvalidInline && message && (
        <p className="mt-1 text-xs text-[var(--danger)]">{message}</p>
      )}
    </div>
  );
}
