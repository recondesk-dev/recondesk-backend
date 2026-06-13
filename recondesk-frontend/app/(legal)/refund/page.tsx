import type { Metadata } from "next";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Refund & Cancellation Policy — ReconDesk",
  description: "Refund and cancellation policy for ReconDesk GST reconciliation subscriptions.",
};

export default function RefundPage() {
  return (
    <LegalPage title="Refund & Cancellation Policy">
      <LegalSection title="Overview">
        <p>
          This refund and cancellation policy outlines how you can cancel your ReconDesk subscription
          or request a refund.
        </p>
        <ol className="list-decimal space-y-3 pl-5">
          <li>
            Cancellation requests will only be considered if made within{" "}
            <LegalStrong>2 days</LegalStrong> of the subscription payment, and only if{" "}
            <LegalStrong>no reconciliation runs</LegalStrong> have been consumed in that billing cycle.
          </li>
          <li>
            If you experience a technical issue on ReconDesk&apos;s end that prevents you from using
            the Service despite a valid subscription, please report it to our customer service team
            within <LegalStrong>2 days</LegalStrong>. The team will review and take an appropriate
            decision, which may include a{" "}
            <LegalStrong>run credit</LegalStrong> or <LegalStrong>refund</LegalStrong>.
          </li>
          <li>
            In case of any refund approved by <LegalStrong>RECONDESK</LegalStrong>, it will take{" "}
            <LegalStrong>7 days</LegalStrong> for the refund to be processed to you.
          </li>
        </ol>
      </LegalSection>

      <LegalSection title="How to Request a Refund">
        <p>
          Email{" "}
          <a
            href="mailto:contact@recondesk.in?subject=Refund%20Request"
            className="font-medium text-brand hover:underline"
          >
            contact@recondesk.in
          </a>{" "}
          with the subject line <LegalStrong>&quot;Refund Request&quot;</LegalStrong>, including your
          registered email and payment reference.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
