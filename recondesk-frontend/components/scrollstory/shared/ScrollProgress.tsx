"use client";

import { useEffect, useRef, useState } from "react";

/**
 * ScrollProgress — a fixed thin bar at the top of the viewport showing
 * overall page scroll progress (0 → 100%).
 */
export function ScrollProgress() {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const handleScroll = () => {
      const scrollTop = window.scrollY;
      const docHeight =
        document.documentElement.scrollHeight - window.innerHeight;
      setProgress(docHeight > 0 ? (scrollTop / docHeight) * 100 : 0);
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div
      className="fixed left-0 top-0 z-[9999] h-[3px] bg-gradient-to-r from-red-500 via-orange-400 to-green-500 transition-none"
      style={{ width: `${progress}%` }}
      aria-hidden="true"
    />
  );
}
