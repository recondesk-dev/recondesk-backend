"use client";

import { useEffect, useRef, useState } from "react";

interface ChapterWrapperProps {
  /** Unique chapter identifier (used for aria labeling) */
  id: string;
  /** How many viewport heights of scroll space to allocate (default: 3) */
  scrollHeight?: number;
  children: (scrollProgress: number) => React.ReactNode;
  className?: string;
}

/**
 * ChapterWrapper — allocates vertical scroll space for a chapter and tracks
 * how far through that space the user has scrolled (0–1).
 *
 * The sticky child inside stays fixed in viewport while the wrapper scrolls past.
 */
export function ChapterWrapper({
  id,
  scrollHeight = 3,
  children,
  className = "",
}: ChapterWrapperProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [scrollProgress, setScrollProgress] = useState(0);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;

    const handleScroll = () => {
      const rect = wrapper.getBoundingClientRect();
      const totalScrollable = wrapper.offsetHeight - window.innerHeight;
      if (totalScrollable <= 0) {
        setScrollProgress(0);
        return;
      }
      // How far the top of the wrapper has scrolled above the viewport top
      const scrolled = -rect.top;
      const progress = Math.min(Math.max(scrolled / totalScrollable, 0), 1);
      setScrollProgress(progress);
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div
      ref={wrapperRef}
      id={id}
      className={`relative ${className}`}
      style={{ height: `${scrollHeight * 100}vh` }}
      aria-label={`Chapter: ${id}`}
    >
      {/* Sticky child stays fixed while wrapper scrolls */}
      <div className="sticky top-0 h-screen w-full overflow-hidden">
        {children(scrollProgress)}
      </div>
    </div>
  );
}
