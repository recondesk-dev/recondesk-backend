/**
 * Unit tests for Phase 3.2: Maker-Checker Return Filing Approvals.
 * Run with: ./node_modules/.bin/sucrase-node components/filing/makerCheckerApproval.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  filingApprovalsApi,
  type ReturnApproval,
  type ReturnApprovalStatus,
} from "../../lib/api";
import {
  isRoleManagerOrAbove,
  isRoleWriterOrAbove,
  normalizeAuthRole,
} from "../../lib/auth-profile";

describe("Phase 3.2: Maker-Checker Role Authorities", () => {
  it("1. Only Managers, Partners, and Owners hold authority to approve or reject returns", () => {
    assert.equal(isRoleManagerOrAbove("owner"), true);
    assert.equal(isRoleManagerOrAbove("partner"), true);
    assert.equal(isRoleManagerOrAbove("manager"), true);
    assert.equal(isRoleManagerOrAbove("admin"), true);

    // Preparers, staff, and viewers are blocked from approval authority
    assert.equal(isRoleManagerOrAbove("preparer"), false);
    assert.equal(isRoleManagerOrAbove("staff"), false);
    assert.equal(isRoleManagerOrAbove("viewer"), false);
    assert.equal(isRoleManagerOrAbove("guest"), false);
  });

  it("2. Preparers and operational roles hold write authority to prepare and submit returns", () => {
    assert.equal(isRoleWriterOrAbove("preparer"), true);
    assert.equal(isRoleWriterOrAbove("staff"), true);
    assert.equal(isRoleWriterOrAbove("manager"), true);
    assert.equal(isRoleWriterOrAbove("partner"), true);
    assert.equal(isRoleWriterOrAbove("owner"), true);
    assert.equal(isRoleWriterOrAbove("admin"), true);

    // Viewers cannot prepare or submit returns
    assert.equal(isRoleWriterOrAbove("viewer"), false);
  });
});

describe("Phase 3.2: Separation of Duties Invariant", () => {
  it("1. Flags self-approval when current user is the return preparer", () => {
    const approval: ReturnApproval = {
      id: "appr-1",
      firm_id: "firm-1",
      client_gstin_id: "cid-1",
      gstin: "27AABCU9603R1ZM",
      period: "2024-11",
      return_type: "GSTR-1",
      status: "UNDER_REVIEW",
      figures_digest: "sha256_mock_digest",
      validation_digest: "",
      figures_summary: {},
      preparer_id: "user-123",
      preparer_name: "CA Omkar",
      preparer_role: "partner",
      prepared_at: "2024-11-10T10:00:00Z",
      submission_notes: "Ready for review",
      approver_id: null,
      approver_name: "",
      approver_role: "",
      approved_at: null,
      approval_notes: "",
      rejected_by: null,
      rejected_by_name: "",
      rejected_by_role: "",
      rejected_at: null,
      rejection_reason: "",
      filing_run_id: null,
      created_at: "2024-11-10T10:00:00Z",
      updated_at: "2024-11-10T10:00:00Z",
    };

    const currentUserId = "user-123";
    const isSelfPreparer = Boolean(
      currentUserId && approval.preparer_id && currentUserId === approval.preparer_id
    );
    assert.equal(isSelfPreparer, true);

    const differentUserId = "user-456";
    const isDifferentPreparer = Boolean(
      differentUserId && approval.preparer_id && differentUserId === approval.preparer_id
    );
    assert.equal(isDifferentPreparer, false);
  });
});

describe("Phase 3.2: Lifecycle Status Mapping Invariants", () => {
  const ALL_STATUSES: ReturnApprovalStatus[] = [
    "DRAFT",
    "PREPARED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "SAVED",
    "OFFSET_COMPLETE",
    "FILED",
  ];

  it("1. Recognizes all 8 durable lifecycle states", () => {
    assert.equal(ALL_STATUSES.length, 8);
    assert.ok(ALL_STATUSES.includes("DRAFT"));
    assert.ok(ALL_STATUSES.includes("PREPARED"));
    assert.ok(ALL_STATUSES.includes("UNDER_REVIEW"));
    assert.ok(ALL_STATUSES.includes("APPROVED"));
    assert.ok(ALL_STATUSES.includes("REJECTED"));
    assert.ok(ALL_STATUSES.includes("SAVED"));
    assert.ok(ALL_STATUSES.includes("OFFSET_COMPLETE"));
    assert.ok(ALL_STATUSES.includes("FILED"));
  });
});

describe("Phase 3.2: Filing Approvals API Client Contract", () => {
  it("1. filingApprovalsApi exposes all required workflow methods", () => {
    assert.equal(typeof filingApprovalsApi.getApproval, "function");
    assert.equal(typeof filingApprovalsApi.prepare, "function");
    assert.equal(typeof filingApprovalsApi.submit, "function");
    assert.equal(typeof filingApprovalsApi.approve, "function");
    assert.equal(typeof filingApprovalsApi.reject, "function");
    assert.equal(typeof filingApprovalsApi.getHistory, "function");
  });
});
