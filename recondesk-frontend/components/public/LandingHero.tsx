"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

type ProofStat = {
  id: string;
  /** Target for animated count; null = static string display */
  target: number | null;
  suffix?: string;
  staticValue?: string;
  label: string;
  description: string;
};

const PROOF_STATS: ProofStat[] = [
  {
    id: "rules",
    target: 103,
    suffix: "+",
    label: "Logic rules",
    description: "GST scenarios covered end-to-end",
  },
  {
    id: "levels",
    target: 5,
    staticValue: undefined,
    label: "Matching levels",
    description: "L1 exact → L5 probable",
  },
  {
    id: "s175",
    target: null,
    staticValue: "17(5)",
    label: "Blocked credit",
    description: "Every Section 17(5) category flagged",
  },
  {
    id: "r37",
    target: 180,
    suffix: "-day",
    label: "Rule 37 clock",
    description: "Interest & payment deadline tracking",
  },
];

function easeOutCubic(t: number) {
  return 1 - Math.pow(1 - t, 3);
}

function useCountUp(target: number | null, active: boolean, durationMs = 1100) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (target == null || !active) {
      if (target != null && !active) setValue(0);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      setValue(Math.round(easeOutCubic(t) * target));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, active, durationMs]);

  return value;
}

function AnimatedStat({
  stat,
  active,
  overrideTarget,
}: {
  stat: ProofStat;
  active: boolean;
  overrideTarget?: number | null;
}) {
  const target = overrideTarget !== undefined ? overrideTarget : stat.target;
  const counted = useCountUp(target, active && target != null);

  let display: string;
  if (stat.staticValue) {
    display = stat.staticValue;
  } else if (target != null) {
    display = `${counted}${stat.suffix ?? ""}`;
  } else {
    display = "—";
  }

  return (
    <div className="relative flex flex-col border-t border-[#EBEBEC] pt-4 first:border-t-0 sm:border-t-0 sm:border-l sm:border-[#EBEBEC] sm:pl-5 sm:pt-0 first:sm:border-l-0 first:sm:pl-0">
      <p className="font-mono text-2xl font-semibold tracking-tight text-[var(--ink)] tabular-nums sm:text-3xl">
        {display}
      </p>
      <p className="mt-1 text-sm font-medium text-[var(--ink)]">{stat.label}</p>
      <p className="mt-1 text-xs leading-relaxed text-gray-500">{stat.description}</p>
    </div>
  );
}

function ProofStrip() {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);
  const [ruleTarget, setRuleTarget] = useState<number>(103);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setActive(true);
          io.disconnect();
        }
      },
      { threshold: 0.35 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/rules/summary`)
      .then((res) => {
        if (!res.ok) throw new Error("rules summary failed");
        return res.json() as Promise<{ total?: number }>;
      })
      .then((data) => {
        if (cancelled) return;
        if (typeof data.total === "number" && data.total > 0) {
          setRuleTarget(data.total);
        }
      })
      .catch(() => {
        /* keep 103 fallback */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div
      ref={ref}
      className="mx-auto mt-12 max-w-4xl border-y border-[#EBEBEC] bg-white/80 px-4 py-6 backdrop-blur-sm sm:mt-14 sm:px-8 sm:py-7"
      aria-label="Product proof points"
    >
      <div className="mb-5 flex flex-col items-start justify-between gap-1 sm:mb-6 sm:flex-row sm:items-end">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-400">
          Under the hood
        </p>
        <p className="text-[11px] text-gray-400">
          Live rule registry · matching engine · compliance clocks
        </p>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-6 md:grid-cols-4 md:gap-x-0">
        {PROOF_STATS.map((stat) => (
          <AnimatedStat
            key={stat.id}
            stat={stat}
            active={active}
            overrideTarget={stat.id === "rules" ? ruleTarget : undefined}
          />
        ))}
      </div>
    </div>
  );
}

export function LandingHero() {
  return (
    <section className="mx-auto max-w-6xl px-4 pb-10 pt-10 sm:px-6 sm:pb-14 sm:pt-14 lg:px-8">
      <div className="text-center">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
          ReconDesk
        </p>
        <h1 className="mx-auto mt-4 max-w-4xl text-[1.75rem] font-semibold leading-[1.15] tracking-tight text-[var(--ink)] sm:text-4xl sm:leading-[1.12] lg:text-[3.25rem]">
          Two files in. Clear decisions out.
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-gray-600 sm:mt-6 sm:text-lg">
          Upload your purchase register and GSTR-2B (or GSTR-1). Get five-level matching plus
          WHAT / WHY / NEXT on every issue — claim, hold, or dispute. No Tally bridge to install,
          sync, or babysit at month-end.
        </p>

        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:mt-10 sm:flex-row sm:gap-4">
          <Link
            href="/auth/signup"
            className="inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-[var(--ink)] px-6 text-sm font-semibold text-white shadow-[var(--shadow-soft)] transition-opacity hover:opacity-90 sm:w-auto"
          >
            Start Free — First 2 Runs Free
          </Link>
          <a
            href="#decision-layer"
            className="inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-white px-6 text-sm font-semibold text-[var(--ink)] shadow-[var(--shadow-soft)] transition hover:bg-[#F7F7F8] sm:w-auto"
          >
            See the Decision Layer
          </a>
        </div>

        <p className="mt-5 text-sm text-gray-500">
          No credit card · Works with Tally, Busy &amp; Excel exports · Results in minutes
        </p>
      </div>

      <ProofStrip />
    </section>
  );
}
