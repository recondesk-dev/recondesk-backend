"use client";

import { useEffect, useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const STATIC_STATS = ["5-level matching", "Rule 37 detection", "Section 17(5) flags"] as const;
const RULE_COUNT_FALLBACK = "90+ logic rules";

function FeatureStatBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex shrink-0 items-center rounded-xl border border-[#E8E8E8] bg-white px-4 py-2 text-[13px] font-medium leading-tight text-[#0A0A0A]">
      {label}
    </span>
  );
}

function RuleCountBadge() {
  const [label, setLabel] = useState(RULE_COUNT_FALLBACK);

  useEffect(() => {
    let cancelled = false;

    fetch(`${API_URL}/api/rules/summary`)
      .then((res) => {
        if (!res.ok) throw new Error("Rules summary request failed");
        return res.json() as Promise<{ total?: number }>;
      })
      .then((data) => {
        if (cancelled) return;
        const total = typeof data.total === "number" ? data.total : null;
        if (total !== null && total > 0) {
          setLabel(`${total}+ logic rules`);
        }
      })
      .catch(() => {
        // Keep static fallback while loading or on error.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return <FeatureStatBadge label={label} />;
}

export function FeatureStatsStrip() {
  return (
    <div
      className="mt-6 flex flex-wrap items-center justify-center gap-2 sm:mt-8 sm:gap-3"
      aria-label="Product capabilities"
    >
      {STATIC_STATS.map((label) => (
        <FeatureStatBadge key={label} label={label} />
      ))}
      <RuleCountBadge />
    </div>
  );
}
