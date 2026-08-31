"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props {
  scrollProgress: number;
}

interface Step {
  icon: string;
  stepLabel: string;
  title: string;
  description: string;
  tag: string;
  time: string;
  /** Step 8 gets red accent treatment */
  accentRed?: boolean;
}

type RowStatus = "matched" | "missing-books" | "missing-2b" | "mismatch";

interface SheetRow {
  gstin: string;
  invoice: string;
  date: string;
  gstr2bAmt: string;
  booksAmt: string;
  status: RowStatus;
}

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

// ─── Step Data ────────────────────────────────────────────────────────────────

const STEPS: Step[] = [
  {
    icon: "📥",
    stepLabel: "STEP 01",
    title: "Download GSTR-2B",
    description:
      "Log into GST portal. Navigate to returns. Download JSON for each client separately.",
    tag: "GST Portal",
    time: "~15 min per client",
  },
  {
    icon: "📊",
    stepLabel: "STEP 02",
    title: "Export Purchase Register",
    description:
      "Open Tally or accounting software. Export purchase register for the same period. Save as Excel.",
    tag: "Tally / ERP",
    time: "~10 min per client",
  },
  {
    icon: "📂",
    stepLabel: "STEP 03",
    title: "Open Excel",
    description:
      "Create a new workbook. Paste GSTR-2B data in Sheet 1. Paste purchase register in Sheet 2.",
    tag: "Microsoft Excel",
    time: "~10 min per client",
  },
  {
    icon: "🔍",
    stepLabel: "STEP 04",
    title: "Match Line by Line",
    description:
      "Use VLOOKUP or manual comparison. Match each invoice by GSTIN, invoice number, date, and amount.",
    tag: "Manual Matching",
    time: "~45 min per client",
  },
  {
    icon: "🚩",
    stepLabel: "STEP 05",
    title: "Flag Mismatches",
    description:
      "Highlight unmatched rows in red. Invoices missing from GSTR-2B. Invoices in GSTR-2B not in your books.",
    tag: "Manual Review",
    time: "~20 min per client",
  },
  {
    icon: "📞",
    stepLabel: "STEP 06",
    title: "Chase Suppliers",
    description:
      "Call or WhatsApp suppliers whose invoices are missing. Ask them to file their GSTR-1. Wait.",
    tag: "Follow-ups",
    time: "~30 min per client",
  },
  {
    icon: "⚖️",
    stepLabel: "STEP 07",
    title: "Decide on Unmatched ITC",
    description:
      "Determine which unmatched ITC to claim provisionally. Document reasoning. Flag risk for client.",
    tag: "ITC Decision",
    time: "~20 min per client",
  },
  {
    icon: "🔁",
    stepLabel: "STEP 08",
    title: "Repeat for Every Client",
    description:
      "Go back to step 1. New client. Same process. 40 clients means 40 full cycles this month.",
    tag: "×40 clients",
    time: "~2.5 hrs per client",
    accentRed: true,
  },
];

// ─── Spreadsheet Data ─────────────────────────────────────────────────────────

const SHEET_ROWS: SheetRow[] = [
  {
    gstin: "27AABCS1234A1Z5",
    invoice: "INV-2024-441",
    date: "03-Oct",
    gstr2bAmt: "₹84,320",
    booksAmt: "₹84,320",
    status: "matched",
  },
  {
    gstin: "29AABCT5678B2Z3",
    invoice: "INV-OCT-089",
    date: "07-Oct",
    gstr2bAmt: "₹1,24,500",
    booksAmt: "₹1,24,500",
    status: "matched",
  },
  {
    gstin: "27AABCU9012C3Z1",
    invoice: "INV-1092",
    date: "09-Oct",
    gstr2bAmt: "₹67,800",
    booksAmt: "—",
    status: "missing-books",
  },
  {
    gstin: "24AABCV3456D4Z9",
    invoice: "PUR-441",
    date: "12-Oct",
    gstr2bAmt: "—",
    booksAmt: "₹2,31,000",
    status: "missing-2b",
  },
  {
    gstin: "27AABCW7890E5Z7",
    invoice: "INV-2024-203",
    date: "15-Oct",
    gstr2bAmt: "₹98,750",
    booksAmt: "₹95,200",
    status: "mismatch",
  },
  {
    gstin: "33AABCX2345F6Z5",
    invoice: "TAX-OCT-17",
    date: "18-Oct",
    gstr2bAmt: "₹1,56,400",
    booksAmt: "—",
    status: "missing-books",
  },
  {
    gstin: "27AABCY6789G7Z3",
    invoice: "INV-889",
    date: "22-Oct",
    gstr2bAmt: "₹43,200",
    booksAmt: "₹43,200",
    status: "matched",
  },
];

// Stagger thresholds: rows 0–6 unlock from sp 0.78 → 1.00
const ROW_THRESHOLDS = SHEET_ROWS.map(
  (_, i) => 0.78 + i * ((1.0 - 0.78) / (SHEET_ROWS.length - 1))
);

// ─── Layout constants ─────────────────────────────────────────────────────────

const CARD_WIDTH = 280;
const CARD_GAP = 16;
const SIDE_PAD = 48;
const TOTAL_TRACK_WIDTH =
  STEPS.length * CARD_WIDTH + (STEPS.length - 1) * CARD_GAP;

// ─── StepCard ─────────────────────────────────────────────────────────────────

interface StepCardProps {
  step: Step;
  isActive: boolean;
  isMobile: boolean;
}

function StepCard({ step, isActive, isMobile }: StepCardProps) {
  const borderColor = isActive
    ? "#3b82f6"
    : step.accentRed
    ? "#ef4444"
    : "#2a2a2a";

  return (
    <div
      style={{
        width: isMobile ? "min(280px, 90vw)" : `${CARD_WIDTH}px`,
        minHeight: "320px",
        background: step.accentRed ? "#1a0f0f" : "#111111",
        border: `1px solid ${borderColor}`,
        borderLeft: `3px solid ${borderColor}`,
        borderRadius: "12px",
        padding: "24px",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        transform: isActive && !isMobile ? "scale(1.02)" : "scale(1)",
        transition: "border-color 300ms ease, transform 300ms ease",
        boxSizing: "border-box",
      }}
    >
      {/* Icon */}
      <span style={{ fontSize: "2rem", lineHeight: 1, userSelect: "none" }}>
        {step.icon}
      </span>

      {/* Step label */}
      <p
        style={{
          fontFamily: "var(--font-jetbrains-mono, monospace)",
          fontSize: "0.75rem",
          color: "#3b82f6",
          margin: "14px 0 0",
          letterSpacing: "0.1em",
        }}
      >
        {step.stepLabel}
      </p>

      {/* Title */}
      <h3
        style={{
          fontFamily: "var(--font-inter, Inter, sans-serif)",
          fontSize: "1.1rem",
          fontWeight: 600,
          color: "#f0f0f0",
          margin: "8px 0 0",
          lineHeight: 1.3,
        }}
      >
        {step.title}
      </h3>

      {/* Description */}
      <p
        style={{
          fontFamily: "var(--font-inter, Inter, sans-serif)",
          fontSize: "0.85rem",
          color: "#9ca3af",
          lineHeight: 1.6,
          margin: "12px 0 0",
          flex: 1,
        }}
      >
        {step.description}
      </p>

      {/* Footer: tag + time */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: "16px",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-jetbrains-mono, monospace)",
            fontSize: "0.7rem",
            color: "#6b7280",
            background: "#1f2937",
            borderRadius: "4px",
            padding: "2px 8px",
          }}
        >
          {step.tag}
        </span>
        <span
          style={{
            fontFamily: "var(--font-jetbrains-mono, monospace)",
            fontSize: "0.75rem",
            color: "#ef4444",
          }}
        >
          {step.time}
        </span>
      </div>
    </div>
  );
}

// ─── Spreadsheet row helpers ──────────────────────────────────────────────────

function statusCell(status: RowStatus): { text: string; color: string } {
  switch (status) {
    case "matched":
      return { text: "✅ Matched", color: "#22c55e" };
    case "missing-books":
      return { text: "⚠️ Missing in books", color: "#f97316" };
    case "missing-2b":
      return { text: "⚠️ Missing in 2B", color: "#f97316" };
    case "mismatch":
      return { text: "❌ Amount mismatch", color: "#ef4444" };
  }
}

function rowBackground(status: RowStatus): string {
  switch (status) {
    case "matched":
      return "#1a1a1a";
    case "missing-books":
    case "missing-2b":
      return "#1a0f0f";
    case "mismatch":
      return "#1a0a0a";
  }
}

interface SheetRowProps {
  row: SheetRow;
  visible: boolean;
}

function SpreadsheetRow({ row, visible }: SheetRowProps) {
  const { text, color } = statusCell(row.status);
  const bg = rowBackground(row.status);

  const cellBase: CSSProperties = {
    fontFamily: "var(--font-jetbrains-mono, monospace)",
    fontSize: "0.75rem",
    color: "#a0a0a0",
    padding: "10px 14px",
    border: "1px solid #2a2a2a",
    background: bg,
    whiteSpace: "nowrap",
  };

  return (
    <tr
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(8px)",
        transition: "opacity 0.3s ease, transform 0.3s ease",
      }}
    >
      <td style={{ ...cellBase, color: "#555", fontSize: "0.68rem" }}>
        {row.gstin}
      </td>
      <td style={cellBase}>{row.invoice}</td>
      <td style={cellBase}>{row.date}</td>
      <td style={cellBase}>{row.gstr2bAmt}</td>
      <td style={cellBase}>{row.booksAmt}</td>
      <td style={{ ...cellBase, color, fontWeight: 600 }}>{text}</td>
    </tr>
  );
}

// ─── Chapter ──────────────────────────────────────────────────────────────────

/**
 * Chapter 02 — The Work
 *
 * Phase 1  (0.00 – 0.10): Title + subtitle fade in
 * Phase 2  (0.10 – 0.75): Horizontal card timeline pans left
 * Phase 3  (0.75 – 1.00): Spreadsheet appears; rows stagger in; closing lines overlay
 *
 * Layout:
 *   Top 15%  — chapter header
 *   Mid 55%  — horizontal pan track (desktop) / vertical stack (mobile)
 *   Bot 30%  — spreadsheet table
 *   Overlay  — "3–4 hours / You have 40." absolute bottom
 */
export function Chapter02_TheWork({ scrollProgress: sp }: Props) {
  // ── Viewport / responsive ────────────────────────────────────────────────
  const [vpWidth, setVpWidth] = useState(0);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const update = () => {
      setVpWidth(window.innerWidth);
      setIsMobile(window.innerWidth < 768);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // ── Horizontal pan ───────────────────────────────────────────────────────
  // At sp=0.10 → translateX=0 (first card at SIDE_PAD from left)
  // At sp=0.75 → translateX = maxTranslate (last card at SIDE_PAD from right)
  const maxTranslate =
    vpWidth > 0
      ? -(TOTAL_TRACK_WIDTH - vpWidth + 2 * SIDE_PAD)
      : 0;

  const translateX = isMobile
    ? 0
    : mapRange(sp, 0.1, 0.75, 0, Math.min(maxTranslate, 0));

  // ── Active card (whichever center is closest to viewport center) ─────────
  // Card i center from left = SIDE_PAD + translateX + i*(CARD_WIDTH+CARD_GAP) + CARD_WIDTH/2
  // Solve for i where card center = vpWidth/2:
  const activeIndex =
    vpWidth > 0
      ? Math.min(
          STEPS.length - 1,
          Math.max(
            0,
            Math.round(
              (vpWidth / 2 - SIDE_PAD - translateX - CARD_WIDTH / 2) /
                (CARD_WIDTH + CARD_GAP)
            )
          )
        )
      : 0;

  // ── Step counter label (which step is currently active, 1-based) ─────────
  const stepLabel = `${activeIndex + 1} / ${STEPS.length}`;

  // ── Phase 1: title ───────────────────────────────────────────────────────
  const titleOpacity = mapRange(sp, 0.0, 0.1, 0, 1);
  const titleY = mapRange(sp, 0.0, 0.1, -12, 0);

  // ── Phase 2: cards ───────────────────────────────────────────────────────
  // Fade in slightly ahead of pan start
  const cardsOpacity = mapRange(sp, 0.06, 0.16, 0, 1);

  // Progress dots: how far along the pan are we (0 = first card, 7 = last)
  const dotProgress = mapRange(sp, 0.1, 0.75, 0, STEPS.length - 1);

  // ── Phase 3: spreadsheet ─────────────────────────────────────────────────
  const sheetOpacity = mapRange(sp, 0.75, 0.88, 0, 1);
  const sheetY = mapRange(sp, 0.75, 0.88, 20, 0);

  // Row visibility
  const rowVisible = ROW_THRESHOLDS.map((t) => sp >= t);

  // ── Closing overlay ──────────────────────────────────────────────────────
  const closingOpacity = mapRange(sp, 0.93, 1.0, 0, 1);
  const closingY = mapRange(sp, 0.93, 1.0, 14, 0);

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <StickyScene background="#0a0a0a">
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          overflow: "hidden",
          position: "relative",
        }}
      >

        {/* ── HEADER 15% ──────────────────────────────────────────────────── */}
        <div
          style={{
            height: "15%",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            padding: isMobile ? "0 20px" : `0 ${SIDE_PAD}px`,
            opacity: titleOpacity,
            transform: `translateY(${titleY}px)`,
          }}
        >
          <div>
            <h2
              style={{
                fontFamily: "var(--font-inter, Inter, sans-serif)",
                fontSize: "clamp(1.1rem, 2.2vw, 2rem)",
                fontWeight: 400,
                color: "#f0f0f0",
                margin: 0,
                lineHeight: 1.25,
              }}
            >
              Here&rsquo;s what reconciliation actually looks like.
            </h2>
            <p
              style={{
                fontFamily: "var(--font-jetbrains-mono, monospace)",
                fontSize: "clamp(0.65rem, 1.1vw, 0.85rem)",
                color: "#6b7280",
                margin: "8px 0 0",
                letterSpacing: "0.02em",
              }}
            >
              Every month. For every client.
            </p>
          </div>
        </div>

        {/* ── CARD TRACK 55% ──────────────────────────────────────────────── */}
        <div
          style={{
            height: "55%",
            flexShrink: 0,
            position: "relative",
            overflow: "hidden",
            opacity: cardsOpacity,
          }}
        >
          {!isMobile ? (
            /* Desktop: horizontally panning track */
            <>
              <div
                style={{
                  display: "flex",
                  gap: `${CARD_GAP}px`,
                  position: "absolute",
                  top: "50%",
                  left: 0,
                  /* translateX drives the pan; SIDE_PAD gives initial left indent */
                  transform: `translateX(${translateX + SIDE_PAD}px) translateY(-50%)`,
                  willChange: "transform",
                }}
              >
                {STEPS.map((step, i) => (
                  <StepCard
                    key={i}
                    step={step}
                    isActive={i === activeIndex}
                    isMobile={false}
                  />
                ))}
              </div>

              {/* Progress dots — bottom of card track area */}
              <div
                style={{
                  position: "absolute",
                  bottom: "12px",
                  left: SIDE_PAD,
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                {STEPS.map((_, i) => (
                  <div
                    key={i}
                    style={{
                      height: "3px",
                      borderRadius: "2px",
                      background:
                        i <= Math.round(dotProgress) ? "#3b82f6" : "#2a2a2a",
                      width:
                        i <= Math.round(dotProgress) ? "20px" : "6px",
                      transition: "all 300ms ease",
                    }}
                  />
                ))}
                <span
                  style={{
                    fontFamily: "var(--font-jetbrains-mono, monospace)",
                    fontSize: "0.65rem",
                    color: "#444",
                    marginLeft: "8px",
                  }}
                >
                  {stepLabel}
                </span>
              </div>
            </>
          ) : (
            /* Mobile: vertically scrollable card list */
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: `${CARD_GAP}px`,
                padding: "12px 20px",
                overflowY: "auto",
                height: "100%",
                alignItems: "center",
              }}
            >
              {STEPS.map((step, i) => (
                <StepCard key={i} step={step} isActive={false} isMobile />
              ))}
            </div>
          )}
        </div>

        {/* ── SPREADSHEET 30% ─────────────────────────────────────────────── */}
        <div
          style={{
            height: "30%",
            flexShrink: 0,
            opacity: sheetOpacity,
            transform: `translateY(${sheetY}px)`,
            display: "flex",
            flexDirection: "column",
            gap: "6px",
            padding: isMobile ? "0 12px" : `0 ${SIDE_PAD}px`,
            overflow: "hidden",
          }}
        >
          {/* Table label */}
          <p
            style={{
              fontFamily: "var(--font-jetbrains-mono, monospace)",
              fontSize: "0.68rem",
              color: "#6b7280",
              margin: 0,
              letterSpacing: "0.06em",
              flexShrink: 0,
            }}
          >
            GSTR-2B vs PURCHASE REGISTER — MEHTA &amp; SONS — OCT 2024
          </p>

          {/* Scrollable table wrapper */}
          <div
            style={{
              overflowX: "auto",
              overflowY: "hidden",
              flex: 1,
              minHeight: 0,
              /* On mobile, allow full-width horizontal scroll */
            }}
          >
            <table
              style={{
                minWidth: "600px",
                width: "100%",
                borderCollapse: "collapse",
              }}
            >
              <thead>
                <tr>
                  {[
                    "Supplier GSTIN",
                    "Invoice No.",
                    "Invoice Date",
                    "GSTR-2B Amt",
                    "Books Amt",
                    "Status",
                  ].map((col) => (
                    <th
                      key={col}
                      style={{
                        fontFamily: "var(--font-jetbrains-mono, monospace)",
                        fontSize: "0.68rem",
                        color: "#6b7280",
                        background: "#2a2a2a",
                        padding: "8px 14px",
                        border: "1px solid #333",
                        textAlign: "left",
                        textTransform: "uppercase",
                        letterSpacing: "0.08em",
                        whiteSpace: "nowrap",
                        fontWeight: 500,
                      }}
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {SHEET_ROWS.map((row, i) => (
                  <SpreadsheetRow key={i} row={row} visible={rowVisible[i]} />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── CLOSING OVERLAY (absolute bottom) ───────────────────────────── */}
        {/*
         * Positioned absolute so it sits over the spreadsheet section once
         * enough scroll space has been consumed — avoids layout overflow.
         * Appears at sp ≥ 0.93, after all spreadsheet rows are visible.
         */}
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            /* Gradient mask so text lifts out of the table cleanly */
            background:
              "linear-gradient(to top, #0a0a0a 40%, rgba(10,10,10,0.85) 70%, transparent 100%)",
            padding: "32px 24px 28px",
            textAlign: "center",
            opacity: closingOpacity,
            transform: `translateY(${closingY}px)`,
            pointerEvents: "none",
          }}
        >
          <p
            style={{
              fontFamily: "var(--font-inter, Inter, sans-serif)",
              fontSize: "clamp(1.1rem, 2.5vw, 1.8rem)",
              fontWeight: 300,
              color: "#f0f0f0",
              margin: 0,
              lineHeight: 1.3,
            }}
          >
            3–4 hours. One client.
          </p>
          <p
            style={{
              fontFamily: "var(--font-inter, Inter, sans-serif)",
              fontSize: "clamp(1.1rem, 2.5vw, 1.8rem)",
              fontWeight: 300,
              color: "#ef4444",
              margin: "6px 0 0",
              lineHeight: 1.3,
            }}
          >
            You have 40.
          </p>
        </div>

      </div>
    </StickyScene>
  );
}
