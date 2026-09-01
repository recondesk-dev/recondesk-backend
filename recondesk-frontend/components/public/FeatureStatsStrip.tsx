"use client";

import { useEffect, useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const RULE_COUNT_FALLBACK = "103+";

const STATIC_STATS = [
  {
    value: "5-Level",
    label: "Matching Engine",
    description: "L1 exact to L4 PAN & L6 review",
  },
  {
    value: "17(5)",
    label: "Blocked Credit Flags",
    description: "All restricted categories detected",
  },
  {
    value: "180-Day",
    label: "Rule 37 Tracking",
    description: "Payment deadline & reversal alerts",
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
    <div className="flex flex-col rounded-[10px] border border-[#E5E5E2] bg-white p-5 transition-transform duration-200 hover:-translate-y-0.5">
      <p className="text-2xl font-bold tracking-tight text-[#0A0A0A] sm:text-3xl">{value}</p>
      <p className="mt-1 text-sm font-semibold text-[#0A0A0A]">{label}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-[#6B6B6B]">{description}</p>
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
      className="mx-auto mt-20 mb-8 max-w-5xl px-4 sm:px-6 lg:px-8"
      aria-label="Product capabilities"
    >
      <p className="text-center text-xs font-bold uppercase tracking-widest text-[#6B6B6B]">
        WHAT&apos;S UNDER THE HOOD
      </p>
      <div className="mt-6 grid grid-cols-2 gap-3.5 text-left md:grid-cols-4">
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
