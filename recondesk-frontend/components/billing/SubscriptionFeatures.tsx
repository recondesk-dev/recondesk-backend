type FeatureLine = {
  title: string;
  detail: string;
};

type Chapter = {
  index: string;
  label: string;
  title: string;
  kicker: string;
  accent: string;
  lines: FeatureLine[];
};

const CHAPTERS: Chapter[] = [
  {
    index: "01",
    label: "Core reconciliation",
    title: "The engine",
    kicker: "From raw filings to a clear desk — purchase side and sales side.",
    accent: "from-[rgba(17,17,17,0.06)] via-transparent to-[rgba(16,185,129,0.08)]",
    lines: [
      {
        title: "GSTR-2B ↔ Purchase Register",
        detail:
          "Upload 2B (JSON) + PR (Excel/CSV). Auto-detects Tally, Busy, or generic Excel.",
      },
      {
        title: "Multi-level matching",
        detail:
          "GSTIN + invoice, fuzzy invoice, amount/date tolerances, vendor-name fuzzy match, review & probable matches.",
      },
      {
        title: "Results buckets",
        detail:
          "Matched, Review Required, Duplicates, ITC at Risk, Missed ITC, Rule 37, Section 17(5), GSTR-3B check.",
      },
      {
        title: "Decision layer",
        detail:
          "What / Why / Next on every issue — notes, bulk status updates, finalize the run.",
      },
      {
        title: "GSTR-1 ↔ Sales Register",
        detail:
          "Mismatches, 3B tie-out, Table 13 / docs issued, HSN checks, amendments.",
      },
    ],
  },
  {
    index: "02",
    label: "Compliance & intelligence",
    title: "The watchtower",
    kicker: "Catch risk early. See the portfolio the way a partner would.",
    accent: "from-[rgba(16,185,129,0.1)] via-transparent to-[rgba(17,17,17,0.04)]",
    lines: [
      {
        title: "Rule 37 tracking",
        detail: "180-day payment warnings and overdue clocks before ITC reverses.",
      },
      {
        title: "Section 17(5) flags",
        detail: "Blocked-credit HSN alerts so wrongful claims never slip through.",
      },
      {
        title: "90+ GST rules",
        detail: "Matching, ITC, normalization, period, supplier, and decision rules — always on.",
      },
      {
        title: "Chronic risk",
        detail: "Invoices that stay unmatched across consecutive periods surface automatically.",
      },
      {
        title: "Supplier intelligence",
        detail: "Filing reliability and mismatch patterns per vendor — not just a flat list.",
      },
      {
        title: "Portfolio dashboard",
        detail:
          "Priority clients, missed ITC amounts, risk levels, return-period board, ITC trends.",
      },
    ],
  },
  {
    index: "03",
    label: "Firm workflow",
    title: "The firm desk",
    kicker: "Built for CA firms — owner reviews, staff executes, nothing falls through.",
    accent: "from-[rgba(17,17,17,0.05)] via-transparent to-transparent",
    lines: [
      {
        title: "Admin vs Staff roles",
        detail: "Client assignment so every member only sees what they own.",
      },
      {
        title: "Team invites & audit log",
        detail: "Invite by email. Activity trail for every sensitive action.",
      },
      {
        title: "Onboarding wizard",
        detail: "First client + first run in one guided pass — live in minutes.",
      },
      {
        title: "Per-client import mappings",
        detail: "Column maps saved and reused — no remapping every month.",
      },
      {
        title: "Auto-approve threshold",
        detail: "High-confidence Review Required items can clear themselves.",
      },
      {
        title: "GSTN connect (OTP)",
        detail: "Autofetch GSTR-2B & IMS instead of hunting for portal downloads.",
      },
    ],
  },
  {
    index: "04",
    label: "Client communication",
    title: "The client line",
    kicker: "Collect files. Chase suppliers. Leave a paper trail clients respect.",
    accent: "from-[rgba(16,185,129,0.08)] via-transparent to-[rgba(17,17,17,0.05)]",
    lines: [
      {
        title: "Upload request links",
        detail: "Clients drop files on a tokenized page — no login, no friction.",
      },
      {
        title: "Communication center",
        detail: "Upload requests, messages, and follow-up history in one place.",
      },
      {
        title: "Supplier follow-up letters",
        detail: "Generate letters from results with a full audit trail.",
      },
      {
        title: "Excel & PDF exports",
        detail: "Full workbooks, filtered risk sheets, and reconciliation PDF reports.",
      },
      {
        title: "Follow-up audit export",
        detail: "Client-level history you can hand to a partner or keep on file.",
      },
    ],
  },
];

const BUCKET_STRIP = [
  "Matched",
  "Review Required",
  "Duplicates",
  "ITC at Risk",
  "Missed ITC",
  "Rule 37",
  "Section 17(5)",
  "GSTR-3B Check",
  "GSTR-1 Tie-out",
  "Follow-up Log",
] as const;

const TRUST = [
  "Tally · Busy · Excel",
  "Encrypted in transit & at rest",
  "Per-firm isolation",
  "2 free reconciliations",
  "Manual Razorpay renew",
] as const;

type Props = {
  /** Compact variant for the dashboard billing page */
  compact?: boolean;
};

export function SubscriptionFeatures({ compact = false }: Props) {
  return (
    <section
      className={
        compact
          ? "space-y-8"
          : "mx-auto mt-24 max-w-6xl"
      }
      aria-labelledby="subscription-features-heading"
    >
      <div className={compact ? "text-left" : "text-center"}>
        <h2
          id="subscription-features-heading"
          className={`font-semibold tracking-tight text-[var(--ink)] ${
            compact
              ? "text-3xl leading-[1.1] sm:text-4xl"
              : "text-4xl leading-[1.05] sm:text-5xl md:text-[3.5rem]"
          }`}
        >
          Full desk. Every plan.
          <br className="hidden sm:block" />
          <span className={compact ? "text-gray-400" : "text-emerald-700/80"}>
            {" "}
            Nothing held back.
          </span>
        </h2>
        <p
          className={`mt-4 max-w-2xl text-base text-gray-600 ${
            compact ? "" : "mx-auto"
          }`}
        >
          You don&apos;t buy features — you buy GSTIN capacity. The matching engine,
          compliance watchtower, firm workflow, and client line ship with every plan.
        </p>
      </div>

      {/* Moving capability strip — shows breadth without a boring checklist */}
      <div
        className={`relative overflow-hidden rounded-full border border-black/[0.04] ${
          compact ? "mt-6 bg-[#F7F7F8]" : "mt-10 bg-white/50"
        }`}
      >
        <div
          className={`pointer-events-none absolute inset-y-0 left-0 z-10 w-12 bg-gradient-to-r to-transparent ${
            compact ? "from-[#F7F7F8]" : "from-[var(--bg)]"
          }`}
        />
        <div
          className={`pointer-events-none absolute inset-y-0 right-0 z-10 w-12 bg-gradient-to-l to-transparent ${
            compact ? "from-[#F7F7F8]" : "from-[var(--bg)]"
          }`}
        />
        <div className="flex w-max animate-[landing-trust-marquee_32s_linear_infinite] gap-3 py-3 pl-4 motion-reduce:animate-none">
          {[...BUCKET_STRIP, ...BUCKET_STRIP].map((label, i) => (
            <span
              key={`${label}-${i}`}
              className="inline-flex shrink-0 items-center gap-2 rounded-full bg-white px-3.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm ring-1 ring-black/[0.04]"
            >
              <span className="h-1 w-1 rounded-full bg-emerald-600" aria-hidden />
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className={`space-y-5 ${compact ? "mt-6" : "mt-12"}`}>
        {CHAPTERS.map((chapter, idx) => (
          <article
            key={chapter.index}
            className={`subscription-feature-chapter relative overflow-hidden rounded-[1.75rem] border border-white/70 bg-gradient-to-br ${chapter.accent} bg-white/65 p-6 shadow-[var(--shadow-soft)] backdrop-blur-md sm:p-8 ${
              idx % 2 === 1 ? "sm:ml-6 lg:ml-12" : "sm:mr-6 lg:mr-12"
            }`}
          >
            <div className="relative grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)] lg:gap-10">
              <header className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
                  {chapter.label}
                </p>
                <h3 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--ink)] sm:text-[1.75rem]">
                  {chapter.title}
                </h3>
                <p
                  className="mt-1 text-4xl font-semibold leading-none tracking-tighter text-[var(--ink)]/10 sm:text-5xl"
                  aria-hidden
                >
                  {chapter.index}
                </p>
                <p className="mt-3 max-w-sm text-sm leading-relaxed text-gray-600">
                  {chapter.kicker}
                </p>
                <div
                  className="mt-5 h-px w-16 bg-gradient-to-r from-[var(--ink)]/40 to-transparent"
                  aria-hidden
                />
              </header>

              <ul className="relative grid gap-4 sm:grid-cols-2 sm:gap-x-6 sm:gap-y-5">
                {chapter.lines.map((line) => (
                  <li key={line.title} className="min-w-0">
                    <p className="text-[13px] font-semibold tracking-tight text-[var(--ink)]">
                      {line.title}
                    </p>
                    <p className="mt-1 text-[13px] leading-relaxed text-gray-600">
                      {line.detail}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          </article>
        ))}
      </div>

      <div
        className={`flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-gray-600 ${
          compact
            ? "rounded-[1.25rem] bg-[#F7F7F8] px-5 py-4"
            : "justify-center rounded-[1.25rem] bg-white/60 px-5 py-4 shadow-[var(--shadow-soft)] backdrop-blur-sm"
        }`}
      >
        {TRUST.map((t) => (
          <span key={t} className="inline-flex items-center gap-2">
            <span className="h-1 w-1 rounded-full bg-[var(--ink)]" aria-hidden />
            {t}
          </span>
        ))}
      </div>
    </section>
  );
}
