"use client";

import { Copy } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";

const tooltipClass =
  "pointer-events-none fixed z-[200] whitespace-nowrap rounded-lg bg-gray-900 px-2 py-1 text-[11px] font-mono shadow-lg";

export function GstinCell({
  gstin,
  className = "",
}: {
  gstin: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const anchorRef = useRef<HTMLSpanElement>(null);
  const value = gstin?.trim() ?? "";
  const display = value || "—";

  const syncPos = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPos({ top: rect.top - 6, left: rect.left });
  }, []);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  useEffect(() => {
    if (!hovered && !copied) return;
    syncPos();
    const update = () => syncPos();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [hovered, copied, syncPos]);

  const copyGstin = useCallback(
    async (e: MouseEvent | KeyboardEvent) => {
      e.stopPropagation();
      if (!value) return;
      syncPos();
      try {
        await navigator.clipboard.writeText(value);
        setCopied(true);
      } catch {
        // clipboard unavailable
      }
    },
    [value, syncPos]
  );

  const showTooltip = hovered || copied;

  const tooltip =
    typeof document !== "undefined" && showTooltip && value
      ? createPortal(
          <span
            className={tooltipClass}
            style={{
              top: pos.top,
              left: pos.left,
              transform: "translateY(-100%)",
            }}
          >
            {copied ? (
              <span className="text-green-400">Copied!</span>
            ) : (
              <span className="text-white">{value}</span>
            )}
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
        role="button"
        tabIndex={0}
        onClick={(e) => void copyGstin(e)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            void copyGstin(e);
          }
        }}
        onMouseEnter={() => {
          syncPos();
          setHovered(true);
        }}
        onMouseLeave={() => {
          if (!copied) setHovered(false);
        }}
        className={`group relative inline-block w-full max-w-full cursor-pointer ${className}`}
      >
        <span className="inline-flex w-full max-w-full items-center gap-1">
          <span className="min-w-0 truncate">{display}</span>
          <Copy className="h-3 w-3 shrink-0 text-gray-400 opacity-0 transition-opacity group-hover:opacity-100" />
        </span>
      </span>
      {tooltip}
    </>
  );
}
