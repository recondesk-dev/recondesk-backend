"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  OFFSET_HOLD_MS,
  type OffsetConfirmSteps,
  canStartHold,
  formatInr,
  isHoldComplete,
  typedCashMatchesExpected,
} from "@/components/filing/gstr3b/offsetConfirmLogic";

type Props = {
  expectedCashTotal: number;
  itcTotal: number;
  periodLabel: string;
  steps: OffsetConfirmSteps;
  onStepsChange: (next: OffsetConfirmSteps) => void;
  /** Fired only after step1+2 satisfied and hold completes. */
  onCommit: () => void;
  disabled?: boolean;
  busy?: boolean;
};

/**
 * Three-step deliberate confirm — not a normal primary button.
 * Parent owns step state so stale resets can clear all three at once.
 */
export function OffsetDeliberateConfirm({
  expectedCashTotal,
  itcTotal,
  periodLabel,
  steps,
  onStepsChange,
  onCommit,
  disabled,
  busy,
}: Props) {
  const [holding, setHolding] = useState(false);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);
  const committedRef = useRef(false);

  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  const stopHold = useCallback(() => {
    setHolding(false);
    startRef.current = null;
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (!committedRef.current) {
      onStepsChange({ ...stepsRef.current, holdProgressMs: 0 });
    }
  }, [onStepsChange]);

  const tick = useCallback(() => {
    if (startRef.current == null) return;
    const elapsed = performance.now() - startRef.current;
    const next = {
      ...stepsRef.current,
      holdProgressMs: Math.min(elapsed, OFFSET_HOLD_MS),
    };
    onStepsChange(next);
    stepsRef.current = next;
    if (elapsed >= OFFSET_HOLD_MS) {
      if (!committedRef.current) {
        committedRef.current = true;
        setHolding(false);
        onCommit();
      }
      return;
    }
    rafRef.current = requestAnimationFrame(tick);
  }, [onCommit, onStepsChange]);

  const beginHold = useCallback(() => {
    if (disabled || busy) return;
    if (!canStartHold(stepsRef.current, expectedCashTotal)) return;
    committedRef.current = false;
    setHolding(true);
    startRef.current = performance.now();
    rafRef.current = requestAnimationFrame(tick);
  }, [busy, disabled, expectedCashTotal, tick]);

  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // If parent resets steps (stale), drop any in-flight hold.
  useEffect(() => {
    if (
      !steps.reviewed &&
      !steps.typedCashTotal &&
      steps.holdProgressMs === 0 &&
      holding
    ) {
      stopHold();
      committedRef.current = false;
    }
  }, [holding, steps, stopHold]);

  const typedOk = typedCashMatchesExpected(
    steps.typedCashTotal,
    expectedCashTotal
  );
  const holdReady = canStartHold(steps, expectedCashTotal);
  const progress = Math.min(1, steps.holdProgressMs / OFFSET_HOLD_MS);

  return (
    <div className="space-y-6 border-t border-[#3A3630] pt-6">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#A89F90]">
          Step 1 of 3 — Review
        </p>
        <label className="mt-3 flex cursor-pointer items-start gap-3 text-[13px] text-[#E8E4DC]">
          <input
            type="checkbox"
            checked={steps.reviewed}
            disabled={disabled || busy}
            onChange={(e) =>
              onStepsChange({
                ...steps,
                reviewed: e.target.checked,
                holdProgressMs: 0,
              })
            }
            className="mt-1 h-4 w-4 accent-[#C4B59A]"
          />
          <span>
            I have verified every pdcash / pditc line above against the books
            for {periodLabel}.
          </span>
        </label>
      </div>

      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#A89F90]">
          Step 2 of 3 — Type cash outflow to unlock
        </p>
        <p className="mt-1 text-[12px] text-[#A89F90]">
          Type the total cash tax heads (sum of ipd+cpd+spd+cspd):{" "}
          <span className="font-mono text-[#E8E4DC]">
            {formatInr(expectedCashTotal)}
          </span>
        </p>
        <input
          type="text"
          inputMode="decimal"
          autoComplete="off"
          disabled={disabled || busy || !steps.reviewed}
          value={steps.typedCashTotal}
          onChange={(e) =>
            onStepsChange({
              ...steps,
              typedCashTotal: e.target.value,
              holdProgressMs: 0,
            })
          }
          placeholder="Type the amount"
          className="mt-3 h-11 w-full max-w-sm rounded border border-[#3A3630] bg-[#0E0C0A] px-3 font-mono text-[14px] text-[#E8E4DC] outline-none focus:border-[#C4B59A] disabled:opacity-40"
        />
        {steps.typedCashTotal && !typedOk ? (
          <p className="mt-2 text-[12px] text-[#E8A060]">
            Amount does not match the cash outflow above.
          </p>
        ) : null}
        {typedOk ? (
          <p className="mt-2 text-[12px] text-[#8ABA8A]">
            Cash total matches. ITC utilisation this offset:{" "}
            {formatInr(itcTotal)}.
          </p>
        ) : null}
      </div>

      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#A89F90]">
          Step 3 of 3 — Hold to commit
        </p>
        <p className="mt-1 text-[12px] text-[#A89F90]">
          Press and hold. Release cancels. There is no single-click Offset
          button.
        </p>
        <button
          type="button"
          disabled={disabled || busy || !holdReady}
          onMouseDown={(e) => {
            e.preventDefault();
            beginHold();
          }}
          onMouseUp={stopHold}
          onMouseLeave={stopHold}
          onTouchStart={(e) => {
            e.preventDefault();
            beginHold();
          }}
          onTouchEnd={stopHold}
          onTouchCancel={stopHold}
          className="relative mt-3 h-14 w-full max-w-md overflow-hidden rounded border border-[#6B5A3A] bg-[#1A160F] text-[13px] font-semibold text-[#E8E4DC] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <span
            className="absolute inset-y-0 left-0 bg-[#5A4A28] transition-[width] duration-75"
            style={{ width: `${progress * 100}%` }}
            aria-hidden
          />
          <span className="relative z-10">
            {busy
              ? "Submitting Offset…"
              : holding || isHoldComplete(steps)
                ? `Hold… ${Math.round(progress * 100)}%`
                : `Hold to offset ${formatInr(expectedCashTotal)} cash + ${formatInr(itcTotal)} ITC`}
          </span>
        </button>
      </div>
    </div>
  );
}
