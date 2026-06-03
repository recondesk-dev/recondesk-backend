"use client";

import { useState, useCallback } from "react";

export function isValidGSTIN(gstin: string): boolean {
  if (!gstin) return false;
  const cleaned = gstin.trim().toUpperCase();
  const regex = /^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
  return regex.test(cleaned);
}

export const GST_STATE_CODES: Record<string, string> = {
  "01": "Jammu & Kashmir",
  "02": "Himachal Pradesh",
  "03": "Punjab",
  "04": "Chandigarh",
  "05": "Uttarakhand",
  "06": "Haryana",
  "07": "Delhi",
  "08": "Rajasthan",
  "09": "Uttar Pradesh",
  "10": "Bihar",
  "11": "Sikkim",
  "12": "Arunachal Pradesh",
  "13": "Nagaland",
  "14": "Manipur",
  "15": "Mizoram",
  "16": "Tripura",
  "17": "Meghalaya",
  "18": "Assam",
  "19": "West Bengal",
  "20": "Jharkhand",
  "21": "Odisha",
  "22": "Chhattisgarh",
  "23": "Madhya Pradesh",
  "24": "Gujarat",
  "25": "Daman & Diu",
  "26": "Dadra & Nagar Haveli",
  "27": "Maharashtra",
  "28": "Andhra Pradesh",
  "29": "Karnataka",
  "30": "Goa",
  "31": "Lakshadweep",
  "32": "Kerala",
  "33": "Tamil Nadu",
  "34": "Puducherry",
  "35": "Andaman & Nicobar",
  "36": "Telangana",
  "37": "Andhra Pradesh (New)",
};

export function getGstStateName(gstin: string): string | null {
  if (!isValidGSTIN(gstin)) return null;
  return GST_STATE_CODES[gstin.trim().toUpperCase().slice(0, 2)] ?? null;
}

/** Sorted Indian state / UT names for profile and address dropdowns. */
export const INDIAN_STATE_NAMES = [...new Set(Object.values(GST_STATE_CODES))].sort(
  (a, b) => a.localeCompare(b)
);

export type GstinFieldStatus = "idle" | "valid" | "invalid";

export function validateGstin(value: string): {
  status: GstinFieldStatus;
  message: string | null;
} {
  const v = value.trim().toUpperCase();
  if (!v) return { status: "idle", message: null };
  if (!isValidGSTIN(v)) {
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
