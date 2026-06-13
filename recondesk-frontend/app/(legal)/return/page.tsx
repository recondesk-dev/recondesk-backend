import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Return Policy — ReconDesk",
  description: "Return Policy for ReconDesk GST reconciliation software. ReconDesk is a digital SaaS product with no physical goods.",
};

export default function ReturnPage() {
  return (
    <LegalPage title="Return Policy">
      <LegalSection title="1. Overview">
        <p>
          ReconDesk is a <LegalStrong>digital software-as-a-service (SaaS)</LegalStrong> product that
          provides GST reconciliation tools for Chartered Accountant (CA) firms in India. The service is
          delivered entirely online through recondesk.in.
        </p>
        <p>
          Because ReconDesk is a <LegalStrong>purely digital product</LegalStrong> with{" "}
          <LegalStrong>no physical goods</LegalStrong>, there are{" "}
          <LegalStrong>no physical items to return</LegalStrong>. This policy explains what
          &quot;return&quot; means in the context of a software subscription, and how cancellations and
          refunds are handled.
        </p>
      </LegalSection>

      <LegalSection title="2. No Physical Returns">
        <p>
          ReconDesk does not sell, ship, or deliver any physical products. All features and outputs
          (reconciliation runs, reports, exports) are provided digitally through your online account.
          Accordingly, the concept of a physical &quot;return&quot; does not apply to ReconDesk
          subscriptions.
        </p>
      </LegalSection>

      <LegalSection title="3. Subscription Cancellation (&quot;Digital Return&quot;)">
        <p>
          In the context of a SaaS subscription, &quot;returning&quot; the product means{" "}
          <LegalStrong>cancelling your subscription access</LegalStrong>. You may cancel at any time:
        </p>
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <LegalStrong>No cancellation fee</LegalStrong> applies. You may stop your subscription at
            any time without penalty.
          </li>
          <li>
            Access to the Service continues until the end of your{" "}
            <LegalStrong>current paid billing month</LegalStrong>, after which your subscription will
            not renew.
          </li>
          <li>
            We do not refund fees for unused days within the current billing period after cancellation,
            except where our{" "}
            <Link href="/refund" className="font-medium text-brand hover:underline">
              Refund Policy
            </Link>{" "}
            expressly permits (for example, a refund request within 48 hours with no runs consumed).
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="4. Refund Terms">
        <p>
          All refund eligibility criteria, timelines, and procedures are governed by our{" "}
          <Link href="/refund" className="font-medium text-brand hover:underline">
            Refund Policy
          </Link>
          . Please refer to that page for full details on when refunds are available and how to request
          them.
        </p>
      </LegalSection>

      <LegalSection title="5. How to Request a Cancellation or Refund">
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
            <LegalStrong>PhonePe / Razorpay payment reference</LegalStrong> or order ID.
          </li>
          <li>
            We aim to respond within <LegalStrong>three (3) business days</LegalStrong>.
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
        <p>
          <LegalStrong>Address:</LegalStrong> Hadapsar, Pune, Maharashtra, India
        </p>
        <p className="text-[#6B6B6B]">
          <LegalStrong>Last updated:</LegalStrong> May 2026
        </p>
        <p className="text-[#6B6B6B]">
          <LegalStrong>Effective date:</LegalStrong> May 2026
        </p>
      </LegalSection>
    </LegalPage>
  );
}
