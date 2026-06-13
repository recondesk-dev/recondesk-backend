import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Shipping & Returns — ReconDesk",
  description: "Shipping and Returns policy for ReconDesk GST reconciliation software. ReconDesk is a digital SaaS product with no physical goods or shipping.",
};

export default function ShippingReturnsPage() {
  return (
    <LegalPage title="Shipping & Returns">
      <LegalSection title="1. No Physical Products">
        <p>
          ReconDesk is a <LegalStrong>software-as-a-service (SaaS)</LegalStrong> platform that
          provides GST reconciliation tools for Chartered Accountant firms. We do not sell, ship, or
          deliver any physical goods.
        </p>
      </LegalSection>

      <LegalSection title="2. Shipping">
        <p>
          As ReconDesk is a <LegalStrong>fully digital service</LegalStrong>, no shipping is
          involved. Upon successful subscription payment, your account is activated immediately and
          you can access the Service online at{" "}
          <LegalStrong>recondesk.in</LegalStrong>.
        </p>
      </LegalSection>

      <LegalSection title="3. Returns">
        <p>
          Since no physical product is shipped or delivered, there is no return process for the
          Service. If you wish to cancel your subscription or request a refund, please refer to our{" "}
          <Link href="/refund" className="font-medium text-brand hover:underline">
            Refund Policy
          </Link>{" "}
          for eligibility and process details.
        </p>
      </LegalSection>

      <LegalSection title="4. Contact">
        <p>
          For any questions, email{" "}
          <a
            href="mailto:contact@recondesk.in"
            className="font-medium text-brand hover:underline"
          >
            contact@recondesk.in
          </a>
          .
        </p>
        <p className="text-[#6B6B6B]">
          <LegalStrong>Effective date:</LegalStrong> May 2026
        </p>
      </LegalSection>
    </LegalPage>
  );
}
