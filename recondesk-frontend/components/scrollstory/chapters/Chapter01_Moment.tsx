"use client";

import { useEffect, useRef, useState } from "react";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props {
  scrollProgress: number; // 0–1
}

type CardType = "error" | "info";

interface NotificationCard {
  id: number;
  type: CardType;
  icon: string;
  title: string;
  subtitle: string;
  time: string;
  /** scrollProgress threshold at which this card first appears */
  threshold: number;
}

// ─── Data ─────────────────────────────────────────────────────────────────────

const CARDS: NotificationCard[] = [
  {
    id: 0,
    type: "info",
    icon: "📧",
    title: "Client - Mehta & Sons",
    subtitle: "GSTR-2B downloaded. Starting reconciliation.",
    time: "9:04 AM",
    threshold: 0.40,
  },
  {
    id: 1,
    type: "error",
    icon: "⚠️",
    title: "Mismatch detected",
    subtitle: "14 invoices unmatched in purchase register",
    time: "9:47 AM",
    threshold: 0.48,
  },
  {
    id: 2,
    type: "info",
    icon: "💬",
    title: "WhatsApp - Ramesh (Client)",
    subtitle: "Sir aapne file kiya kya? Portal pe nahi dikh raha",
    time: "11:12 AM",
    threshold: 0.55,
  },
  {
    id: 3,
    type: "error",
    icon: "📧",
    title: "Client - Sharma Traders",
    subtitle: "Bhai reconciliation kab hogi? Notice aa gaya",
    time: "2:38 PM",
    threshold: 0.62,
  },
  {
    id: 4,
    type: "error",
    icon: "⚠️",
    title: "4 clients pending reconciliation",
    subtitle: "GSTR-3B due in 2 days",
    time: "6:55 PM",
    threshold: 0.70,
  },
];

// ─── Helper ───────────────────────────────────────────────────────────────────

/**
 * Maps a value from one range to another, clamped to [outMin, outMax].
 */
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

// ─── Notification Card ────────────────────────────────────────────────────────

interface CardProps {
  card: NotificationCard;
  /** Whether this card has been "unlocked" by scroll crossing its threshold */
  visible: boolean;
}

function NotifCard({ card, visible }: CardProps) {
  const accentColor = card.type === "error" ? "#ef4444" : "#3b82f6";

  return (
    <div
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(20px)",
        transition: "opacity 0.35s ease, transform 0.35s ease",
        background: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderLeft: `3px solid ${accentColor}`,
        borderRadius: "8px",
        padding: "12px 16px",
        display: "flex",
        alignItems: "flex-start",
        gap: "12px",
        minWidth: 0,
      }}
    >
      {/* Icon */}
      <span
        style={{ fontSize: "1.1rem", lineHeight: 1.4, flexShrink: 0 }}
        role="img"
        aria-label={card.type === "error" ? "warning" : "message"}
      >
        {card.icon}
      </span>

      {/* Body */}
      <div style={{ minWidth: 0, flex: 1 }}>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--font-jetbrains-mono, monospace)",
            fontSize: "0.75rem",
            fontWeight: 600,
            color: accentColor,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {card.title}
        </p>
        <p
          style={{
            margin: "3px 0 0",
            fontFamily: "var(--font-jetbrains-mono, monospace)",
            fontSize: "0.8rem",
            color: "#a0a0a0",
            lineHeight: 1.4,
            wordBreak: "break-word",
          }}
        >
          {card.subtitle}
        </p>
      </div>

      {/* Timestamp */}
      <span
        style={{
          fontFamily: "var(--font-jetbrains-mono, monospace)",
          fontSize: "0.65rem",
          color: "#555",
          flexShrink: 0,
          marginTop: "2px",
        }}
      >
        {card.time}
      </span>
    </div>
  );
}

// ─── Chapter ──────────────────────────────────────────────────────────────────

/**
 * Chapter 01 — The Moment
 *
 * Phase 1  (0.00 – 0.15): "It's the 14th of the month." fades in
 * Phase 2  (0.15 – 0.35): Previous line fades out, new headline + subtitle appear
 * Phase 3  (0.35 – 0.75): Notification stack, cards appear one by one
 * Phase 4  (0.75 – 1.00): Stack dims, "This happens every month." fades in over it
 *
 * All opacity/transform values are derived from scrollProgress via mapRange().
 * Cards use a one-way unlock state (never hidden once shown).
 */
export function Chapter01_Moment({ scrollProgress: sp }: Props) {
  // ── Card unlock state ──────────────────────────────────────────────────────
  const [unlockedIds, setUnlockedIds] = useState<Set<number>>(new Set());
  const prevSp = useRef(0);

  useEffect(() => {
    // Only check forward-scroll direction to prevent flickering on scroll-back
    if (sp <= prevSp.current && sp > 0.01) {
      prevSp.current = sp;
      return;
    }
    prevSp.current = sp;

    setUnlockedIds((prev) => {
      const next = new Set(prev);
      for (const card of CARDS) {
        if (sp >= card.threshold) {
          next.add(card.id);
        }
      }
      return next;
    });
  }, [sp]);

  // ── Phase opacities (all via mapRange) ────────────────────────────────────

  // Phase 1: "It's the 14th of the month."
  // Fade in: 0.00 → 0.12 | Hold | Fade out: 0.15 → 0.22
  const line1FadeIn  = mapRange(sp, 0.00, 0.12, 0, 1);
  const line1FadeOut = mapRange(sp, 0.15, 0.22, 1, 0);
  const line1Opacity = sp < 0.15 ? line1FadeIn : line1FadeOut;
  const line1Y       = sp < 0.15
    ? mapRange(sp, 0.00, 0.12, 12, 0)   // rises up into position
    : mapRange(sp, 0.15, 0.22, 0, -8);  // floats up slightly as it exits

  // Phase 2 — main headline: "You have 40 clients."
  // Fade in: 0.17 → 0.27 | Hold | Fade out: 0.33 → 0.40
  const line2HeadFadeIn  = mapRange(sp, 0.17, 0.27, 0, 1);
  const line2HeadFadeOut = mapRange(sp, 0.33, 0.40, 1, 0);
  const line2HeadOpacity = sp < 0.33 ? line2HeadFadeIn : line2HeadFadeOut;
  const line2HeadY       = sp < 0.33
    ? mapRange(sp, 0.17, 0.27, 12, 0)
    : mapRange(sp, 0.33, 0.40, 0, -8);

  // Phase 2 — subtitle: "GSTR-3B is due in 4 days."
  // Same fade but with ~0.05 delay in range
  const line2SubFadeIn  = mapRange(sp, 0.22, 0.32, 0, 1);
  const line2SubFadeOut = mapRange(sp, 0.33, 0.40, 1, 0);
  const line2SubOpacity = sp < 0.33 ? line2SubFadeIn : line2SubFadeOut;
  const line2SubY       = sp < 0.33
    ? mapRange(sp, 0.22, 0.32, 10, 0)
    : mapRange(sp, 0.33, 0.40, 0, -6);

  // Phase 3 — notification stack wrapper
  // Fade in: 0.35 → 0.42
  const stackOpacityBase = mapRange(sp, 0.35, 0.42, 0, 1);
  // Phase 4 — stack dims to 0.3 opacity
  const stackDim         = mapRange(sp, 0.75, 0.85, 1, 0.3);
  const stackOpacity     = sp < 0.75
    ? stackOpacityBase
    : stackOpacityBase * stackDim;
  const stackY = mapRange(sp, 0.35, 0.42, 20, 0);

  // Phase 4 — "This happens every month."
  const endHeadOpacity = mapRange(sp, 0.78, 0.90, 0, 1);
  const endHeadY       = mapRange(sp, 0.78, 0.90, 16, 0);

  // Phase 4 — "For every client. Every month. Without fail."
  const endSubOpacity = mapRange(sp, 0.85, 0.96, 0, 1);
  const endSubY       = mapRange(sp, 0.85, 0.96, 10, 0);

  // Scroll hint — only in the very first sliver
  const scrollHintOpacity = mapRange(sp, 0.00, 0.06, 1, 0);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <StickyScene background="#0a0a0a">
      <div
        style={{
          position: "relative",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          width: "100%",
          height: "100%",
          padding: "0 24px",
          overflow: "hidden",
        }}
      >

        {/* ── Phase 1: "It's the 14th of the month." ─────────────────────── */}
        <div
          style={{
            position: "absolute",
            top: 0, left: 0, right: 0, bottom: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "0 24px",
            opacity: line1Opacity,
            transform: `translateY(${line1Y}px)`,
            pointerEvents: "none",
            // willChange omitted intentionally — pure CPU compositing is fine here
          }}
          aria-hidden={line1Opacity < 0.05}
        >
          <p
            style={{
              fontFamily: "var(--font-inter, Inter, sans-serif)",
              fontSize: "clamp(1.75rem, 4vw, 3rem)",
              fontWeight: 300,
              color: "#f0f0f0",
              textAlign: "center",
              lineHeight: 1.3,
              margin: 0,
            }}
          >
            It&rsquo;s the 14th of the month.
          </p>
        </div>

        {/* ── Phase 2: "You have 40 clients." + subtitle ──────────────────── */}
        <div
          style={{
            position: "absolute",
            top: 0, left: 0, right: 0, bottom: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "0 24px",
            pointerEvents: "none",
          }}
          aria-hidden={line2HeadOpacity < 0.05}
        >
          <p
            style={{
              fontFamily: "var(--font-inter, Inter, sans-serif)",
              fontSize: "clamp(1.75rem, 4vw, 3rem)",
              fontWeight: 300,
              color: "#f0f0f0",
              textAlign: "center",
              lineHeight: 1.3,
              margin: 0,
              opacity: line2HeadOpacity,
              transform: `translateY(${line2HeadY}px)`,
            }}
          >
            You have 40 clients.
          </p>
          <p
            style={{
              fontFamily: "var(--font-jetbrains-mono, monospace)",
              fontSize: "clamp(0.75rem, 1.5vw, 1rem)",
              fontWeight: 400,
              color: "#6b7280",
              textAlign: "center",
              marginTop: "16px",
              letterSpacing: "0.02em",
              opacity: line2SubOpacity,
              transform: `translateY(${line2SubY}px)`,
            }}
          >
            GSTR-3B is due in 4 days.
          </p>
        </div>

        {/* ── Phase 3: Notification stack ─────────────────────────────────── */}
        <div
          style={{
            position: "absolute",
            top: 0, left: 0, right: 0, bottom: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "0 20px",
            pointerEvents: stackOpacity < 0.05 ? "none" : "auto",
          }}
        >
          <div
            style={{
              width: "100%",
              maxWidth: "min(400px, 90vw)",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
              opacity: stackOpacity,
              transform: `translateY(${stackY}px)`,
            }}
          >
            {/* Stack label */}
            <p
              style={{
                fontFamily: "var(--font-jetbrains-mono, monospace)",
                fontSize: "0.65rem",
                color: "#444",
                textTransform: "uppercase",
                letterSpacing: "0.15em",
                margin: "0 0 4px 2px",
              }}
            >
              Today · 5 notifications
            </p>

            {CARDS.map((card) => (
              <NotifCard
                key={card.id}
                card={card}
                visible={unlockedIds.has(card.id)}
              />
            ))}
          </div>
        </div>

        {/* ── Phase 4: "This happens every month." ────────────────────────── */}
        <div
          style={{
            position: "absolute",
            top: 0, left: 0, right: 0, bottom: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "0 24px",
            pointerEvents: "none",
          }}
          aria-hidden={endHeadOpacity < 0.05}
        >
          <p
            style={{
              fontFamily: "var(--font-inter, Inter, sans-serif)",
              fontSize: "clamp(1.5rem, 3.5vw, 2.5rem)",
              fontWeight: 400,
              color: "#f0f0f0",
              textAlign: "center",
              lineHeight: 1.3,
              margin: 0,
              opacity: endHeadOpacity,
              transform: `translateY(${endHeadY}px)`,
            }}
          >
            This happens every month.
          </p>
          <p
            style={{
              fontFamily: "var(--font-jetbrains-mono, monospace)",
              fontSize: "clamp(0.7rem, 1.2vw, 0.9rem)",
              fontWeight: 400,
              color: "#6b7280",
              textAlign: "center",
              letterSpacing: "0.05em",
              marginTop: "20px",
              opacity: endSubOpacity,
              transform: `translateY(${endSubY}px)`,
            }}
          >
            For every client. Every month. Without fail.
          </p>
        </div>

        {/* ── Scroll hint ──────────────────────────────────────────────────── */}
        <div
          style={{
            position: "absolute",
            bottom: "32px",
            left: "50%",
            transform: "translateX(-50%)",
            opacity: scrollHintOpacity,
            pointerEvents: "none",
            animation: "scrollHintBob 1.6s ease-in-out infinite",
          }}
          aria-hidden="true"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 5v14M5 12l7 7 7-7"
              stroke="#555"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      </div>

      {/* Keyframes for scroll hint — injected inline to avoid global CSS dependency */}
      <style>{`
        @keyframes scrollHintBob {
          0%, 100% { transform: translateX(-50%) translateY(0); }
          50%       { transform: translateX(-50%) translateY(7px); }
        }
      `}</style>
    </StickyScene>
  );
}
