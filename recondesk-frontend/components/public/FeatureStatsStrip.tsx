"use client";

import { useEffect, useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const RULE_COUNT_FALLBACK = "90+";

const STATIC_STATS = [
  {
    value: "5-Level",
    label: "Matching Engine",
    description: "L1 exact to L5 probable",
  },
  {
    value: "17(5)",
    label: "Blocked Credit Flags",
    description: "All categories detected",
  },
  {
    value: "180-Day",
    label: "Rule 37 Tracking",
    description: "Payment deadline alerts",
  },
] as const;

function StatCard({
  value,
  label,
  description,
}: {
  value: string;
  label: string;
  description: string;
}) {
  return (
    <div className="flex flex-col rounded-2xl border border-[#E8E8E8] bg-white px-6 py-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <p className="text-2xl font-semibold tracking-tight text-[#0A0A0A] sm:text-3xl">{value}</p>
      <p className="mt-1 text-sm font-medium text-[#0A0A0A]">{label}</p>
      <p className="mt-2 text-xs leading-relaxed text-[#6B6B6B]">{description}</p>
    </div>
  );
}

export function FeatureStatsStrip() {
  const [ruleCount, setRuleCount] = useState(RULE_COUNT_FALLBACK);

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
          setRuleCount(`${total}+`);
        }
      })
      .catch(() => {
        // Keep static fallback while loading or on error.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section
      className="mx-auto mt-16 mb-4 max-w-4xl px-4"
      aria-label="Product capabilities"
    >
      <p className="text-center text-[11px] font-semibold uppercase tracking-widest text-gray-400">
        WHAT&apos;S UNDER THE HOOD
      </p>
      <div className="mt-6 grid grid-cols-2 gap-4 text-left md:grid-cols-4">
        <StatCard
          value={ruleCount}
          label="Logic Rules"
          description="Every GST scenario covered"
        />
        {STATIC_STATS.map((stat) => (
          <StatCard key={stat.label} {...stat} />
        ))}
      </div>
    </section>
  );
}
