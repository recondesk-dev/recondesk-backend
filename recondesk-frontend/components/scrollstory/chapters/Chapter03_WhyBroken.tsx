"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";

// ─── Helper ───────────────────────────────────────────────────────────────────

function mapRange(
  value: number,
  inMin: number,
  inMax: number,
  outMin: number,
  outMax: number
): number {
  return Math.min(
    Math.max(
      ((value - inMin) / (inMax - inMin)) * (outMax - outMin) + outMin,
      outMin
    ),
    outMax
  );
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props {
  scrollProgress: number;
}

type LineType = "match" | "missing" | "mismatch";

interface LineConfig {
  threshold: number;
  type: LineType;
  leftRow: number;
  rightRow: number | null;
  color: string;
  cardIndex: number;
}

interface RowData {
  invoice: string;
  gstin: string;
  amount: string;
  isMissing?: boolean;
  isMismatch?: boolean;
}

// ─── Row Data ─────────────────────────────────────────────────────────────────

const GSTR2B_ROWS: RowData[] = [
  { invoice: "INV-441",  gstin: "27AABCS...A1Z5", amount: "₹84,320"   },
  { invoice: "INV-089",  gstin: "29AABCT...B2Z3", amount: "₹1,24,500" },
  { invoice: "INV-1092", gstin: "27AABCU...C3Z1", amount: "₹67,800"   },
  { invoice: "INV-203",  gstin: "27AABCW...E5Z7", amount: "₹98,750"   },
  { invoice: "INV-156",  gstin: "33AABCX...F6Z5", amount: "₹1,56,400" },
  { invoice: "INV-889",  gstin: "27AABCY...G7Z3", amount: "₹43,200"   },
];

const PR_ROWS: RowData[] = [
  { invoice: "PUR-441",  gstin: "27AABCS...A1Z5", amount: "₹84,320"   },
  { invoice: "PUR-089",  gstin: "29AABCT...B2Z3", amount: "₹1,24,500" },
  { invoice: "—",        gstin: "—",               amount: "—",         isMissing: true  },
  { invoice: "PUR-203",  gstin: "27AABCW...E5Z7",  amount: "₹95,200", isMismatch: true },
  { invoice: "—",        gstin: "—",               amount: "—",         isMissing: true  },
  { invoice: "PUR-889",  gstin: "27AABCY...G7Z3", amount: "₹43,200"   },
];

// ─── Line Configs ─────────────────────────────────────────────────────────────

const LINE_CONFIGS: LineConfig[] = [
  { threshold: 0.20, type: "match",    leftRow: 0, rightRow: 0,    color: "#16a34a", cardIndex: 0 },
  { threshold: 0.28, type: "match",    leftRow: 1, rightRow: 1,    color: "#16a34a", cardIndex: 0 },
  { threshold: 0.36, type: "missing",  leftRow: 2, rightRow: null, color: "#ef4444", cardIndex: 1 },
  { threshold: 0.44, type: "mismatch", leftRow: 3, rightRow: 3,    color: "#f97316", cardIndex: 2 },
  { threshold: 0.52, type: "missing",  leftRow: 4, rightRow: null, color: "#ef4444", cardIndex: 3 },
  { threshold: 0.60, type: "match",    leftRow: 5, rightRow: 5,    color: "#16a34a", cardIndex: 0 },
];

// ─── Explanation Cards ────────────────────────────────────────────────────────

const EXPLANATION_CARDS = [
  {
    text: "Same invoice, same amount. This is the easy case.",
    color: "#16a34a",
  },
  {
    text: "This invoice exists in GSTR-2B — your supplier filed it.\nBut it\u2019s not in your client\u2019s books. Did they miss recording it?\nOr did the supplier file incorrectly?",
    color: "#ef4444",
  },
  {
    text: "Invoice exists on both sides — but amounts differ by \u20b93,550.\nRounding error? Credit note not recorded? You have to find out.",
    color: "#f97316",
  },
  {
    text: "This one is in your books but missing from GSTR-2B entirely.\nYour supplier hasn\u2019t filed their GSTR-1 yet.\nYou can\u2019t claim this ITC until they do.",
    color: "#ef4444",
  },
];

// Mobile status pills — one per GSTR-2B row
const MOBILE_STATUS: { label: string; color: string }[] = [
  { label: "✅ Matched",          color: "#22c55e" },
  { label: "✅ Matched",          color: "#22c55e" },
  { label: "⚠\uFE0F Not in books",  color: "#ef4444" },
  { label: "⚠\uFE0F Amt mismatch", color: "#f97316" },
  { label: "⚠\uFE0F Not in GSTR-2B", color: "#ef4444" },
  { label: "✅ Matched",          color: "#22c55e" },
];

// ─── SVG Geometry ─────────────────────────────────────────────────────────────
// These constants must match the rendered column layout precisely.

const HEADER_H = 64; // column header (pill + subtitle)
const ROW_H    = 44; // each invoice row height
const ROW_GAP  = 8;  // gap between rows
const ROW_STEP = ROW_H + ROW_GAP;   // 52px
const GAP_W    = 48; // horizontal gap between the two columns
const SVG_H    = HEADER_H + GSTR2B_ROWS.length * ROW_STEP + 24;

/** Y-center of row i within the SVG / column coordinate space */
function rowCenterY(i: number): number {
  return HEADER_H + i * ROW_STEP + ROW_H / 2;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ColumnHeader({
  label,
  sublabel,
  pillBg,
  pillColor,
}: {
  label: string;
  sublabel: string;
  pillBg: string;
  pillColor: string;
}) {
  return (
    <div
      style={{
        height: HEADER_H,
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-start",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          display: "inline-block",
          alignSelf: "flex-start",
          background: pillBg,
          color: pillColor,
          fontFamily: "var(--font-jetbrains-mono, monospace)",
          fontSize: "0.7rem",
          fontWeight: 600,
          letterSpacing: "0.08em",
          padding: "4px 10px",
          borderRadius: 4,
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      <p
        style={{
          margin: "8px 0 0",
          fontFamily: "var(--font-inter, Inter, sans-serif)",
          fontSize: "0.78rem",
          color: "#6b7280",
          lineHeight: 1.4,
        }}
      >
        {sublabel}
      </p>
    </div>
  );
}

interface InvoiceRowProps {
  row: RowData;
  mobileStatus?: { label: string; color: string };
  showMobileStatus?: boolean;
}

function InvoiceRow({ row, mobileStatus, showMobileStatus }: InvoiceRowProps) {
  const MONO: CSSProperties = {
    fontFamily: "var(--font-jetbrains-mono, monospace)",
    fontSize: "0.72rem",
  };

  if (row.isMissing) {
    return (
      <div
        style={{
          height: ROW_H,
          border: "1px dashed #2a2a2a",
          borderRadius: 6,
          background: "#0f0f0f",
          padding: "0 12px",
          display: "flex",
          alignItems: "center",
          gap: 8,
          boxSizing: "border-box",
          flexShrink: 0,
        }}
      >
        <span style={{ ...MONO, color: "#3a3a3a", flex: 1 }}>—</span>
        <span
          style={{
            ...MONO,
            fontSize: "0.62rem",
            background: "rgba(239,68,68,0.1)",
            color: "#ef4444",
            padding: "2px 6px",
            borderRadius: 3,
            whiteSpace: "nowrap",
          }}
        >
          NOT IN BOOKS
        </span>
      </div>
    );
  }

  return (
    <div
      style={{
        height: ROW_H,
        background: "#111111",
        border: "1px solid #2a2a2a",
        borderRadius: 6,
        padding: "0 12px",
        display: "flex",
        alignItems: "center",
        gap: 8,
        boxSizing: "border-box",
        flexShrink: 0,
        minWidth: 0,
      }}
    >
      <span style={{ ...MONO, color: "#9ca3af", flexShrink: 0 }}>
        {row.invoice}
      </span>
      <span
        style={{
          ...MONO,
          color: "#555",
          flex: 1,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {row.gstin}
      </span>
      <span
        style={{
          ...MONO,
          color: row.isMismatch ? "#ef4444" : "#9ca3af",
          flexShrink: 0,
        }}
      >
        {row.amount}
      </span>
      {showMobileStatus && mobileStatus && (
        <span
          style={{
            ...MONO,
            fontSize: "0.6rem",
            color: mobileStatus.color,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          {mobileStatus.label}
        </span>
      )}
    </div>
  );
}

// ─── Chapter ──────────────────────────────────────────────────────────────────

/**
 * Chapter 03 — Why It's Broken
 *
 * Phase 1  (0.00 – 0.15): "The problem isn't your process. / The problem is structural."
 * Phase 2  (0.15 – 0.80): Two-column GSTR-2B vs Purchase Register,
 *                          SVG bezier connection lines drawing in one by one,
 *                          contextual explanation card cycling below
 * Phase 3  (0.80 – 1.00): Structural text explanation, 4 lines staggered
 *
 * SVG lines: rendered in the 48px gap between columns, absolutely positioned.
 * Each line uses stroke-dashoffset transition triggered on threshold crossing.
 * Missing-row lines draw halfway then show an "×" glyph at midpoint.
 */
export function Chapter03_WhyBroken({ scrollProgress: sp }: Props) {
  // ── State ──────────────────────────────────────────────────────────────────
  const [isMobile, setIsMobile] = useState(false);
  const [unlockedLines, setUnlockedLines] = useState<Set<number>>(new Set());

  useEffect(() => {
    const update = () => setIsMobile(window.innerWidth < 768);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // One-way unlock: once a line's threshold is crossed, it stays visible
  useEffect(() => {
    setUnlockedLines((prev) => {
      const next = new Set(prev);
      LINE_CONFIGS.forEach((lc, i) => {
        if (sp >= lc.threshold) next.add(i);
      });
      // Sets are compared by reference in React — only update if changed
      if (next.size === prev.size) return prev;
      return next;
    });
  }, [sp]);

  // Active explanation card: last unlocked line's cardIndex
  let activeCardIndex = -1;
  for (let i = LINE_CONFIGS.length - 1; i >= 0; i--) {
    if (unlockedLines.has(i)) {
      activeCardIndex = LINE_CONFIGS[i].cardIndex;
      break;
    }
  }

  // ── Phase opacities ────────────────────────────────────────────────────────

  // Phase 1
  const p1Opacity =
    sp < 0.12
      ? mapRange(sp, 0.0, 0.07, 0, 1)
      : mapRange(sp, 0.12, 0.17, 1, 0);
  const p1L2Opacity = mapRange(sp, 0.08, 0.13, 0, 1);

  // Phase 2 (two-column)
  const p2Opacity =
    sp < 0.78
      ? mapRange(sp, 0.15, 0.23, 0, 1)
      : mapRange(sp, 0.78, 0.86, 1, 0);

  // Phase 3 (structural text)
  const p3Opacity  = mapRange(sp, 0.80, 0.87, 0, 1);
  const p3L1Opacity = mapRange(sp, 0.82, 0.88, 0, 1);
  const p3L2Opacity = mapRange(sp, 0.87, 0.92, 0, 1);
  const p3L3Opacity = mapRange(sp, 0.92, 0.97, 0, 1);
  const p3L4Opacity = mapRange(sp, 0.97, 1.00, 0, 1);

  // ── Shared style shorthands ────────────────────────────────────────────────
  const INTER: CSSProperties = {
    fontFamily: "var(--font-inter, Inter, sans-serif)",
  };

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <StickyScene background="#0a0a0a">
      <div
        style={{
          position: "relative",
          width: "100%",
          height: "100%",
          overflow: "hidden",
        }}
      >

        {/* ── PHASE 1: Opening statement ──────────────────────────────────── */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "0 24px",
            textAlign: "center",
            opacity: p1Opacity,
            pointerEvents: "none",
          }}
          aria-hidden={p1Opacity < 0.05}
        >
          <p
            style={{
              ...INTER,
              fontSize: "clamp(1.3rem, 3.5vw, 2.2rem)",
              fontWeight: 300,
              color: "#f0f0f0",
              margin: 0,
              lineHeight: 1.35,
            }}
          >
            The problem isn&rsquo;t your process.
          </p>
          <p
            style={{
              ...INTER,
              fontSize: "clamp(1.3rem, 3.5vw, 2.2rem)",
              fontWeight: 600,
              color: "#ef4444",
              margin: "14px 0 0",
              lineHeight: 1.35,
              opacity: p1L2Opacity,
            }}
          >
            The problem is structural.
          </p>
        </div>

        {/* ── PHASE 2: Two-column comparison ──────────────────────────────── */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            opacity: p2Opacity,
            padding: isMobile ? "16px" : "16px 24px",
            overflow: "hidden",
            pointerEvents: p2Opacity < 0.05 ? "none" : "auto",
          }}
          aria-hidden={p2Opacity < 0.05}
        >
          {/* ── Columns container ─────────────────────────────────────────── */}
          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              gap: isMobile ? 14 : GAP_W,
              maxWidth: 900,
              width: "100%",
              position: "relative",  // SVG positioned within this
              flexShrink: 0,
            }}
          >
            {/* ── Left column: GSTR-2B ─────────────────────────────────── */}
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                gap: ROW_GAP,
                minWidth: 0,
              }}
            >
              <ColumnHeader
                label="GSTR-2B / GST Portal"
                sublabel="Generated from your suppliers' filings"
                pillBg="#1e3a5f"
                pillColor="#3b82f6"
              />
              {GSTR2B_ROWS.map((row, i) => (
                <InvoiceRow
                  key={i}
                  row={row}
                  mobileStatus={MOBILE_STATUS[i]}
                  showMobileStatus={isMobile}
                />
              ))}
            </div>

            {/* ── SVG connection lines (desktop only) ──────────────────── */}
            {!isMobile && (
              <svg
                width={GAP_W}
                height={SVG_H}
                viewBox={`0 0 ${GAP_W} ${SVG_H}`}
                style={{
                  position: "absolute",
                  /* Sits exactly in the 48px gap between the two equal flex columns */
                  left: `calc(50% - ${GAP_W / 2}px)`,
                  top: 0,
                  pointerEvents: "none",
                  zIndex: 10,
                  overflow: "visible",
                }}
                aria-hidden="true"
              >
                {LINE_CONFIGS.map((lc, i) => {
                  const y = rowCenterY(lc.leftRow);
                  const isMissingLine = lc.type === "missing";
                  /*
                   * Full line: M 0,y Q midX,y-4 48,y (quadratic bezier, gentle curve)
                   * Half line: M 0,y Q 12,y-3 24,y (draws to midpoint, ✕ shown there)
                   * approxLen: dasharray value that covers the path length
                   */
                  const endX   = isMissingLine ? GAP_W / 2 : GAP_W;
                  const cpX    = isMissingLine ? GAP_W / 4 : GAP_W / 2;
                  const cpY    = y - 4;
                  const pathD  = `M 0,${y} Q ${cpX},${cpY} ${endX},${y}`;
                  const approxLen = isMissingLine ? 26 : 52;
                  const unlocked  = unlockedLines.has(i);

                  return (
                    <g key={i}>
                      {/* Connection line */}
                      <path
                        d={pathD}
                        stroke={lc.color}
                        strokeWidth={1.5}
                        fill="none"
                        strokeLinecap="round"
                        strokeDasharray={approxLen}
                        strokeDashoffset={unlocked ? 0 : approxLen}
                        style={{
                          transition: unlocked
                            ? "stroke-dashoffset 0.55s ease-out"
                            : "none",
                        }}
                      />
                      {/* ✕ glyph at midpoint for missing-row lines */}
                      {isMissingLine && (
                        <text
                          x={endX}
                          y={y + 4}
                          fill={lc.color}
                          fontSize={10}
                          textAnchor="middle"
                          fontFamily="monospace"
                          style={{
                            opacity: unlocked ? 1 : 0,
                            /* Slight delay so glyph appears after line finishes drawing */
                            transition: unlocked
                              ? "opacity 0.15s ease 0.5s"
                              : "none",
                          }}
                        >
                          ×
                        </text>
                      )}
                    </g>
                  );
                })}
              </svg>
            )}

            {/* ── Right column: Purchase Register ──────────────────────── */}
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                gap: ROW_GAP,
                minWidth: 0,
              }}
            >
              <ColumnHeader
                label="Purchase Register / Your Books"
                sublabel="Recorded from your client's accounting software"
                pillBg="#3b1f1f"
                pillColor="#f97316"
              />
              {PR_ROWS.map((row, i) => (
                <InvoiceRow key={i} row={row} />
              ))}
            </div>
          </div>

          {/* ── Explanation card ─────────────────────────────────────────── */}
          {/*
           * Container has a fixed height so all 4 cards (position:absolute)
           * can cycle over each other cleanly via opacity transitions.
           */}
          <div
            style={{
              marginTop: 18,
              maxWidth: isMobile ? "90vw" : 520,
              width: "100%",
              position: "relative",
              height: 120,
              flexShrink: 0,
              opacity: activeCardIndex >= 0 && sp < 0.77 ? 1 : 0,
              transition: "opacity 300ms ease",
            }}
            aria-live="polite"
          >
            {EXPLANATION_CARDS.map((card, i) => (
              <div
                key={i}
                style={{
                  position: "absolute",
                  inset: 0,
                  background: "#111111",
                  border: "1px solid #2a2a2a",
                  borderRadius: 8,
                  padding: "14px 18px",
                  opacity: i === activeCardIndex ? 1 : 0,
                  transition: "opacity 300ms ease",
                  pointerEvents: i === activeCardIndex ? "auto" : "none",
                  overflow: "hidden",
                }}
              >
                <p
                  style={{
                    ...INTER,
                    fontSize: "0.82rem",
                    color: "#9ca3af",
                    lineHeight: 1.7,
                    margin: 0,
                    whiteSpace: "pre-line",
                  }}
                >
                  {card.text}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* ── PHASE 3: Structural explanation ─────────────────────────────── */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            opacity: p3Opacity,
            pointerEvents: "none",
          }}
          aria-hidden={p3Opacity < 0.05}
        >
          {/* Centered text block, left-aligned text within it */}
          <div
            style={{
              maxWidth: 600,
              width: "100%",
              padding: isMobile ? "0 20px" : "0 24px",
            }}
          >
            {/* Line 1 */}
            <p
              style={{
                ...INTER,
                fontSize: "clamp(0.85rem, 1.5vw, 1rem)",
                color: "#9ca3af",
                margin: 0,
                lineHeight: 1.65,
                opacity: p3L1Opacity,
              }}
            >
              GSTR-2B is built from your suppliers&rsquo; behaviour.
            </p>

            {/* Line 2 */}
            <p
              style={{
                ...INTER,
                fontSize: "clamp(0.85rem, 1.5vw, 1rem)",
                color: "#9ca3af",
                margin: "8px 0 0",
                lineHeight: 1.65,
                opacity: p3L2Opacity,
              }}
            >
              Your purchase register is built from your client&rsquo;s behaviour.
            </p>

            {/* Line 3 — larger */}
            <p
              style={{
                ...INTER,
                fontSize: "clamp(1rem, 2vw, 1.3rem)",
                fontWeight: 300,
                color: "#f0f0f0",
                margin: "24px 0 0",
                lineHeight: 1.55,
                opacity: p3L3Opacity,
              }}
            >
              These two datasets have different owners,
              different systems, and different filing dates.
            </p>

            {/* Line 4 — red, emphatic */}
            <p
              style={{
                ...INTER,
                fontSize: "clamp(0.9rem, 1.8vw, 1.1rem)",
                fontWeight: 500,
                color: "#ef4444",
                margin: "20px 0 0",
                lineHeight: 1.55,
                opacity: p3L4Opacity,
              }}
            >
              Every mismatch is a decision you have to make manually.
            </p>
          </div>
        </div>

      </div>
    </StickyScene>
  );
}
