import type { Metadata } from "next";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Privacy Policy — ReconDesk",
  description: "Privacy Policy for ReconDesk GST reconciliation platform (recondesk.in).",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy">
      <LegalSection title="1. Introduction">
        <p>
          ReconDesk is an online GST reconciliation software-as-a-service that helps Chartered
          Accountant (CA) firms in India compare GSTR-2B data against purchase registers and
          identify invoice-level matches and mismatches. The service is operated by{" "}
          <LegalStrong>Omkar Rajendra Kadam</LegalStrong> as a{" "}
          <LegalStrong>sole proprietorship</LegalStrong>, with operations
          registered in <LegalStrong>Hadapsar, Pune, Maharashtra</LegalStrong>.
        </p>
        <p>
          This Privacy Policy applies to the website <LegalStrong>recondesk.in</LegalStrong>{" "}
          and all related websites, applications, and services offered by ReconDesk
          (&quot;ReconDesk&quot;, &quot;we&quot;, &quot;us&quot;, or &quot;our&quot;). By using
          ReconDesk, you acknowledge that you have read this policy.
        </p>
      </LegalSection>

      <LegalSection title="2. Information We Collect">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <LegalStrong>Account information:</LegalStrong> name, email address,
            firm name, phone number, and similar profile details you provide when registering or
            updating your account.
          </li>
          <li>
            <LegalStrong>GST and reconciliation data:</LegalStrong> GSTR-2B JSON
            files, purchase register files (including Excel or CSV exports from tools such as
            Tally or Busy), client GSTINs, and derived reconciliation outputs (match/mismatch
            results, summaries, and audit-related metadata associated with runs you initiate).
          </li>
          <li>
            <LegalStrong>Usage data:</LegalStrong> reconciliation runs you create,
            timestamps of logins and material actions, and audit logs we maintain for security
            and compliance.
          </li>
          <li>
            <LegalStrong>Payment data:</LegalStrong> payments for subscriptions are
            processed by <LegalStrong>PhonePe and/or Razorpay</LegalStrong>. We do not store full
            payment card numbers or CVV on ReconDesk systems; such data is handled according to the
            respective payment processor&apos;s standards and policies.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="3. How We Use Your Information">
        <ul className="list-disc space-y-2 pl-5">
          <li>To perform GSTR-2B versus purchase register reconciliation and generate results for your firm.</li>
          <li>To create and manage your account, team access, and subscription or entitlements.</li>
          <li>To send transactional communications (for example, run completion or billing-related notices).</li>
          <li>To maintain security, prevent abuse, and comply with applicable law.</li>
        </ul>
        <p>
          We <LegalStrong>do not</LegalStrong> sell your personal information. We do
          not share your client or reconciliation data with third parties for their marketing
          purposes.
        </p>
      </LegalSection>

      <LegalSection title="4. File Handling &amp; Data Retention">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            Uploaded source files (such as GSTR-2B JSON and purchase register exports) are processed
            to complete reconciliation and are <LegalStrong>deleted after processing</LegalStrong>{" "}
            is complete, in line with our product design and security practices.
          </li>
          <li>
            Reconciliation results, mismatch records, and related account data that you keep in
            your workspace are retained in your account until you delete them or until account
            closure, subject to backups and legal holds.
          </li>
          <li>
            After account closure, we may retain certain information (including account and
            transactional records) for <LegalStrong>three (3) years</LegalStrong> where
            required for legal, regulatory, tax, or dispute-resolution purposes.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="5. Data Security">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            We use industry-standard protections including encryption of data{" "}
            <LegalStrong>at rest (AES-256)</LegalStrong> and{" "}
            <LegalStrong>in transit (TLS 1.2+)</LegalStrong>, implemented via our cloud providers.
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
      </LegalSection>

      <LegalSection title="6. Your Rights (DPDP Act, 2023)">
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
      </LegalSection>

      <LegalSection title="7. Third-Party Services">
        <p>ReconDesk relies on carefully selected processors, including:</p>
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <LegalStrong>Supabase</LegalStrong> — database, authentication, and related
            infrastructure. Their handling of data is governed by their documentation and terms.
          </li>
          <li>
            <LegalStrong>PhonePe / Razorpay</LegalStrong> — payment acceptance and related payment
            flows. Payment data is subject to the respective processor&apos;s privacy policy and
            security programme.
          </li>
          <li>
            <LegalStrong>Cloudflare R2</LegalStrong> — temporary storage for uploaded
            files during processing, where configured for your deployment.
          </li>
        </ul>
        <p>
          We encourage you to review the privacy policies of these providers for details on their
          subprocessors and regions.
        </p>
      </LegalSection>

      <LegalSection title="8. Cookies">
        <p>
          We use <LegalStrong>essential cookies</LegalStrong> and similar technologies needed
          to maintain authentication sessions and core security. We do not use advertising or
          third-party tracking cookies for profiling visitors across unrelated sites.
        </p>
      </LegalSection>

      <LegalSection title="9. Changes to This Policy">
        <p>
          We may update this Privacy Policy from time to time. If we make material changes, we will
          notify registered users by email to the address associated with their account and update
          the &quot;Last updated&quot; date at the top of this page.
        </p>
      </LegalSection>

      <LegalSection title="10. Contact">
        <p>
          <LegalStrong>Email:</LegalStrong>{" "}
          <a
            href="mailto:contact@recondesk.in"
            className="font-medium text-brand hover:underline"
          >
            contact@recondesk.in
          </a>
        </p>
        <p>
          <LegalStrong>Address:</LegalStrong> Hadapsar, Pune, Maharashtra, India
        </p>
        <p className="text-[#6B6B6B]">
          <LegalStrong>Effective date:</LegalStrong> May 2026
        </p>
      </LegalSection>
    </LegalPage>
  );
}
