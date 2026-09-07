import React from "react";

export interface ItcIneligibleBadgeProps {
  itcAvailable?: boolean | null;
  itcReason?: string | null;
}

export function ItcIneligibleBadge({
  itcAvailable,
  itcReason,
}: ItcIneligibleBadgeProps) {
  if (itcAvailable !== false) return null;
  return React.createElement(
    "span",
    {
      className:
        "inline-flex items-center whitespace-nowrap rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-inset ring-amber-600/20",
      title: itcReason || "Marked ineligible in GSTR-2B",
    },
    "ITC Ineligible"
  );
}
