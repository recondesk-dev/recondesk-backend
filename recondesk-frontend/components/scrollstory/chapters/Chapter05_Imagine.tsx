"use client";

import { motion } from "framer-motion";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";

interface Props {
  scrollProgress: number;
}

const WORDS = "What if the reconciliation just... happened?".split(" ");

/**
 * Chapter 05 — Imagine
 * Background transitions dark → white. Text appears word-by-word on scroll.
 */
export function Chapter05_Imagine({ scrollProgress }: Props) {
  // Background: #0a0a0a → #ffffff across full scroll
  const t = Math.min(Math.max(scrollProgress, 0), 1);
  const r = Math.round(10 + (255 - 10) * t);
  const g = Math.round(10 + (255 - 10) * t);
  const b = Math.round(10 + (255 - 10) * t);
  const bgColor = `rgb(${r},${g},${b})`;
  const textColor = t > 0.5 ? "#0a0a0a" : "#f0f0f0";
  const subtextColor = t > 0.5 ? "#555" : "#888";

  // Words appear: progress 0.1 → 0.8 drives word reveal
  const wordProgress = Math.max((scrollProgress - 0.1) / 0.7, 0);
  const visibleWords = Math.floor(wordProgress * WORDS.length);

  return (
    <StickyScene background={bgColor}>
      <div className="relative flex h-full w-full flex-col items-center justify-center px-8 text-center">
        {/* Chapter label */}
        <motion.p
          className="mb-8 font-mono text-xs uppercase tracking-[0.25em]"
          style={{ color: subtextColor }}
          animate={{ opacity: 1 }}
          initial={{ opacity: 0 }}
        >
          Chapter 05 — Imagine
        </motion.p>

        {/* Word-by-word text */}
        <h2 className="max-w-3xl text-4xl font-semibold leading-tight sm:text-5xl lg:text-6xl">
          {WORDS.map((word, i) => (
            <motion.span
              key={i}
              className="mr-[0.25em] inline-block"
              style={{ color: textColor }}
              animate={{
                opacity: i < visibleWords ? 1 : 0.08,
                y: i < visibleWords ? 0 : 12,
              }}
              transition={{ duration: 0.8, ease: "easeOut" }}
            >
              {word}
            </motion.span>
          ))}
        </h2>

        {/* Sub-text after reveal */}
        <motion.p
          className="mt-10 max-w-lg text-base leading-relaxed sm:text-lg"
          style={{ color: subtextColor }}
          animate={{ opacity: visibleWords >= WORDS.length ? 1 : 0, y: visibleWords >= WORDS.length ? 0 : 16 }}
          transition={{ duration: 1, ease: "easeOut" }}
        >
          No VLOOKUPs. No manual column matching. No late-night portal sessions.
          Just upload, and know.
        </motion.p>

        {/* Transition indicator */}
        {t > 0.85 && (
          <motion.div
            className="absolute bottom-10 left-1/2 -translate-x-1/2"
            animate={{ y: [0, 8, 0] }}
            transition={{ repeat: Infinity, duration: 1.5 }}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 5v14M5 12l7 7 7-7"
                stroke={t > 0.5 ? "#ccc" : "#555"}
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </motion.div>
        )}
      </div>
    </StickyScene>
  );
}
