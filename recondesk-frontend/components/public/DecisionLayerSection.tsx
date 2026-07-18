import Link from "next/link";

export function DecisionLayerSection() {
  return (
    <section
      id="decision-layer"
      className="scroll-mt-20 border-y border-[#EBEBEC] bg-white py-12 sm:scroll-mt-24 sm:py-16"
    >
      <div className="mx-auto max-w-3xl px-4 text-center sm:px-6 lg:px-8">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-400">
          Decision Layer
        </p>
        <h2 className="mt-3 text-2xl font-semibold tracking-tight text-[var(--ink)] sm:text-3xl">
          Not just “mismatch found.” What to do next.
        </h2>
        <p className="mt-4 text-base leading-relaxed text-gray-600 sm:text-lg">
          Most tools stop when the numbers don&apos;t line up. ReconDesk&apos;s Decision Layer
          goes further: for each invoice it states{" "}
          <span className="font-medium text-[var(--ink)]">what</span> went wrong,{" "}
          <span className="font-medium text-[var(--ink)]">why</span> it matters under GST
          (Rule&nbsp;37, Section&nbsp;17(5), and more), and the{" "}
          <span className="font-medium text-[var(--ink)]">next</span> action — claim, hold, or
          dispute — so your team can close the period instead of re-reading a spreadsheet.
        </p>
        <p className="mt-6 text-sm leading-relaxed text-gray-500">
          Rule&nbsp;37 tracking, Section&nbsp;17(5) flags, and Audit Observations ship in the
          same plan — not locked behind a separate “Audit Engine” upsell.
        </p>
        <div className="mt-8">
          <Link
            href="/auth/signup"
            className="inline-flex min-h-[44px] items-center justify-center rounded-full border border-[#E5E5E5] bg-[var(--bg)] px-5 text-sm font-semibold text-[var(--ink)] transition hover:bg-[#EFEFEF]"
          >
            Try it on your next client →
          </Link>
        </div>
      </div>
    </section>
  );
}
