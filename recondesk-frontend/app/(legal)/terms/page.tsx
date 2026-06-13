import type { Metadata } from "next";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Terms of Service — ReconDesk",
  description: "Terms of Service for using ReconDesk GST reconciliation (recondesk.in).",
};

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service">
      <LegalSection title="1. Acceptance of Terms">
        <p>
          By accessing or using ReconDesk at recondesk.in or related services (&quot;Service&quot;), you
          agree to these Terms of Service (&quot;Terms&quot;). If you do not agree, do not use the Service.
        </p>
        <p>
          You represent that you are at least <LegalStrong>18 years of age</LegalStrong> and
          that you are using the Service on behalf of a{" "}
          <LegalStrong>registered business or professional practice in India</LegalStrong>{" "}
          (such as a CA firm) authorised to subscribe on its behalf.
        </p>
      </LegalSection>

      <LegalSection title="2. Description of Service">
        <p>
          ReconDesk provides software that automates <LegalStrong>GSTR-2B versus purchase register</LegalStrong>{" "}
          reconciliation for CA firms, including matching, mismatch summaries, and related outputs
          designed to assist your review.
        </p>
        <p>
          <LegalStrong>Results are advisory.</LegalStrong> You and your firm remain solely
          responsible for validating outputs, professional judgement, and all GST filings, statutory
          forms, and representations made to tax authorities.
        </p>
      </LegalSection>

      <LegalSection title="3. Account Responsibilities">
        <ul className="list-disc space-y-2 pl-5">
          <li>You are responsible for safeguarding passwords, API tokens (if any), and devices used to access the Service.</li>
          <li>You must not share login credentials in a manner that defeats access controls or exceeds your subscription.</li>
          <li>Staff or invited user accounts must be used only by the individual identified for that access.</li>
          <li>You are responsible for the accuracy of information you provide and for activity under your account, subject to reasonable dispute procedures.</li>
        </ul>
      </LegalSection>

      <LegalSection title="4. Acceptable Use">
        <ul className="list-disc space-y-2 pl-5">
          <li>Upload and process only files and data that your firm is lawfully authorised to handle for the relevant client.</li>
          <li>Do not attempt to reverse engineer, scrape, probe, or interfere with the Service except as permitted by law.</li>
          <li>Do not upload malware, exploits, or content designed to harm the platform or other users.</li>
          <li>Do not use the Service in violation of applicable laws, including the Information Technology Act, 2000 and GST law.</li>
        </ul>
      </LegalSection>

      <LegalSection title="5. Subscription &amp; Billing">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            Subscription plans are offered on a <LegalStrong>monthly</LegalStrong> basis. Payments are
            collected through <LegalStrong>PhonePe and/or Razorpay</LegalStrong> as manual orders; we do
            not require automated recurring debit mandates through the platform unless separately
            communicated and agreed.
          </li>
          <li>
            Reconciliation <LegalStrong>runs</LegalStrong> are allocated per your plan and may carry
            forward for up to <LegalStrong>two (2) months</LegalStrong> as described on the pricing
            page, after which unused allotments may expire.
          </li>
          <li>
            <LegalStrong>Non-payment or failed renewal</LegalStrong> may result in suspension or
            downgrade after a reasonable <LegalStrong>seven (7) day</LegalStrong> grace period from
            the due date communicated in-app or by email, unless we agree otherwise in writing.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="6. Free Trial">
        <p>
          Your first <LegalStrong>two (2) reconciliation runs</LegalStrong> may be offered free of
          charge without requiring a payment card, as published on our website. Free runs may{" "}
          <LegalStrong>expire after thirty (30) days</LegalStrong> if unused, unless we specify
          otherwise at signup.
        </p>
      </LegalSection>

      <LegalSection title="7. Limitation of Liability">
        <p>
          Reconciliation assistance is a software tool, not legal, tax, or professional advice. To the fullest
          extent permitted by the <LegalStrong>Consumer Protection Act, 2019</LegalStrong>, the{" "}
          <LegalStrong>Information Technology Act, 2000</LegalStrong>, and other applicable law:
        </p>
        <ul className="list-disc space-y-2 pl-5">
          <li>
            We are <LegalStrong>not liable</LegalStrong> for penalties, interest, disallowances,
            assessments, reputational loss, or indirect or consequential damages arising from GST filings or
            decisions made using or despite ReconDesk outputs.
          </li>
          <li>
            Our aggregate liability for proven direct damages arising from the Service in any three-month period is
            limited to the <LegalStrong>fees you paid to ReconDesk in the preceding three (3)
            months</LegalStrong>, except where liability cannot be limited by law.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="8. Intellectual Property">
        <p>
          The ReconDesk platform, including software, workflows, algorithms, documentation, and user interface, is
          protected by intellectual property laws and remains our property or that of our licensors. We grant you a
          limited, non-exclusive, non-transferable right to use the Service during your subscription.
        </p>
        <p>
          <LegalStrong>Your data</LegalStrong> (files you upload and outputs we store in your account)
          remains yours, subject to licenses we need to operate the Service (hosting, processing, and support).
        </p>
      </LegalSection>

      <LegalSection title="9. Termination">
        <ul className="list-disc space-y-2 pl-5">
          <li>You may cancel your subscription at any time. Access generally continues through the end of the paid billing period unless we state otherwise.</li>
          <li>We may suspend or terminate accounts for material breach of these Terms, abuse, or legal requirement, with notice where practicable.</li>
        </ul>
      </LegalSection>

      <LegalSection title="10. Governing Law">
        <p>
          These Terms are governed by the <LegalStrong>laws of India</LegalStrong>. Subject to
          mandatory provisions of applicable statute, courts at{" "}
          <LegalStrong>Pune, Maharashtra</LegalStrong> shall have exclusive jurisdiction over
          disputes arising from these Terms or the Service.
        </p>
      </LegalSection>

      <LegalSection title="11. Contact">
        <p>
          Operator: <LegalStrong>Omkar Rajendra Kadam</LegalStrong> (sole proprietorship)
        </p>
        <p>
          <LegalStrong>Email:</LegalStrong>{" "}
          <a
            href="mailto:contact@recondesk.in"
            className="font-medium text-brand hover:underline"
          >
            contact@recondesk.in
          </a>
        </p>
        <p className="text-[#6B6B6B]">
          <LegalStrong>Effective date:</LegalStrong> May 2026
        </p>
      </LegalSection>
    </LegalPage>
  );
}
