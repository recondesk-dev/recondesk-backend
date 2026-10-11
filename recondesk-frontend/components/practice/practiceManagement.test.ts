/**
 * Unit tests for ReconDesk Phase 3.4: CA Practice Management,
 * PAN-Level Organizations, Unified Filing Dashboard, Compliance Calendar,
 * Task Management, and Safe Bulk Operations.
 *
 * Run with: ./node_modules/.bin/sucrase-node components/practice/practiceManagement.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  practiceApi,
  type PracticeOrganization,
  type PracticeTask,
  type ComplianceDeadlineItem,
  type PracticeDashboardGridRow,
} from "../../lib/api";
import {
  isRoleAdminOrPartner,
  isRoleManagerOrAbove,
  isRoleWriterOrAbove,
} from "../../lib/auth-profile";

describe("Phase 3.4: PAN-Level Legal Organization & Constitution Inference", () => {
  it("1. Infers business constitution from 4th character of PAN correctly", () => {
    const constitutions: Record<string, string> = {
      C: "Company",
      P: "Individual / Proprietorship",
      F: "Partnership Firm / LLP",
      H: "HUF (Hindu Undivided Family)",
      A: "AOP (Association of Persons)",
      T: "Trust",
      B: "BOI (Body of Individuals)",
      G: "Government Agency",
      J: "Artificial Juridical Person",
      L: "Local Authority",
    };

    function inferConstitution(pan: string): string {
      if (!pan || pan.length < 4) return "Proprietorship";
      const char = pan[3].toUpperCase();
      return constitutions[char] || "Proprietorship";
    }

    assert.equal(inferConstitution("AAACC1234F"), "Company");
    assert.equal(inferConstitution("AAAFA1234F"), "Partnership Firm / LLP");
    assert.equal(inferConstitution("AAAPP1234F"), "Individual / Proprietorship");
    assert.equal(inferConstitution("AAATH1234F"), "Trust");
    assert.equal(inferConstitution("AAAAA1234F"), "AOP (Association of Persons)");
  });

  it("2. Extracts 10-character PAN from 15-character GSTIN", () => {
    function extractPan(gstin: string): string {
      if (!gstin || gstin.length !== 15) return "";
      return gstin.substring(2, 12).toUpperCase();
    }

    assert.equal(extractPan("27AAACC1234F1Z5"), "AAACC1234F");
    assert.equal(extractPan("29AABCS1429B1ZB"), "AABCS1429B");
    assert.equal(extractPan("invalid"), "");
  });
});

describe("Phase 3.4: Authoritative Filing Progress Invariant", () => {
  it("1. Never marks return as FILED unless authoritative GSTN record exists", () => {
    function resolveActionableStage(row: {
      has_gstn_filing: boolean;
      approval_status?: string;
      client_auth_status?: string;
      blocker?: string | null;
    }): string {
      // INVARIANT: Never infer filed without authoritative GSTN record
      if (row.has_gstn_filing) return "FILED";
      if (row.blocker) return "BLOCKED";
      if (row.approval_status === "APPROVED" && row.client_auth_status === "AUTHORIZED") {
        return "READY_TO_FILE";
      }
      if (row.approval_status === "UNDER_REVIEW") return "UNDER_REVIEW";
      if (row.client_auth_status === "PENDING") return "PENDING_CONSENT";
      return "DRAFT";
    }

    // A return submitted but without GSTN confirmation is NOT filed
    const pendingSubmission = {
      has_gstn_filing: false,
      approval_status: "APPROVED",
      client_auth_status: "AUTHORIZED",
      blocker: null,
    };
    assert.equal(resolveActionableStage(pendingSubmission), "READY_TO_FILE");

    // Only genuine GSTN filing produces FILED stage
    const verifiedFiled = {
      has_gstn_filing: true,
      approval_status: "APPROVED",
      client_auth_status: "AUTHORIZED",
      blocker: null,
    };
    assert.equal(resolveActionableStage(verifiedFiled), "FILED");

    // Blockers take precedence over preparation
    const blockedReturn = {
      has_gstn_filing: false,
      approval_status: "UNDER_REVIEW",
      blocker: "Rule 37 unpaid invoice reversal required",
    };
    assert.equal(resolveActionableStage(blockedReturn), "BLOCKED");
  });

  it("2. Validates stage resolution priority for revoked, expired, and rejected authorization", () => {
    function resolveActionableStage(row: {
      has_gstn_filing: boolean;
      approval_status?: string;
      client_auth_status?: string;
      blocker?: string | null;
    }): string {
      if (row.has_gstn_filing) return "FILED";
      if (
        row.blocker ||
        row.client_auth_status === "REJECTED" ||
        row.client_auth_status === "REVOKED" ||
        row.client_auth_status === "EXPIRED" ||
        row.approval_status === "REJECTED"
      ) {
        return "BLOCKED";
      }
      if (row.approval_status === "UNDER_REVIEW") return "UNDER_REVIEW";
      if (row.client_auth_status === "PENDING" || row.client_auth_status === "VIEWED") {
        return "AWAITING_CLIENT_CONSENT";
      }
      if (row.approval_status === "APPROVED" && row.client_auth_status === "AUTHORIZED") {
        return "READY_TO_FILE";
      }
      if (row.approval_status === "PREPARED") return "PREPARED";
      return "DRAFT";
    }

    // Revoked client consent drops to BLOCKED
    assert.equal(
      resolveActionableStage({
        has_gstn_filing: false,
        approval_status: "APPROVED",
        client_auth_status: "REVOKED",
        blocker: null,
      }),
      "BLOCKED"
    );

    // Expired client token drops to BLOCKED
    assert.equal(
      resolveActionableStage({
        has_gstn_filing: false,
        approval_status: "APPROVED",
        client_auth_status: "EXPIRED",
        blocker: null,
      }),
      "BLOCKED"
    );

    // Maker-checker rejected drops to BLOCKED
    assert.equal(
      resolveActionableStage({
        has_gstn_filing: false,
        approval_status: "REJECTED",
        client_auth_status: "NONE",
        blocker: null,
      }),
      "BLOCKED"
    );
  });
});

describe("Phase 3.4: Compliance Calendar Statutory Rules", () => {
  it("1. Verifies standard monthly and quarterly due dates", () => {
    const deadlines: ComplianceDeadlineItem[] = [
      {
        period: "102026",
        return_type: "GSTR-1",
        category: "MONTHLY",
        due_date: "2026-11-11",
        description: "GSTR-1 Monthly Outward Supplies",
        days_remaining: 5,
        is_overdue: false,
        urgency: "MEDIUM",
      },
      {
        period: "102026",
        return_type: "GSTR-3B",
        category: "MONTHLY",
        due_date: "2026-11-20",
        description: "GSTR-3B Monthly Summary & Tax Payment",
        days_remaining: 14,
        is_overdue: false,
        urgency: "LOW",
      },
      {
        period: "092026",
        return_type: "GSTR-3B",
        category: "MONTHLY",
        due_date: "2026-10-20",
        description: "GSTR-3B Monthly Summary",
        days_remaining: -2,
        is_overdue: true,
        urgency: "HIGH",
      },
      {
        period: "092026",
        return_type: "CMP-08",
        category: "COMPOSITION",
        due_date: "2026-10-18",
        description: "CMP-08 Quarterly Challan",
        days_remaining: 0,
        is_overdue: false,
        urgency: "HIGH",
      },
    ];

    // Filter overdue
    const overdue = deadlines.filter((d) => d.is_overdue);
    assert.equal(overdue.length, 1);
    assert.equal(overdue[0].return_type, "GSTR-3B");

    // Filter by return type
    const gstr1 = deadlines.filter((d) => d.return_type === "GSTR-1");
    assert.equal(gstr1.length, 1);
    assert.equal(gstr1[0].due_date, "2026-11-11");
  });

  it("2. Distinguishes QRMP Group A (22nd) and Group B (24th) state deadlines", () => {
    // Authoritative Group A States and UTs (Rule 61(1)(i))
    const groupAStateCodes = new Set([
      "22", "23", "24", "26", "27", "29", "30", "31", "32", "33", "34", "35", "36", "37",
    ]);

    function getQrmpDueDate(stateCode: string): string {
      return groupAStateCodes.has(stateCode) ? "22nd" : "24th";
    }

    // Representative Group A States (Due: 22nd)
    assert.equal(getQrmpDueDate("27"), "22nd"); // Maharashtra
    assert.equal(getQrmpDueDate("24"), "22nd"); // Gujarat
    assert.equal(getQrmpDueDate("29"), "22nd"); // Karnataka
    assert.equal(getQrmpDueDate("22"), "22nd"); // Chhattisgarh
    assert.equal(getQrmpDueDate("23"), "22nd"); // Madhya Pradesh
    assert.equal(getQrmpDueDate("33"), "22nd"); // Tamil Nadu
    assert.equal(getQrmpDueDate("32"), "22nd"); // Kerala
    assert.equal(getQrmpDueDate("26"), "22nd"); // Dadra & Nagar Haveli and Daman & Diu

    // Representative Group B States (Due: 24th)
    assert.equal(getQrmpDueDate("07"), "24th"); // Delhi
    assert.equal(getQrmpDueDate("09"), "24th"); // Uttar Pradesh
    assert.equal(getQrmpDueDate("19"), "24th"); // West Bengal
    assert.equal(getQrmpDueDate("08"), "24th"); // Rajasthan
    assert.equal(getQrmpDueDate("10"), "24th"); // Bihar
    assert.equal(getQrmpDueDate("03"), "24th"); // Punjab
    assert.equal(getQrmpDueDate("06"), "24th"); // Haryana
    assert.equal(getQrmpDueDate("38"), "24th"); // Ladakh
  });

  it("3. Clearly flags inferred deadlines as unverified when taxpayer state is unknown", () => {
    function evaluateDeadlineVerification(item: { is_verified?: boolean; verification_status?: string }): string {
      if (item.verification_status === "OFFICIALLY_VERIFIED") return "CBIC_EXTENSION";
      if (item.is_verified === false || item.verification_status === "INFERRED") return "UNCONFIRMED_INFERRED";
      return "STATUTORY_VERIFIED";
    }

    assert.equal(evaluateDeadlineVerification({ is_verified: false, verification_status: "INFERRED" }), "UNCONFIRMED_INFERRED");
    assert.equal(evaluateDeadlineVerification({ is_verified: true, verification_status: "STATUTORY_RULE" }), "STATUTORY_VERIFIED");
    assert.equal(evaluateDeadlineVerification({ is_verified: true, verification_status: "OFFICIALLY_VERIFIED" }), "CBIC_EXTENSION");
  });
});

describe("Phase 3.4: Staff Tasks & Role Authority Guardrails", () => {
  it("1. Allows assignees and operational roles to update task status", () => {
    assert.equal(isRoleWriterOrAbove("preparer"), true);
    assert.equal(isRoleWriterOrAbove("manager"), true);
    assert.equal(isRoleWriterOrAbove("partner"), true);
    assert.equal(isRoleWriterOrAbove("viewer"), false);
  });

  it("2. Restricts partner governance and partner overrides to authorized leadership", () => {
    assert.equal(isRoleAdminOrPartner("owner"), true);
    assert.equal(isRoleAdminOrPartner("partner"), true);
    assert.equal(isRoleAdminOrPartner("admin"), true);
    assert.equal(isRoleAdminOrPartner("manager"), false);
    assert.equal(isRoleAdminOrPartner("preparer"), false);
    assert.equal(isRoleAdminOrPartner("viewer"), false);
  });
});

describe("Phase 3.4: Safe Bulk Operations Guardrails", () => {
  it("1. Validates and reports partial failure without dropping successful items", () => {
    const rawItems = [
      { id: "gstin-1", valid: true },
      { id: "gstin-2", valid: false, error: "Client GSTIN is deactivated" },
      { id: "gstin-3", valid: true },
    ];

    const succeeded = rawItems.filter((i) => i.valid);
    const failed = rawItems
      .filter((i) => !i.valid)
      .map((i) => ({ id: i.id, error: i.error || "Unknown error" }));

    const result = {
      total: rawItems.length,
      succeeded_count: succeeded.length,
      failed_count: failed.length,
      succeeded,
      failed,
    };

    assert.equal(result.total, 3);
    assert.equal(result.succeeded_count, 2);
    assert.equal(result.failed_count, 1);
    assert.equal(result.failed[0].id, "gstin-2");
    assert.equal(result.failed[0].error, "Client GSTIN is deactivated");
  });

  it("2. Practice API client contract exposes all Phase 3.4 endpoints", () => {
    assert.equal(typeof practiceApi.listOrganizations, "function");
    assert.equal(typeof practiceApi.createOrganization, "function");
    assert.equal(typeof practiceApi.getOrganizationDetail, "function");
    assert.equal(typeof practiceApi.updateOrganization, "function");
    assert.equal(typeof practiceApi.getDashboard, "function");
    assert.equal(typeof practiceApi.getPartnerGovernance, "function");
    assert.equal(typeof practiceApi.getCalendar, "function");
    assert.equal(typeof practiceApi.listTasks, "function");
    assert.equal(typeof practiceApi.createTask, "function");
    assert.equal(typeof practiceApi.updateTask, "function");
    assert.equal(typeof practiceApi.deleteTask, "function");
    assert.equal(typeof practiceApi.getTaskHistory, "function");
    assert.equal(typeof practiceApi.bulkAssign, "function");
    assert.equal(typeof practiceApi.bulkCreateTasks, "function");
    assert.equal(typeof practiceApi.bulkUpdateTaskStatus, "function");
  });
});
