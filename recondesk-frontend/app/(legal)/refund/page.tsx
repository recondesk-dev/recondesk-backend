import type { Metadata } from "next";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Refund Policy — ReconDesk",
  description: "Refund and cancellation policy for ReconDesk subscriptions (Razorpay).",
};

export default function RefundPage() {
  return (
    <LegalPage title="Refund Policy">
      <LegalSection title="1. Overview">
        <p>
          ReconDesk offers <LegalStrong>monthly subscription plans</LegalStrong> for GST
          reconciliation software, with payments collected through{" "}
          <LegalStrong>Razorpay</LegalStrong>. This Refund Policy explains when refunds may be
          available and how to request them.
        </p>
      </LegalSection>

      <LegalSection title="2. Free Trial">
        <p>
          Your first <LegalStrong>two (2) reconciliation runs</LegalStrong> may be provided free
          of charge with <LegalStrong>no payment</LegalStrong> required to evaluate the Service,
          as described on our website and at signup.
        </p>
      </LegalSection>

      <LegalSection title="3. Refund Eligibility">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            Refund requests received within <LegalStrong>forty-eight (48) hours</LegalStrong> of a
            successful subscription payment may be considered if{" "}
            <LegalStrong>no reconciliation runs</LegalStrong> have been consumed in that billing
            cycle.
          </li>
          <li>
            We do not typically provide refunds for <LegalStrong>partially used</LegalStrong>{" "}
            subscription months or where plan runs have already been consumed.
          </li>
          <li>
            If a <LegalStrong>technical failure on ReconDesk&apos;s side</LegalStrong> (not user
            error, file corruption attributable to you, or third-party downtime outside our control) prevents you
            from completing reconciliation despite a valid run entitlement, we will work with you in good faith to
            restore service—including, where appropriate, issuing a{" "}
            <LegalStrong>run credit</LegalStrong> or, in clear-cut cases, a{" "}
            <LegalStrong>full refund</LegalStrong> of the affected payment.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="4. How to Request a Refund">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            Email{" "}
            <a
              href="mailto:contact@recondesk.in?subject=Refund%20Request"
              className="font-medium text-brand hover:underline"
            >
              contact@recondesk.in
            </a>{" "}
            with the subject line <LegalStrong>&quot;Refund Request&quot;</LegalStrong>.
          </li>
          <li>
            Include your <LegalStrong>registered email address</LegalStrong> and your{" "}
            <LegalStrong>Razorpay payment reference</LegalStrong> or order ID.
          </li>
          <li>We aim to respond within <LegalStrong>three (3) business days</LegalStrong>.</li>
          <li>
            Approved refunds are typically processed within{" "}
            <LegalStrong>five (5) to seven (7) business days</LegalStrong> through the original
            payment method, subject to Razorpay and banking timelines.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="5. Cancellation">
        <ul className="list-disc space-y-2 pl-5">
          <li>You may cancel your subscription at any time; <LegalStrong>no cancellation fee</LegalStrong> applies.</li>
          <li>
            Access generally continues until the end of the <LegalStrong>current paid billing month</LegalStrong>.
          </li>
          <li>
            We do not refund fees for unused days within the current billing period after you cancel, except where
            this Refund Policy expressly permits (for example, an approved refund under Section 3).
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="6. Contact">
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
