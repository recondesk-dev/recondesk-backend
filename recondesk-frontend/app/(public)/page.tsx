import Link from "next/link";
import { ClipboardList, GitMerge, Upload } from "lucide-react";

function Section({
  id,
  className = "",
  children,
}: {
  id?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={`mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20 lg:px-8 ${className}`}>
      {children}
    </section>
  );
}

export default function LandingPage() {
  return (
    <>
      {/* Hero */}
      <Section className="pb-12 pt-10 sm:pb-16 sm:pt-14">
        <div className="text-center">
          <h1 className="mx-auto max-w-4xl text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-5xl">
            Find the ITC Your Clients Are Missing Every Month
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-400 sm:text-xl">
            GSTR-2B reconciliation for CA firms. Upload 2 files. Results in 60 seconds.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-lg bg-[var(--accent)] px-6 text-sm font-semibold text-white shadow-lg shadow-[var(--accent)]/25 transition hover:opacity-95 sm:w-auto"
            >
              Start Free — First 2 Runs Free
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-lg border border-white/15 bg-white/5 px-6 text-sm font-semibold text-white transition hover:bg-white/10 sm:w-auto"
            >
              See How It Works
            </a>
          </div>
          <p className="mt-6 text-sm text-slate-400">
            Plans from ₹399/month · No credit card to start
          </p>
          <div className="mx-auto mt-8 max-w-3xl rounded-xl border border-white/10 bg-white/[0.03] px-4 py-4 text-sm text-slate-300 sm:px-6">
            <p className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-center sm:gap-x-6 sm:gap-y-2">
              <span>✓ No credit card required</span>
              <span className="hidden text-white/25 sm:inline" aria-hidden>
                ·
              </span>
              <span>✓ Works with Tally, Busy &amp; Excel</span>
              <span className="hidden text-white/25 sm:inline" aria-hidden>
                ·
              </span>
              <span>✓ First 2 runs completely free</span>
            </p>
          </div>
        </div>
      </Section>

      {/* Pain */}
      <Section className="border-t border-white/10 bg-[#0a0c10]/60 py-14">
        <h2 className="text-center text-2xl font-semibold text-white sm:text-3xl">Sound familiar?</h2>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {[
            "3–8 hours per client, per month on manual VLOOKUP reconciliation",
            "ITC mismatches discovered after filing deadline — penalties already hit",
            "30–50 clients. One wrong cell. No audit trail.",
          ].map((text) => (
            <div
              key={text}
              className="rounded-2xl border border-white/10 bg-[#13161f] p-6 text-slate-300 shadow-sm"
            >
              <p className="text-sm leading-relaxed sm:text-base">{text}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* How it works */}
      <Section id="how-it-works" className="scroll-mt-24">
        <h2 className="text-center text-2xl font-semibold text-white sm:text-3xl">How ReconDesk Works</h2>
        <ul className="mt-12 grid gap-8 md:grid-cols-3">
          <li className="flex flex-col items-center text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--accent)]/15 text-[var(--accent)]">
              <Upload className="h-7 w-7" aria-hidden />
            </div>
            <h3 className="mt-4 text-base font-semibold text-white">1. Upload</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              GSTR-2B JSON + Purchase Register (Tally, Busy, or any Excel — auto-detected)
            </p>
          </li>
          <li className="flex flex-col items-center text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--accent)]/15 text-[var(--accent)]">
              <GitMerge className="h-7 w-7" aria-hidden />
            </div>
            <h3 className="mt-4 text-base font-semibold text-white">2. Match</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              ReconDesk matches 5,000+ invoices in 60 seconds using 5-level matching
            </p>
          </li>
          <li className="flex flex-col items-center text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--accent)]/15 text-[var(--accent)]">
              <ClipboardList className="h-7 w-7" aria-hidden />
            </div>
            <h3 className="mt-4 text-base font-semibold text-white">3. Decide</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              Every mismatch explained: What is wrong, Why it happened, What to do next
            </p>
          </li>
        </ul>

        {/* Mock result card */}
        <div className="mx-auto mt-14 max-w-lg rounded-2xl border border-white/10 bg-[#13161f] p-6 shadow-xl">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sample run summary</p>
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500">ITC at Risk</p>
              <p className="mt-1 font-mono text-lg font-semibold text-amber-400">₹1,24,500</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Matched</p>
              <p className="mt-1 font-mono text-lg font-semibold text-emerald-400">847</p>
              <p className="text-[10px] text-slate-500">invoices</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Mismatches</p>
              <p className="mt-1 font-mono text-lg font-semibold text-white">23</p>
            </div>
            <div className="col-span-2 flex flex-wrap gap-2 sm:col-span-1 sm:flex-col sm:justify-end">
              <span className="inline-flex rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-300">
                Claim Now
              </span>
              <span className="inline-flex rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-200">
                Chase Supplier
              </span>
              <span className="inline-flex rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-medium text-rose-200">
                Reverse Entry
              </span>
            </div>
          </div>
        </div>
      </Section>

      {/* FAQ */}
      <Section className="border-t border-white/10 bg-[#0a0c10]/60">
        <h2 className="text-center text-2xl font-semibold text-white sm:text-3xl">
          Questions CAs Ask Before Signing Up
        </h2>
        <dl className="mx-auto mt-10 max-w-3xl space-y-6">
          {[
            {
              q: "Is my client's data safe?",
              a: "Files are deleted after processing. All data is encrypted at rest and in transit. We never share your data with third parties.",
            },
            {
              q: "Which accounting software works?",
              a: "Tally, Busy, or any Excel format — source software is auto-detected on upload.",
            },
            {
              q: "How long does reconciliation take?",
              a: "Under 60 seconds for 1,000 invoices.",
            },
            {
              q: "Can I try before paying?",
              a: "Yes. Your first 2 reconciliations are completely free. No credit card required.",
            },
            {
              q: "Can my staff use it?",
              a: "Yes. Invite team members. Staff can run reconciliations; you review and finalize results.",
            },
            {
              q: "What happens to unused runs?",
              a: "Solo plans: runs expire monthly. Firm Growth and Pro plans: unused runs carry over for up to 2 months.",
            },
            {
              q: "How does billing work?",
              a: "Manual monthly payment via Razorpay. No auto-debit. You choose when to renew.",
            },
          ].map(({ q, a }) => (
            <div key={q} className="rounded-xl border border-white/10 bg-[#13161f] px-5 py-4">
              <dt className="font-semibold text-white">{q}</dt>
              <dd className="mt-2 text-sm leading-relaxed text-slate-400">{a}</dd>
            </div>
          ))}
        </dl>
      </Section>

      {/* Final CTA */}
      <Section className="border-t border-white/10">
        <div className="mx-auto max-w-2xl rounded-3xl border border-[var(--accent)]/30 bg-gradient-to-b from-[var(--accent)]/10 to-transparent px-6 py-12 text-center sm:px-10">
          <h2 className="text-2xl font-semibold text-white sm:text-3xl">Stop Losing ITC. Start Recovering It.</h2>
          <p className="mt-4 text-slate-400">
            First 2 reconciliations free. No credit card required.
          </p>
          <Link
            href="/auth/signup"
            className="mt-8 inline-flex min-h-[48px] items-center justify-center rounded-lg bg-[var(--accent)] px-8 text-sm font-semibold text-white transition hover:opacity-95"
          >
            Get Started Free →
          </Link>
        </div>
      </Section>
    </>
  );
}
