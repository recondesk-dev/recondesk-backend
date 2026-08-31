"use client";

import dynamic from "next/dynamic";
import { ScrollProgress } from "@/components/scrollstory/shared/ScrollProgress";
import { ChapterWrapper } from "@/components/scrollstory/shared/ChapterWrapper";

// Dynamically import all chapters (client-only, no SSR)
const Chapter01_Moment = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter01_Moment").then(
      (m) => m.Chapter01_Moment
    ),
  { ssr: false }
);
const Chapter02_TheWork = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter02_TheWork").then(
      (m) => m.Chapter02_TheWork
    ),
  { ssr: false }
);
const Chapter03_WhyBroken = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter03_WhyBroken").then(
      (m) => m.Chapter03_WhyBroken
    ),
  { ssr: false }
);
const Chapter04_TheCost = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter04_TheCost").then(
      (m) => m.Chapter04_TheCost
    ),
  { ssr: false }
);
const Chapter05_Imagine = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter05_Imagine").then(
      (m) => m.Chapter05_Imagine
    ),
  { ssr: false }
);
const Chapter06_Solution = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter06_Solution").then(
      (m) => m.Chapter06_Solution
    ),
  { ssr: false }
);
const Chapter07_Proof = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter07_Proof").then(
      (m) => m.Chapter07_Proof
    ),
  { ssr: false }
);
const Chapter08_Transformation = dynamic(
  () =>
    import("@/components/scrollstory/chapters/Chapter08_Transformation").then(
      (m) => m.Chapter08_Transformation
    ),
  { ssr: false }
);

/**
 * /story — ReconDesk scrollytelling landing page.
 *
 * Architecture:
 * - Each ChapterWrapper allocates N×100vh of scroll space.
 * - The sticky div inside stays fixed in viewport while scrolling through that space.
 * - ChapterWrapper computes scrollProgress (0–1) and passes it to the chapter via render prop.
 * - All chapters are client-only (dynamic import, ssr: false).
 */
export default function StoryPage() {
  return (
    <main className="relative bg-[#0a0a0a] font-sans">
      {/* Global scroll progress indicator */}
      <ScrollProgress />

      {/* ─── Chapter 01: The Moment ─────────────────────────────────────── */}
      <ChapterWrapper id="chapter-01" scrollHeight={4}>
        {(p) => <Chapter01_Moment scrollProgress={p} />}
      </ChapterWrapper>

      {/* ─── Chapter 02: The Work ───────────────────────────────────────── */}
      <ChapterWrapper id="chapter-02" scrollHeight={5}>
        {(p) => <Chapter02_TheWork scrollProgress={p} />}
      </ChapterWrapper>

      {/* ─── Chapter 03: Why It's Broken ────────────────────────────────── */}
      <ChapterWrapper id="chapter-03" scrollHeight={4}>
        {(p) => <Chapter03_WhyBroken scrollProgress={p} />}
      </ChapterWrapper>

      {/* ─── Chapter 04: The Cost ───────────────────────────────────────── */}
      <ChapterWrapper id="chapter-04" scrollHeight={4}>
        {(p) => <Chapter04_TheCost scrollProgress={p} />}
      </ChapterWrapper>

      {/* ─── Chapter 05: Imagine ────────────────────────────────────────── */}
      <ChapterWrapper id="chapter-05" scrollHeight={3}>
        {(p) => <Chapter05_Imagine scrollProgress={p} />}
      </ChapterWrapper>

      {/* ─── Chapter 06: Solution ───────────────────────────────────────── */}
      <ChapterWrapper id="chapter-06" scrollHeight={4}>
        {(p) => <Chapter06_Solution scrollProgress={p} />}
      </ChapterWrapper>

      {/* ─── Chapter 07: Proof ──────────────────────────────────────────── */}
      <ChapterWrapper id="chapter-07" scrollHeight={4}>
        {(p) => <Chapter07_Proof scrollProgress={p} />}
      </ChapterWrapper>

      {/* ─── Chapter 08: Transformation ─────────────────────────────────── */}
      <ChapterWrapper id="chapter-08" scrollHeight={4}>
        {(p) => <Chapter08_Transformation scrollProgress={p} />}
      </ChapterWrapper>
    </main>
  );
}
