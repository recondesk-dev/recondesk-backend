"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

const tooltipClass =
  "pointer-events-none fixed z-[200] max-w-sm rounded-lg bg-gray-900 px-2.5 py-1.5 text-[11px] leading-snug text-white shadow-lg";

export function HoverTextCell({
  text,
  tooltipText,
  className = "",
  displayClassName = "",
}: {
  text: string | null | undefined;
  /** When set, tooltip shows this instead of `text` (cell still uses `text`). */
  tooltipText?: string | null | undefined;
  className?: string;
  displayClassName?: string;
}) {
  const [hovered, setHovered] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const anchorRef = useRef<HTMLSpanElement>(null);
  const value = text?.trim() ?? "";
  const tooltipValue = (tooltipText ?? text)?.trim() ?? "";
  const display = value || "—";

  const syncPos = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPos({ top: rect.top - 6, left: rect.left });
  }, []);

  useEffect(() => {
    if (!hovered) return;
    syncPos();
    const update = () => syncPos();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [hovered, syncPos]);

  const tooltip =
    typeof document !== "undefined" && hovered && tooltipValue
      ? createPortal(
          <span
            className={tooltipClass}
            style={{
              top: pos.top,
              left: pos.left,
              transform: "translateY(-100%)",
            }}
          >
            {tooltipValue}
          </span>,
          document.body
        )
      : null;

  if (!value) {
    return <span className={className}>{display}</span>;
  }

  return (
    <>
      <span
        ref={anchorRef}
        onMouseEnter={() => {
          syncPos();
          setHovered(true);
        }}
        onMouseLeave={() => setHovered(false)}
        className={`inline-block w-full max-w-full cursor-default ${className}`}
      >
        <span className={`block min-w-0 truncate ${displayClassName}`}>
          {display}
        </span>
      </span>
      {tooltip}
    </>
  );
}
