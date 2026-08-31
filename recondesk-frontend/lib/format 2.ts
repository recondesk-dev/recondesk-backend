/** En-IN number part: no decimals when paise is zero, else exactly 2 decimal places. */
export function formatINRNumber(amount: number): string {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const paise = Math.round(abs * 100) % 100;
  if (paise === 0) {
    return (
      sign +
      Math.trunc(abs).toLocaleString("en-IN", {
        maximumFractionDigits: 0,
        minimumFractionDigits: 0,
      })
    );
  }
  return (
    sign +
    abs.toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

/** Full INR display with ₹ prefix (e.g. ₹14,614 or ₹14,614.12). */
export function formatINR(amount: number): string {
  const num = formatINRNumber(amount);
  if (num === "—") return num;
  return `₹${num}`;
}

export function formatInrCompact(amount: number): string {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e7) {
    return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`;
  }
  if (abs >= 1e5) {
    return `${sign}₹${(abs / 1e5).toFixed(2)}L`;
  }
  return formatINR(n);
}

export function formatInrFull(n: number): string {
  return formatINR(n);
}

const LEGACY_TAX_DELTA_PAISE_RE = /GST tax delta \(Δpaise\):\s*([\d,]+)/;

/** Matched-row tax difference: column shows INR only; tooltip includes label. */
export function formatTaxDifferenceDisplay(
  taxDifferencePaise: number | null | undefined,
  legacyDiscrepancyNote?: string | null
): { display: string | null; tooltip: string | null } {
  let paise: number | null = null;
  if (taxDifferencePaise != null && Number.isFinite(taxDifferencePaise)) {
    paise = taxDifferencePaise;
  } else if (legacyDiscrepancyNote?.trim()) {
    const m = legacyDiscrepancyNote.match(LEGACY_TAX_DELTA_PAISE_RE);
    if (m) {
      const parsed = Number(m[1].replace(/,/g, ""));
      if (Number.isFinite(parsed)) paise = parsed;
    }
  }

  if (paise == null) {
    const fallback = legacyDiscrepancyNote?.trim() || null;
    return { display: fallback, tooltip: fallback };
  }

  const inr = formatINR(paise / 100);
  return { display: inr, tooltip: `Tax difference: ${inr}` };
}

export function formatInrAxis(n: number): string {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(1)}Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`;
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(0)}K`;
  return `₹${n}`;
}

export function truncateGstin(gstin: string): string {
  if (gstin.length <= 12) return gstin;
  return `${gstin.slice(0, 7)}…${gstin.slice(-4)}`;
}
