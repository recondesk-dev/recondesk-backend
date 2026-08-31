"use client";

import React from "react";

interface StickySceneProps {
  children: React.ReactNode;
  className?: string;
  /** Background color token or CSS value */
  background?: string;
}

/**
 * StickyScene — the inner visual canvas of a chapter.
 * Fills 100% of the sticky viewport provided by ChapterWrapper.
 * Handles overflow hidden, centering, and background color.
 */
export function StickyScene({
  children,
  className = "",
  background = "#0a0a0a",
}: StickySceneProps) {
  return (
    <div
      className={`relative flex h-full w-full items-center justify-center overflow-hidden ${className}`}
      style={{ background }}
    >
      {children}
    </div>
  );
}
