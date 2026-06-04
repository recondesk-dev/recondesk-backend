import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Refund Policy — ReconDesk",
  description: "Refund and cancellation policy for ReconDesk subscriptions (Razorpay).",
};

export default function RefundPage() {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Last updated: May 2026
      </p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Refund Policy</h1>

      <div className="mt-10 space-y-10 text-sm leading-relaxed text-slate-300">
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">1. Overview</h2>
          <p>
            ReconDesk offers <strong className="text-slate-200">monthly subscription plans</strong> for GST
            reconciliation software, with payments collected through{" "}
            <strong className="text-slate-200">Razorpay</strong>. This Refund Policy explains when refunds may be
            available and how to request them.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">2. Free Trial</h2>
          <p>
            Your first <strong className="text-slate-200">two (2) reconciliation runs</strong> may be provided free
            of charge with <strong className="text-slate-200">no payment</strong> required to evaluate the Service,
            as described on our website and at signup.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">3. Refund Eligibility</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              Refund requests received within <strong className="text-slate-200">forty-eight (48) hours</strong> of a
              successful subscription payment may be considered if{" "}
              <strong className="text-slate-200">no reconciliation runs</strong> have been consumed in that billing
              cycle.
            </li>
            <li>
              We do not typically provide refunds for <strong className="text-slate-200">partially used</strong>{" "}
              subscription months or where plan runs have already been consumed.
            </li>
            <li>
              If a <strong className="text-slate-200">technical failure on ReconDesk&apos;s side</strong> (not user
              error, file corruption attributable to you, or third-party downtime outside our control) prevents you
              from completing reconciliation despite a valid run entitlement, we will work with you in good faith to
              restore service—including, where appropriate, issuing a{" "}
              <strong className="text-slate-200">run credit</strong> or, in clear-cut cases, a{" "}
              <strong className="text-slate-200">full refund</strong> of the affected payment.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">4. How to Request a Refund</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              Email{" "}
              <a
                href="mailto:contact@recondesk.in?subject=Refund%20Request"
                className="font-medium text-brand hover:underline"
              >
                contact@recondesk.in
              </a>{" "}
              with the subject line <strong className="text-slate-200">&quot;Refund Request&quot;</strong>.
            </li>
            <li>
              Include your <strong className="text-slate-200">registered email address</strong> and your{" "}
              <strong className="text-slate-200">Razorpay payment reference</strong> or order ID.
            </li>
            <li>We aim to respond within <strong className="text-slate-200">three (3) business days</strong>.</li>
            <li>
              Approved refunds are typically processed within{" "}
              <strong className="text-slate-200">five (5) to seven (7) business days</strong> through the original
              payment method, subject to Razorpay and banking timelines.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">5. Cancellation</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>You may cancel your subscription at any time; <strong className="text-slate-200">no cancellation fee</strong> applies.</li>
            <li>
              Access generally continues until the end of the <strong className="text-slate-200">current paid billing month</strong>.
            </li>
            <li>
              We do not refund fees for unused days within the current billing period after you cancel, except where
              this Refund Policy expressly permits (for example, an approved refund under Section 3).
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">6. Contact</h2>
          <p>
            <strong className="text-slate-200">Email:</strong>{" "}
            <a
              href="mailto:contact@recondesk.in"
              className="font-medium text-brand hover:underline"
            >
              contact@recondesk.in
            </a>
          </p>
          <p className="text-slate-400">
            <strong className="text-slate-200">Effective date:</strong> May 2026
          </p>
        </section>

        <p className="pt-4 text-slate-500">
          <Link href="/" className="text-brand hover:underline">
            ← Back to home
          </Link>
        </p>
      </div>
    </article>
  );
}
