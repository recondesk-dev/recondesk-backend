export interface Table4GateBadgeInfo {
  dotClass: string;
  badgeClass?: string;
  badgeText?: string;
}

/**
 * Derives the visual gate status badge and indicator dot for the GSTR-3B module tab.
 * Gives CAs real-time visibility into Table 4 blocking exceptions across all tabs.
 */
export function getTable4GateBadgeInfo(
  unresolvedCount?: number,
  isRunFinalized?: boolean
): Table4GateBadgeInfo {
  if (isRunFinalized) {
    return {
      dotClass: "bg-slate-400",
      badgeClass: "bg-slate-100 text-slate-600",
      badgeText: "Finalized",
    };
  }
  if (unresolvedCount != null) {
    if (unresolvedCount > 0) {
      return {
        dotClass: "bg-amber-500",
        badgeClass: "bg-[#FEF3C7] text-[#92400E]",
        badgeText: `${unresolvedCount} blocking`,
      };
    }
    return {
      dotClass: "bg-emerald-500",
      badgeClass: "bg-[#DCFCE7] text-[#166534]",
      badgeText: "Gate Clear",
    };
  }
  return {
    dotClass: "bg-[#2563EB]",
  };
}
