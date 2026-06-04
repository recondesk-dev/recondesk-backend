import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy — ReconDesk",
  description: "Privacy Policy for ReconDesk GST reconciliation platform (recondesk.in).",
};

export default function PrivacyPage() {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Last updated: May 2026
      </p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Privacy Policy</h1>

      <div className="mt-10 space-y-10 text-sm leading-relaxed text-slate-300">
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">1. Introduction</h2>
          <p>
            ReconDesk is an online GST reconciliation software-as-a-service that helps Chartered
            Accountant (CA) firms in India compare GSTR-2B data against purchase registers and
            identify invoice-level matches and mismatches. The service is operated by{" "}
            <strong className="text-slate-200">Omkar Rajendra Kadam</strong> as a{" "}
            <strong className="text-slate-200">sole proprietorship</strong>, with operations
            registered in <strong className="text-slate-200">Hadapsar, Pune, Maharashtra</strong>.
          </p>
          <p>
            This Privacy Policy applies to the website <strong className="text-slate-200">recondesk.in</strong>{" "}
            and all related websites, applications, and services offered by ReconDesk
            (&quot;ReconDesk&quot;, &quot;we&quot;, &quot;us&quot;, or &quot;our&quot;). By using
            ReconDesk, you acknowledge that you have read this policy.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">2. Information We Collect</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="text-slate-200">Account information:</strong> name, email address,
              firm name, phone number, and similar profile details you provide when registering or
              updating your account.
            </li>
            <li>
              <strong className="text-slate-200">GST and reconciliation data:</strong> GSTR-2B JSON
              files, purchase register files (including Excel or CSV exports from tools such as
              Tally or Busy), client GSTINs, and derived reconciliation outputs (match/mismatch
              results, summaries, and audit-related metadata associated with runs you initiate).
            </li>
            <li>
              <strong className="text-slate-200">Usage data:</strong> reconciliation runs you create,
              timestamps of logins and material actions, and audit logs we maintain for security
              and compliance.
            </li>
            <li>
              <strong className="text-slate-200">Payment data:</strong> payments for subscriptions are
              processed by Razorpay. We do not store full payment card numbers or CVV on ReconDesk
              systems; such data is handled according to Razorpay&apos;s standards and policies.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">3. How We Use Your Information</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>To perform GSTR-2B versus purchase register reconciliation and generate results for your firm.</li>
            <li>To create and manage your account, team access, and subscription or entitlements.</li>
            <li>To send transactional communications (for example, run completion or billing-related notices).</li>
            <li>To maintain security, prevent abuse, and comply with applicable law.</li>
          </ul>
          <p>
            We <strong className="text-slate-200">do not</strong> sell your personal information. We do
            not share your client or reconciliation data with third parties for their marketing
            purposes.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">4. File Handling &amp; Data Retention</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              Uploaded source files (such as GSTR-2B JSON and purchase register exports) are processed
              to complete reconciliation and are <strong className="text-slate-200">deleted after processing</strong>{" "}
              is complete, in line with our product design and security practices.
            </li>
            <li>
              Reconciliation results, mismatch records, and related account data that you keep in
              your workspace are retained in your account until you delete them or until account
              closure, subject to backups and legal holds.
            </li>
            <li>
              After account closure, we may retain certain information (including account and
              transactional records) for <strong className="text-slate-200">three (3) years</strong> where
              required for legal, regulatory, tax, or dispute-resolution purposes.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">5. Data Security</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              We use industry-standard protections including encryption of data{" "}
              <strong className="text-slate-200">at rest (AES-256)</strong> and{" "}
              <strong className="text-slate-200">in transit (TLS 1.2+)</strong>, implemented via our cloud providers.
            </li>
            <li>
              Access within your firm is constrained by product controls (for example, staff may only
              access clients or data assigned or permitted under your workspace rules).
            </li>
            <li>
              We maintain audit logs for sensitive actions appropriate to a B2B reconciliation
              product serving CA firms.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">6. Your Rights (DPDP Act, 2023)</h2>
          <p>
            Where the Digital Personal Data Protection Act, 2023 and applicable rules apply, you may have
            rights including:
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>Right to access personal data we process about you in connection with ReconDesk.</li>
            <li>Right to request correction of inaccurate or incomplete personal data.</li>
            <li>Right to request erasure, including through account deletion, subject to legal retention.</li>
            <li>Right to grievance redressal as described under applicable law.</li>
          </ul>
          <p>
            To exercise these rights or raise a concern, email{" "}
            <a
              href="mailto:contact@recondesk.in"
              className="font-medium text-brand hover:underline"
            >
              contact@recondesk.in
            </a>
            . We may need to verify your identity before fulfilling certain requests.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">7. Third-Party Services</h2>
          <p>ReconDesk relies on carefully selected processors, including:</p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="text-slate-200">Supabase</strong> — database, authentication, and related
              infrastructure. Their handling of data is governed by their documentation and terms.
            </li>
            <li>
              <strong className="text-slate-200">Razorpay</strong> — payment acceptance and related payment
              flows. Payment data is subject to Razorpay&apos;s privacy policy and security programme.
            </li>
            <li>
              <strong className="text-slate-200">Cloudflare R2</strong> — temporary storage for uploaded
              files during processing, where configured for your deployment.
            </li>
          </ul>
          <p>
            We encourage you to review the privacy policies of these providers for details on their
            subprocessors and regions.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">8. Cookies</h2>
          <p>
            We use <strong className="text-slate-200">essential cookies</strong> and similar technologies needed
            to maintain authentication sessions and core security. We do not use advertising or
            third-party tracking cookies for profiling visitors across unrelated sites.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">9. Changes to This Policy</h2>
          <p>
            We may update this Privacy Policy from time to time. If we make material changes, we will
            notify registered users by email to the address associated with their account and update
            the &quot;Last updated&quot; date at the top of this page.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">10. Contact</h2>
          <p>
            <strong className="text-slate-200">Email:</strong>{" "}
            <a
              href="mailto:contact@recondesk.in"
              className="font-medium text-brand hover:underline"
            >
              contact@recondesk.in
            </a>
          </p>
          <p>
            <strong className="text-slate-200">Address:</strong> Hadapsar, Pune, Maharashtra, India
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
