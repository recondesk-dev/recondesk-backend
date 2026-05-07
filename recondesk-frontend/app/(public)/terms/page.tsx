import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service — ReconDesk",
  description: "Terms of Service for using ReconDesk GST reconciliation (recondesk.in).",
};

export default function TermsPage() {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Last updated: May 2026
      </p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Terms of Service</h1>

      <div className="mt-10 space-y-10 text-sm leading-relaxed text-slate-300">
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">1. Acceptance of Terms</h2>
          <p>
            By accessing or using ReconDesk at recondesk.in or related services (&quot;Service&quot;), you
            agree to these Terms of Service (&quot;Terms&quot;). If you do not agree, do not use the Service.
          </p>
          <p>
            You represent that you are at least <strong className="text-slate-200">18 years of age</strong> and
            that you are using the Service on behalf of a{" "}
            <strong className="text-slate-200">registered business or professional practice in India</strong>{" "}
            (such as a CA firm) authorised to subscribe on its behalf.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">2. Description of Service</h2>
          <p>
            ReconDesk provides software that automates <strong className="text-slate-200">GSTR-2B versus purchase register</strong>{" "}
            reconciliation for CA firms, including matching, mismatch summaries, and related outputs
            designed to assist your review.
          </p>
          <p>
            <strong className="text-slate-200">Results are advisory.</strong> You and your firm remain solely
            responsible for validating outputs, professional judgement, and all GST filings, statutory
            forms, and representations made to tax authorities.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">3. Account Responsibilities</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>You are responsible for safeguarding passwords, API tokens (if any), and devices used to access the Service.</li>
            <li>You must not share login credentials in a manner that defeats access controls or exceeds your subscription.</li>
            <li>Staff or invited user accounts must be used only by the individual identified for that access.</li>
            <li>You are responsible for the accuracy of information you provide and for activity under your account, subject to reasonable dispute procedures.</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">4. Acceptable Use</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>Upload and process only files and data that your firm is lawfully authorised to handle for the relevant client.</li>
            <li>Do not attempt to reverse engineer, scrape, probe, or interfere with the Service except as permitted by law.</li>
            <li>Do not upload malware, exploits, or content designed to harm the platform or other users.</li>
            <li>Do not use the Service in violation of applicable laws, including the Information Technology Act, 2000 and GST law.</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">5. Subscription &amp; Billing</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              Subscription plans are offered on a <strong className="text-slate-200">monthly</strong> basis. Payments are
              collected through <strong className="text-slate-200">Razorpay</strong> as manual orders; we do not require
              automated recurring debit mandates through the platform unless separately communicated and agreed.
            </li>
            <li>
              Reconciliation <strong className="text-slate-200">runs</strong> are allocated per your plan and may carry
              forward for up to <strong className="text-slate-200">two (2) months</strong> as described on the pricing
              page, after which unused allotments may expire.
            </li>
            <li>
              <strong className="text-slate-200">Non-payment or failed renewal</strong> may result in suspension or
              downgrade after a reasonable <strong className="text-slate-200">seven (7) day</strong> grace period from
              the due date communicated in-app or by email, unless we agree otherwise in writing.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">6. Free Trial</h2>
          <p>
            Your first <strong className="text-slate-200">two (2) reconciliation runs</strong> may be offered free of
            charge without requiring a payment card, as published on our website. Free runs may{" "}
            <strong className="text-slate-200">expire after thirty (30) days</strong> if unused, unless we specify
            otherwise at signup.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">7. Limitation of Liability</h2>
          <p>
            Reconciliation assistance is a software tool, not legal, tax, or professional advice. To the fullest
            extent permitted by the <strong className="text-slate-200">Consumer Protection Act, 2019</strong>, the{" "}
            <strong className="text-slate-200">Information Technology Act, 2000</strong>, and other applicable law:
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              We are <strong className="text-slate-200">not liable</strong> for penalties, interest, disallowances,
              assessments, reputational loss, or indirect or consequential damages arising from GST filings or
              decisions made using or despite ReconDesk outputs.
            </li>
            <li>
              Our aggregate liability for proven direct damages arising from the Service in any three-month period is
              limited to the <strong className="text-slate-200">fees you paid to ReconDesk in the preceding three (3)
              months</strong>, except where liability cannot be limited by law.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">8. Intellectual Property</h2>
          <p>
            The ReconDesk platform, including software, workflows, algorithms, documentation, and user interface, is
            protected by intellectual property laws and remains our property or that of our licensors. We grant you a
            limited, non-exclusive, non-transferable right to use the Service during your subscription.
          </p>
          <p>
            <strong className="text-slate-200">Your data</strong> (files you upload and outputs we store in your account)
            remains yours, subject to licenses we need to operate the Service (hosting, processing, and support).
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">9. Termination</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>You may cancel your subscription at any time. Access generally continues through the end of the paid billing period unless we state otherwise.</li>
            <li>We may suspend or terminate accounts for material breach of these Terms, abuse, or legal requirement, with notice where practicable.</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">10. Governing Law</h2>
          <p>
            These Terms are governed by the <strong className="text-slate-200">laws of India</strong>. Subject to
            mandatory provisions of applicable statute, courts at{" "}
            <strong className="text-slate-200">Pune, Maharashtra</strong> shall have exclusive jurisdiction over
            disputes arising from these Terms or the Service.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">11. Contact</h2>
          <p>
            Operator: <strong className="text-slate-200">Omkar Rajendra Kadam</strong> (sole proprietorship)
          </p>
          <p>
            <strong className="text-slate-200">Email:</strong>{" "}
            <a
              href="mailto:contact@recondesk.in"
              className="font-medium text-[var(--accent)] hover:underline"
            >
              contact@recondesk.in
            </a>
          </p>
          <p className="text-slate-400">
            <strong className="text-slate-200">Effective date:</strong> May 2026
          </p>
        </section>

        <p className="pt-4 text-slate-500">
          <Link href="/" className="text-[var(--accent)] hover:underline">
            ← Back to home
          </Link>
        </p>
      </div>
    </article>
  );
}
