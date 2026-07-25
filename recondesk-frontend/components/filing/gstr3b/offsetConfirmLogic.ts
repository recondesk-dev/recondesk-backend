/** Pure helpers for GSTR-3B Offset deliberate confirmation. */

export type OffsetConfirmSteps = {
  reviewed: boolean;
  typedCashTotal: string;
  holdProgressMs: number;
};

export const OFFSET_HOLD_MS = 2000;

export const EMPTY_OFFSET_CONFIRM_STEPS: OffsetConfirmSteps = {
  reviewed: false,
  typedCashTotal: "",
  holdProgressMs: 0,
};

/** Sum of cash tax heads GSTN will debit (ipd+cpd+spd+cspd across pdcash rows). */
export function sumPdcashTaxOutflow(
  pdcash: Array<Record<string, unknown>> | null | undefined
): number {
  if (!Array.isArray(pdcash)) return 0;
  let total = 0;
  for (const row of pdcash) {
    if (!row || typeof row !== "object") continue;
    total += num(row.ipd) + num(row.cpd) + num(row.spd) + num(row.cspd);
  }
  return total;
}

export function sumPditcItc(
  pditc: Record<string, unknown> | null | undefined
): number {
  if (!pditc || typeof pditc !== "object") return 0;
  return (
    num(pditc.i_pdi) +
    num(pditc.i_pdc) +
    num(pditc.i_pds) +
    num(pditc.c_pdi) +
    num(pditc.c_pdc) +
    num(pditc.s_pdi) +
    num(pditc.s_pds) +
    num(pditc.cs_pdcs)
  );
}

function num(v: unknown): number {
  if (v == null || v === "") return 0;
  const n = typeof v === "number" ? v : Number(String(v).replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

/** Parse CA-typed cash total (allows commas / ₹ / spaces). */
export function parseTypedCashTotal(raw: string): number | null {
  const cleaned = String(raw || "")
    .replace(/₹/g, "")
    .replace(/,/g, "")
    .replace(/\s/g, "")
    .trim();
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return n;
}

export function typedCashMatchesExpected(
  typed: string,
  expectedCashTotal: number
): boolean {
  const parsed = parseTypedCashTotal(typed);
  if (parsed == null) return false;
  return Math.abs(parsed - expectedCashTotal) < 0.005;
}

export function canStartHold(steps: OffsetConfirmSteps, expectedCash: number): boolean {
  return steps.reviewed && typedCashMatchesExpected(steps.typedCashTotal, expectedCash);
}

export function isHoldComplete(
  steps: OffsetConfirmSteps,
  holdMs: number = OFFSET_HOLD_MS
): boolean {
  return steps.holdProgressMs >= holdMs;
}

/**
 * Full reset of the deliberate sequence after a stale rejection or
 * refreshed preview — CA must not resume from step 3 with old muscle memory.
 */
export function resetOffsetConfirmSteps(): OffsetConfirmSteps {
  return { ...EMPTY_OFFSET_CONFIRM_STEPS };
}

export function formatInr(n: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(n);
}
