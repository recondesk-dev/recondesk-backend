import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  calculateStatutoryDeadlines,
  evaluatePeriodCompliance,
  calculateNetClaimableItc,
  toIST,
} from "./statutoryCompliance";

describe("Statutory GST Compliance Domain Logic", () => {
  it("1. Correctly identifies OUTWARD_FILING phase on or before 11th", () => {
    // 5th September 2026
    const ref = new Date("2026-09-05T10:00:00Z");
    const status = calculateStatutoryDeadlines(ref);

    assert.equal(status.phase, "OUTWARD_FILING");
    assert.equal(status.accentColor, "amber");

    const gstr1 = status.deadlines.find((d) => d.kind === "GSTR-1");
    assert.ok(gstr1);
    assert.equal(gstr1.daysRemaining >= 5, true);

    const gstr3b = status.deadlines.find((d) => d.kind === "GSTR-3B");
    assert.ok(gstr3b);
    assert.equal(gstr3b.daysRemaining >= 14, true);
  });

  it("2. Correctly identifies GSTR2B_BUFFER phase between 12th and 13th", () => {
    // 12th September 2026
    const ref = new Date("2026-09-12T10:00:00Z");
    const status = calculateStatutoryDeadlines(ref);

    assert.equal(status.phase, "GSTR2B_BUFFER");
    assert.equal(status.accentColor, "indigo");

    const gstr2b = status.deadlines.find((d) => d.kind === "GSTR-2B");
    assert.ok(gstr2b);
    assert.equal(gstr2b.daysRemaining <= 2, true);
  });

  it("3. Correctly identifies RECON_GOLDEN_WINDOW between 14th and 20th", () => {
    // 16th September 2026
    const ref = new Date("2026-09-16T10:00:00Z");
    const status = calculateStatutoryDeadlines(ref);

    assert.equal(status.phase, "RECON_GOLDEN_WINDOW");
    assert.equal(status.accentColor, "emerald");

    const gstr3b = status.deadlines.find((d) => d.kind === "GSTR-3B");
    assert.ok(gstr3b);
    assert.equal(gstr3b.daysRemaining <= 4, true);
  });

  it("4. Correctly rolls over to next month's deadlines when currentDay > 20th", () => {
    // 25th September 2026
    const ref = new Date("2026-09-25T10:00:00Z");
    const status = calculateStatutoryDeadlines(ref);

    assert.equal(status.phase, "POST_FILING_AUDIT");

    const gstr1 = status.deadlines.find((d) => d.kind === "GSTR-1");
    assert.ok(gstr1);
    // Next GSTR-1 is 11 Oct 2026
    assert.equal(gstr1.targetDateFormatted.includes("Oct"), true);

    const gstr3b = status.deadlines.find((d) => d.kind === "GSTR-3B");
    assert.ok(gstr3b);
    // Next GSTR-3B is 20 Oct 2026
    assert.equal(gstr3b.targetDateFormatted.includes("Oct"), true);
  });

  it("5. Evaluates period compliance: locked on time vs overdue draft", () => {
    // Period: 2026-08 (filing was due 20 Sep 2026)
    // Ref: 25 Sep 2026 (past 20th deadline)
    const ref = new Date("2026-09-25T10:00:00Z");

    // Case A: Locked on time (e.g. 15 Sep 2026)
    const lockedOnTime = evaluatePeriodCompliance(
      "2026-08",
      true,
      "2026-09-15T12:00:00Z",
      ref
    );
    assert.equal(lockedOnTime.status, "COMPLIANT_ON_TIME");
    assert.equal(lockedOnTime.isLocked, true);

    // Case B: Not locked and past deadline
    const overdueDraft = evaluatePeriodCompliance("2026-08", false, null, ref);
    assert.equal(overdueDraft.status, "OVERDUE");
    assert.equal(overdueDraft.isLocked, false);

    // Case C: Future period (2026-09, filing due 20 Oct 2026)
    const futureDraft = evaluatePeriodCompliance("2026-09", false, null, ref);
    assert.equal(futureDraft.status, "PENDING_ON_TRACK");
  });

  it("6. Correctly computes net claimable ITC and risk rating", () => {
    const calc = calculateNetClaimableItc({
      eligible_itc: 100000,
      reversed_itc: 15000,
      reclaimed_itc: 5000,
      on_hold_itc: 10000,
      at_risk_itc: 5000,
      missed_itc: 2000,
    });

    // Net = 100,000 - 15,000 + 5,000 = 90,000
    assert.equal(calc.netClaimableRupees, 90000);
    assert.equal(calc.netClaimablePaise, 9000000);
    assert.equal(calc.healthRating, "MODERATE_RISK"); // because at_risk > 0
  });

  it("7. Flags high audit risk when at-risk exceeds 20% of claim", () => {
    const calc = calculateNetClaimableItc({
      eligible_itc: 100000,
      reversed_itc: 5000,
      reclaimed_itc: 0,
      at_risk_itc: 25000, // 25% of eligible
    });

    assert.equal(calc.healthRating, "HIGH_RISK");
  });
});
