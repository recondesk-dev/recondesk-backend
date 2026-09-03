/** Shared helpers for GSTR-1 filing UI. */

export function toFilingPeriodYyyyMm(
  raw: string | null | undefined
): string | null {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (!s) return null;
  // YYYY-MM
  if (/^\d{4}-\d{2}$/.test(s)) return s;
  // YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 7);
  // MMYYYY
  if (/^\d{6}$/.test(s)) {
    const mm = s.slice(0, 2);
    const yyyy = s.slice(2);
    return `${yyyy}-${mm}`;
  }
  return null;
}

export function decisionNeededLabel(decision: string): string {
  switch (decision) {
    case "inv_typ":
      return "Invoice type (inv_typ)";
    case "ntty":
      return "Note type (ntty)";
    case "exp_typ":
      return "Export type (exp_typ)";
    case "table_classification":
      return "Table classification";
    case "net_negative_adjustment":
      return "Net negative B2CS (carry forward)";
    default:
      return decision;
  }
}

export function tableLabel(table: string): string {
  const map: Record<string, string> = {
    b2b: "B2B",
    b2cs: "B2C (small)",
    b2cl: "B2C (large)",
    cdnr: "Credit / debit notes (registered)",
    cdnur: "Credit / debit notes (unregistered)",
    exp: "Exports",
    nil: "Nil-rated / exempt",
    hsn: "HSN summary",
    doc_issue: "Documents issued",
    at: "Advances (AT)",
    txpd: "Advances adjusted (TXPD)",
    unclassified: "Unclassified",
  };
  return map[table] || table.toUpperCase();
}

/** Server-confirmed Save success (or later filing steps). Never infer from readiness. */
export function isGstnSaveConfirmed(runStatus: string | null | undefined): boolean {
  return (
    runStatus === "saved" ||
    runStatus === "proceeded" ||
    runStatus === "evc_pending" ||
    runStatus === "filed"
  );
}

export function isSaveTerminalFailure(
  runStatus: string | null | undefined
): boolean {
  return runStatus === "save_failed" || runStatus === "failed";
}

/** GSTR-3B: Save confirmed (before Offset). */
export function isGstr3bSaveConfirmed(
  runStatus: string | null | undefined
): boolean {
  return (
    runStatus === "saved" ||
    runStatus === "offset_pending" ||
    runStatus === "offset_complete" ||
    runStatus === "offset_failed" ||
    runStatus === "evc_pending" ||
    runStatus === "filed"
  );
}

export function isGstr3bSaveFailed(
  runStatus: string | null | undefined
): boolean {
  return runStatus === "save_failed" || runStatus === "failed";
}

export function isGstr3bOffsetComplete(
  runStatus: string | null | undefined
): boolean {
  return (
    runStatus === "offset_complete" ||
    runStatus === "evc_pending" ||
    runStatus === "filed"
  );
}
