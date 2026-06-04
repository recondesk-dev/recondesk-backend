"use client";

import { Copy } from "lucide-react";
import { useCallback, useEffect, useState, type KeyboardEvent, type MouseEvent } from "react";

export function GstinCell({
  gstin,
  className = "",
}: {
  gstin: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const value = gstin?.trim() ?? "";
  const display = value || "—";

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copyGstin = useCallback(
    async (e: MouseEvent | KeyboardEvent) => {
      e.stopPropagation();
      if (!value) return;
      try {
        await navigator.clipboard.writeText(value);
        setCopied(true);
      } catch {
        // clipboard unavailable
      }
    },
    [value]
  );

  if (!value) {
    return <span className={className}>{display}</span>;
  }

  return (
    <span
      role="button"
      tabIndex={0}
      onClick={(e) => void copyGstin(e)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          void copyGstin(e);
        }
      }}
      className={`group relative inline-block max-w-full cursor-pointer ${className}`}
    >
      <span className="inline-flex max-w-full items-center gap-1">
        <span className="truncate">{display}</span>
        <Copy className="h-3 w-3 shrink-0 text-gray-400 opacity-0 transition-opacity group-hover:opacity-100" />
      </span>
      <span
        className={`absolute bottom-full left-0 z-50 mb-1 whitespace-nowrap rounded-lg bg-gray-900 px-2 py-1 text-[11px] font-mono shadow-lg ${
          copied ? "block" : "hidden group-hover:block"
        }`}
      >
        {copied ? (
          <span className="text-green-400">Copied!</span>
        ) : (
          <span className="text-white">{value}</span>
        )}
      </span>
    </span>
  );
}
