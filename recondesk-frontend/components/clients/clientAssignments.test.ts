/**
 * Unit tests for Phase 3.1: Client Team & Multi-Role Assignments and Granular RBAC.
 * Run with: ./node_modules/.bin/sucrase-node components/clients/clientAssignments.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  getRoleConfig,
  initialsFromLabel,
  ROLE_CONFIGS,
  type AssignmentRole,
} from "./clientAssignmentsLogic";
import {
  normalizeAuthRole,
  isRoleAdminOrPartner,
  isRoleManagerOrAbove,
  isRoleWriterOrAbove,
} from "../../lib/auth-profile";
import { clientsApi } from "../../lib/api";

describe("Phase 3.1: Granular RBAC Authorization Invariants", () => {
  it("1. normalizeAuthRole fails closed to 'viewer' for unknown or undefined roles", () => {
    assert.equal(normalizeAuthRole(undefined), "viewer");
    assert.equal(normalizeAuthRole(null), "viewer");
    assert.equal(normalizeAuthRole(""), "viewer");
    assert.equal(normalizeAuthRole("guest"), "viewer");
    assert.equal(normalizeAuthRole("hacker"), "viewer");
    assert.equal(normalizeAuthRole("invalid_role"), "viewer");
  });

  it("2. normalizeAuthRole correctly normalizes CA firm roles", () => {
    assert.equal(normalizeAuthRole("admin"), "admin");
    assert.equal(normalizeAuthRole("ADMIN"), "admin");
    assert.equal(normalizeAuthRole("owner"), "owner");
    assert.equal(normalizeAuthRole("OWNER"), "owner");
    assert.equal(normalizeAuthRole("partner"), "partner");
    assert.equal(normalizeAuthRole("PARTNER"), "partner");
    assert.equal(normalizeAuthRole("manager"), "manager");
    assert.equal(normalizeAuthRole("MANAGER"), "manager");
    assert.equal(normalizeAuthRole("preparer"), "preparer");
    assert.equal(normalizeAuthRole("PREPARER"), "preparer");
    assert.equal(normalizeAuthRole("viewer"), "viewer");
    assert.equal(normalizeAuthRole("staff"), "staff");
  });

  it("3. isRoleManagerOrAbove permits management only to Admin, Owner, Partner, and Manager", () => {
    assert.equal(isRoleManagerOrAbove("admin"), true);
    assert.equal(isRoleManagerOrAbove("owner"), true);
    assert.equal(isRoleManagerOrAbove("partner"), true);
    assert.equal(isRoleManagerOrAbove("manager"), true);

    // Preparer, Reviewer, Staff, Viewer are strictly forbidden from managing client assignments
    assert.equal(isRoleManagerOrAbove("preparer"), false);
    assert.equal(isRoleManagerOrAbove("reviewer"), false);
    assert.equal(isRoleManagerOrAbove("staff"), false);
    assert.equal(isRoleManagerOrAbove("viewer"), false);
    assert.equal(isRoleManagerOrAbove(""), false);
    assert.equal(isRoleManagerOrAbove(null), false);
    assert.equal(isRoleManagerOrAbove(undefined), false);
  });

  it("4. isRoleAdminOrPartner permits deletion and firm configuration strictly to Admin, Owner, and Partner", () => {
    assert.equal(isRoleAdminOrPartner("admin"), true);
    assert.equal(isRoleAdminOrPartner("owner"), true);
    assert.equal(isRoleAdminOrPartner("partner"), true);

    // Managers cannot delete clients or access activity log / firm settings
    assert.equal(isRoleAdminOrPartner("manager"), false);
    assert.equal(isRoleAdminOrPartner("preparer"), false);
    assert.equal(isRoleAdminOrPartner("reviewer"), false);
    assert.equal(isRoleAdminOrPartner("viewer"), false);
    assert.equal(isRoleAdminOrPartner("staff"), false);
  });

  it("5. isRoleWriterOrAbove allows work item and reconciliation write actions for operational roles", () => {
    assert.equal(isRoleWriterOrAbove("admin"), true);
    assert.equal(isRoleWriterOrAbove("owner"), true);
    assert.equal(isRoleWriterOrAbove("partner"), true);
    assert.equal(isRoleWriterOrAbove("manager"), true);
    assert.equal(isRoleWriterOrAbove("preparer"), true);
    assert.equal(isRoleWriterOrAbove("staff"), true);

    // Viewers are strictly read-only
    assert.equal(isRoleWriterOrAbove("viewer"), false);
    assert.equal(isRoleWriterOrAbove(null), false);
  });
});

describe("Phase 3.1: Client Multi-Role Presentation and Mapping", () => {
  it("1. getRoleConfig returns distinct styling and metadata for all CA roles", () => {
    const roles: AssignmentRole[] = ["partner", "manager", "reviewer", "preparer", "viewer"];
    for (const r of roles) {
      const cfg = getRoleConfig(r);
      assert.equal(cfg.key, r);
      assert.ok(cfg.label.length > 0);
      assert.ok(cfg.badgeBg.startsWith("bg-"));
      assert.ok(cfg.badgeText.startsWith("text-"));
      assert.ok(cfg.ringColor.startsWith("ring-"));
      assert.ok(cfg.description.length > 0);
      assert.ok(typeof cfg.iconName === "string" && cfg.iconName.length > 0);
    }
  });

  it("2. getRoleConfig defaults gracefully for unrecognized roles", () => {
    const fallback = getRoleConfig("custom_auditor");
    assert.equal(fallback.key, "viewer");
    assert.equal(fallback.label, "custom_auditor");
    assert.equal(fallback.badgeBg, "bg-gray-100");
  });

  it("3. initialsFromLabel generates clean, consistent two-letter avatar initials", () => {
    assert.equal(initialsFromLabel("Omkar Kadam"), "OK");
    assert.equal(initialsFromLabel("Dr. A. P. J. Kalam"), "DA");
    assert.equal(initialsFromLabel("TaxConsultant"), "TA");
    assert.equal(initialsFromLabel(""), "RD");
    assert.equal(initialsFromLabel("A"), "A");
  });

  it("4. ROLE_CONFIGS defines all expected GSTR compliance responsibilities", () => {
    assert.equal(ROLE_CONFIGS.partner.label, "Partner");
    assert.ok(ROLE_CONFIGS.partner.description.includes("Final statutory sign-off"));

    assert.equal(ROLE_CONFIGS.manager.label, "Manager");
    assert.ok(ROLE_CONFIGS.manager.description.includes("Engagement oversight"));

    assert.equal(ROLE_CONFIGS.reviewer.label, "Reviewer");
    assert.ok(ROLE_CONFIGS.reviewer.description.includes("ITC variance review"));

    assert.equal(ROLE_CONFIGS.preparer.label, "Preparer");
    assert.ok(ROLE_CONFIGS.preparer.description.includes("Data import"));

    assert.equal(ROLE_CONFIGS.viewer.label, "Viewer");
    assert.ok(ROLE_CONFIGS.viewer.description.includes("Read-only access"));
  });
});

describe("Phase 3.1: Client Assignments API Client Contract", () => {
  it("1. clientsApi exposes listAssignments, addAssignment, and removeAssignment methods", () => {
    assert.equal(typeof clientsApi.listAssignments, "function");
    assert.equal(typeof clientsApi.addAssignment, "function");
    assert.equal(typeof clientsApi.removeAssignment, "function");
  });
});
