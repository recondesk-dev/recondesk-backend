/**
 * Phase 3.1: Client Team & Multi-Role Assignments Domain Logic & Helpers.
 */

import {
  isRoleAdminOrPartner,
  isRoleManagerOrAbove,
  isRoleWriterOrAbove,
  normalizeAuthRole,
  type UserRole,
} from "../../lib/auth-profile";

export type AssignmentRole = "preparer" | "reviewer" | "manager" | "partner" | "viewer";

export interface RoleConfig {
  key: AssignmentRole;
  label: string;
  badgeBg: string;
  badgeText: string;
  ringColor: string;
  iconName: "Shield" | "ShieldCheck" | "UserCheck" | "FileSpreadsheet" | "Users";
  description: string;
}

export const ROLE_CONFIGS: Record<AssignmentRole, RoleConfig> = {
  partner: {
    key: "partner",
    label: "Partner",
    badgeBg: "bg-purple-50",
    badgeText: "text-purple-700",
    ringColor: "ring-purple-200",
    iconName: "Shield",
    description: "Final statutory sign-off, firm authority & audit defense",
  },
  manager: {
    key: "manager",
    label: "Manager",
    badgeBg: "bg-blue-50",
    badgeText: "text-blue-700",
    ringColor: "ring-blue-200",
    iconName: "ShieldCheck",
    description: "Engagement oversight, workflow batches & team assignments",
  },
  reviewer: {
    key: "reviewer",
    label: "Reviewer",
    badgeBg: "bg-amber-50",
    badgeText: "text-amber-800",
    ringColor: "ring-amber-200",
    iconName: "UserCheck",
    description: "ITC variance review, exception triage & vendor inquiry approval",
  },
  preparer: {
    key: "preparer",
    label: "Preparer",
    badgeBg: "bg-emerald-50",
    badgeText: "text-emerald-800",
    ringColor: "ring-emerald-200",
    iconName: "FileSpreadsheet",
    description: "Data import, invoice entry & draft reconciliation runs",
  },
  viewer: {
    key: "viewer",
    label: "Viewer",
    badgeBg: "bg-gray-100",
    badgeText: "text-gray-700",
    ringColor: "ring-gray-200",
    iconName: "Users",
    description: "Read-only access to client filing data and reports",
  },
};

export function getRoleConfig(rawRole: string): RoleConfig {
  const norm = (rawRole || "").trim().toLowerCase() as AssignmentRole;
  return (
    ROLE_CONFIGS[norm] || {
      key: "viewer",
      label: rawRole || "Member",
      badgeBg: "bg-gray-100",
      badgeText: "text-gray-700",
      ringColor: "ring-gray-200",
      iconName: "Users",
      description: "Client team member",
    }
  );
}

export function initialsFromLabel(label: string): string {
  const parts = label.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return label.slice(0, 2).toUpperCase() || "RD";
}

export function canManageClientAssignments(role: string | null | undefined): boolean {
  return isRoleManagerOrAbove(role);
}

export function canDeleteFirmClient(role: string | null | undefined): boolean {
  return isRoleAdminOrPartner(role);
}
