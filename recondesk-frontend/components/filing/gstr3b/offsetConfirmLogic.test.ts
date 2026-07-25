/**
 * Pure-logic tests for Offset deliberate confirmation.
 * Run: npx --yes tsx --test components/filing/gstr3b/offsetConfirmLogic.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EMPTY_OFFSET_CONFIRM_STEPS,
  canStartHold,
  parseTypedCashTotal,
  resetOffsetConfirmSteps,
  sumPdcashTaxOutflow,
  sumPditcItc,
  typedCashMatchesExpected,
} from "./offsetConfirmLogic";

describe("sumPdcashTaxOutflow", () => {
  it("sums ipd+cpd+spd+cspd across rows", () => {
    const total = sumPdcashTaxOutflow([
      { ipd: 100, cpd: 20, spd: 20, cspd: 0 },
      { ipd: 0, cpd: 5, spd: 5, cspd: 1 },
    ]);
    assert.equal(total, 151);
  });
});

describe("typedCashMatchesExpected", () => {
  it("accepts commas and rupee sign", () => {
    assert.equal(parseTypedCashTotal("₹1,10,000"), 110000);
    assert.equal(typedCashMatchesExpected("1,10,000", 110000), true);
    assert.equal(typedCashMatchesExpected("109999", 110000), false);
  });
});

describe("deliberate steps / stale reset", () => {
  it("canStartHold requires review + matching typed total", () => {
    assert.equal(
      canStartHold(
        { reviewed: false, typedCashTotal: "100", holdProgressMs: 0 },
        100
      ),
      false
    );
    assert.equal(
      canStartHold(
        { reviewed: true, typedCashTotal: "100", holdProgressMs: 0 },
        100
      ),
      true
    );
  });

  it("resetOffsetConfirmSteps clears all three steps (stale path)", () => {
    const mid = {
      reviewed: true,
      typedCashTotal: "50000",
      holdProgressMs: 1800,
    };
    const reset = resetOffsetConfirmSteps();
    assert.deepEqual(reset, EMPTY_OFFSET_CONFIRM_STEPS);
    assert.equal(reset.reviewed, false);
    assert.equal(reset.typedCashTotal, "");
    assert.equal(reset.holdProgressMs, 0);
    assert.notDeepEqual(reset, mid);
  });
});

describe("sumPditcItc", () => {
  it("sums ITC utilisation fields", () => {
    assert.equal(
      sumPditcItc({
        i_pdi: 40,
        i_pdc: 10,
        i_pds: 10,
        c_pdi: 0,
        c_pdc: 5,
        s_pdi: 0,
        s_pds: 5,
        cs_pdcs: 0,
      }),
      70
    );
  });
});
