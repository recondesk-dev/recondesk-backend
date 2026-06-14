import type { Metadata } from "next";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Refund and Cancellation Policy | ReconDesk",
  description:
    "Refund and cancellation policy for ReconDesk GST reconciliation subscriptions. Learn how to cancel your plan or request a refund.",
};

export default function RefundPage() {
  return (
    <LegalPage title="Refund and Cancellation Policy" lastUpdated="June 2026">
      <LegalSection title="Overview">
        <p>
          This Refund and Cancellation Policy outlines how you can cancel your ReconDesk
          subscription or request a refund for the service purchased through the Platform.
        </p>
      </LegalSection>

      <LegalSection title="Cancellations">
        <p>
          You may cancel your subscription at any time from your account dashboard. Cancellation
          will stop future renewals; access to paid features will continue until the end of the
          current billing cycle, after which your account will revert to the free/limited plan.
        </p>
      </LegalSection>

      <LegalSection title="Refund Requests">
        <p>
          Refund requests must be raised within{" "}
          <LegalStrong>2 days of the payment date</LegalStrong>. To request a refund, please
          contact our support team with your registered email and payment details.
        </p>
      </LegalSection>

      <LegalSection title="Eligibility for Refunds">
        <p>
          Refunds may be considered in cases such as:
        </p>
        <ul className="list-disc space-y-2 pl-5">
          <li>Duplicate payments</li>
          <li>
            Technical issues preventing access to the service that our team is unable to resolve
          </li>
          <li>Incorrect billing</li>
        </ul>
        <p>
          Refunds are <LegalStrong>not provided</LegalStrong> for partial use of a billing cycle,
          change of mind after using the service, or failure to cancel before renewal.
        </p>
      </LegalSection>

      <LegalSection title="Processing Time">
        <p>
          Approved refunds will be processed within{" "}
          <LegalStrong>7 working days</LegalStrong> to the original payment method.
        </p>
      </LegalSection>

      <LegalSection title="Contact Us">
        <p>
          For any cancellation or refund requests, please reach out to:
        </p>
        <p>
          <LegalStrong>Phone:</LegalStrong>{" "}
          <a href="tel:+918605035248" className="font-medium text-brand hover:underline">
            8605035248
          </a>
        </p>
        <p>
          <LegalStrong>Email:</LegalStrong>{" "}
          <a
            href="mailto:contact@recondesk.in?subject=Refund%20Request"
            className="font-medium text-brand hover:underline"
          >
            contact@recondesk.in
          </a>
        </p>
      </LegalSection>
    </LegalPage>
  );
}
