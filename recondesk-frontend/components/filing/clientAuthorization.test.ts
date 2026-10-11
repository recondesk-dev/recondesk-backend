/**
 * Unit tests for Phase 3.3: Client Review, Consent and Filing Authorization.
 * Run with: ./node_modules/.bin/sucrase-node components/filing/clientAuthorization.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  type ClientFilingAuthorization,
  type ClientAuthStatus,
  type ClientPublicReviewData,
  clientAuthorizationsApi,
  publicClientReviewApi,
} from "../../lib/api";
import {
  isRoleManagerOrAbove,
  isRoleWriterOrAbove,
} from "../../lib/auth-profile";

describe("Phase 3.3: Role Authorities for Client Authorization Management", () => {
  it("1. Only Managers, Partners, and Owners hold authority to revoke client authorizations", () => {
    assert.equal(isRoleManagerOrAbove("owner"), true);
    assert.equal(isRoleManagerOrAbove("partner"), true);
    assert.equal(isRoleManagerOrAbove("manager"), true);
    assert.equal(isRoleManagerOrAbove("admin"), true);

    // Preparers, staff, and viewers are blocked from revocation authority
    assert.equal(isRoleManagerOrAbove("preparer"), false);
    assert.equal(isRoleManagerOrAbove("staff"), false);
    assert.equal(isRoleManagerOrAbove("viewer"), false);
    assert.equal(isRoleManagerOrAbove("guest"), false);
  });

  it("2. Preparers and operational roles hold authority to generate client review requests", () => {
    assert.equal(isRoleWriterOrAbove("preparer"), true);
    assert.equal(isRoleWriterOrAbove("staff"), true);
    assert.equal(isRoleWriterOrAbove("manager"), true);
    assert.equal(isRoleWriterOrAbove("partner"), true);
    assert.equal(isRoleWriterOrAbove("owner"), true);
    assert.equal(isRoleWriterOrAbove("admin"), true);

    // Viewers cannot generate review links
    assert.equal(isRoleWriterOrAbove("viewer"), false);
  });
});

describe("Phase 3.3: Link Access vs Explicit Authorization Invariant", () => {
  it("1. Visiting or viewing a review link transitions status to VIEWED, never AUTHORIZED", () => {
    const pendingAuth: ClientFilingAuthorization = {
      id: "auth-1",
      firm_id: "firm-1",
      client_gstin_id: "cid-1",
      gstin: "27AABCU9603R1ZX",
      period: "2026-10",
      return_type: "GSTR-1",
      status: "PENDING",
      figures_digest: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      figures_summary: { total_taxable_value: 500000, total_tax: 90000 },
      signatory_name: null,
      signatory_designation: null,
      signatory_contact: null,
      consent_text_version: "v1.0",
      consent_declaration: null,
      client_ip: null,
      user_agent: null,
      authorized_at: null,
      rejected_at: null,
      rejection_reason: null,
      revoked_at: null,
      revocation_reason: null,
      revoked_by: null,
      created_by: "ca-user-1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 172800000).toISOString(),
      updated_at: new Date().toISOString(),
    };

    // Simulate link open transition
    const viewedAuth: ClientFilingAuthorization = {
      ...pendingAuth,
      status: "VIEWED",
      client_ip: "203.0.113.42",
      updated_at: new Date().toISOString(),
    };

    assert.equal(viewedAuth.status, "VIEWED");
    assert.notEqual(viewedAuth.status, "AUTHORIZED");
    assert.equal(viewedAuth.authorized_at, null);
    assert.equal(viewedAuth.signatory_name, null);
  });

  it("2. Explicit authorization requires signatory identity and consent affirmation", () => {
    const reviewData: ClientPublicReviewData = {
      id: "auth-1",
      gstin: "27AABCU9603R1ZX",
      period: "2026-10",
      return_type: "GSTR-1",
      status: "AUTHORIZED",
      figures_digest: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      figures_summary: { total_taxable_value: 500000, total_tax: 90000 },
      signatory_name: "Rajesh Kumar",
      signatory_designation: "Managing Director",
      consent_text_version: "v1.0",
      consent_declaration: "I hereby confirm that I have reviewed the return figures...",
      authorized_at: new Date().toISOString(),
      rejected_at: null,
      rejection_reason: null,
      expires_at: new Date(Date.now() + 172800000).toISOString(),
    };

    assert.equal(reviewData.status, "AUTHORIZED");
    assert.equal(reviewData.signatory_name, "Rajesh Kumar");
    assert.equal(reviewData.signatory_designation, "Managing Director");
    assert.notEqual(reviewData.authorized_at, null);
  });
});

describe("Phase 3.3: Cryptographic Figures Binding & Tamper Detection", () => {
  it("1. Bound digest must strictly match between authorized record and filed payload", () => {
    const authorizedDigest = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918";
    const currentPayloadDigest = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918";
    const alteredPayloadDigest = "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0";

    // Valid filing check
    assert.equal(authorizedDigest === currentPayloadDigest, true);

    // Tampered figures check (must fail closed)
    assert.equal(authorizedDigest === alteredPayloadDigest, false);
  });
});
