/** Workspace audit log row from GET /api/audit-logs */

export type AuditLogAction =
  | "FILE_UPLOADED"
  | "RECON_STARTED"
  | "RECON_COMPLETED"
  | "RECON_FINALIZED"
  | "MISMATCH_NOTE_ADDED"
  | "MISMATCH_NOTE_EDITED"
  | "CLIENT_ADDED"
  | "CLIENT_DELETED"
  | "RESULT_EXPORTED"
  | (string & {});

export type AuditLogRow = {
  id: string;
  firm_id: string | null;
  user_id: string | null;
  user_name: string | null;
  role: string | null;
  action: AuditLogAction;
  entity_type: string;
  entity_id: string | null;
  entity_label: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

export type AuditLogListResponse = {
  data: AuditLogRow[];
  total: number;
  limit: number;
  offset: number;
};

export const AUDIT_ACTION_OPTIONS: { value: AuditLogAction; label: string }[] = [
  { value: "FILE_UPLOADED", label: "File uploaded" },
  { value: "RECON_STARTED", label: "Reconciliation started" },
  { value: "RECON_COMPLETED", label: "Reconciliation completed" },
  { value: "RECON_FINALIZED", label: "Reconciliation finalized" },
  { value: "MISMATCH_NOTE_ADDED", label: "Note added" },
  { value: "MISMATCH_NOTE_EDITED", label: "Note edited" },
  { value: "CLIENT_ADDED", label: "Client added" },
  { value: "CLIENT_DELETED", label: "Client deleted" },
  { value: "RESULT_EXPORTED", label: "Result exported" },
];

const ACTION_VERB: Record<string, string> = {
  FILE_UPLOADED: "uploaded file",
  RECON_STARTED: "started reconciliation",
  RECON_COMPLETED: "completed reconciliation",
  RECON_FINALIZED: "finalized reconciliation",
  MISMATCH_NOTE_ADDED: "added a mismatch note",
  MISMATCH_NOTE_EDITED: "edited a mismatch note",
  CLIENT_ADDED: "added client",
  CLIENT_DELETED: "removed client",
  RESULT_EXPORTED: "exported results",
};

export function formatAuditActionLabel(action: string): string {
  const found = AUDIT_ACTION_OPTIONS.find((o) => o.value === action);
  if (found) return found.label;
  return action.replace(/_/g, " ").toLowerCase();
}

export function formatActivityTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "numeric",
      month: "short",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return iso;
  }
}

function exportTypeLabel(meta: Record<string, unknown> | null | undefined): string {
  const t = String(meta?.export_type ?? "").toLowerCase();
  if (t.includes("excel")) return "Excel workbook";
  if (t.includes("itc")) return "missed ITC CSV";
  if (t.includes("risk")) return "risk CSV";
  return "results";
}

/** Plain-language sentence for table Details column and summaries. */
export function formatActivityMessage(row: AuditLogRow): string {
  const name = row.user_name?.trim() || "Someone";
  const verb = ACTION_VERB[row.action] ?? formatAuditActionLabel(row.action).toLowerCase();
  const when = formatActivityTimestamp(row.created_at);
  const entity = row.entity_label?.trim();

  if (row.action === "FILE_UPLOADED") {
    const fileName = entity || "a file";
    const clientPart = entity && entity !== fileName ? ` for ${entity}` : "";
    if (row.metadata?.file_type === "gstr2b") {
      return `${name} uploaded GSTR-2B file${clientPart ? ` (${fileName})` : ""} on ${when}`;
    }
    if (row.metadata?.file_type === "purchase_register") {
      return `${name} uploaded purchase register${entity ? ` (${entity})` : ""} on ${when}`;
    }
    return `${name} uploaded ${fileName}${clientPart} on ${when}`;
  }

  if (row.action === "RESULT_EXPORTED") {
    const exportKind = exportTypeLabel(row.metadata);
    return `${name} exported ${exportKind}${entity ? ` for ${entity}` : ""} on ${when}`;
  }

  if (row.action === "CLIENT_ADDED" || row.action === "CLIENT_DELETED") {
    return `${name} ${verb}${entity ? ` ${entity}` : ""} on ${when}`;
  }

  if (entity) {
    return `${name} ${verb} for ${entity} on ${when}`;
  }

  return `${name} ${verb} on ${when}`;
}

export function formatActivityDetails(row: AuditLogRow): string {
  const meta = row.metadata ?? {};
  const parts: string[] = [];

  if (meta.file_type && typeof meta.file_type === "string") {
    parts.push(`Type: ${meta.file_type}`);
  }
  if (meta.export_type && typeof meta.export_type === "string") {
    parts.push(`Export: ${meta.export_type}`);
  }
  if (meta.note_id) {
    parts.push(`Note ${String(meta.note_id).slice(0, 8)}…`);
  }
  if (meta.match_rate_percent != null) {
    parts.push(`Match rate: ${meta.match_rate_percent}%`);
  }

  return parts.length > 0 ? parts.join(" · ") : "—";
}
