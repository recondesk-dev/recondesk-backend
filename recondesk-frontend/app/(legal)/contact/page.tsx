import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Contact — ReconDesk",
  description: "Contact ReconDesk for support, billing, refunds, and enterprise enquiries.",
};

export default function ContactPage() {
  return (
    <LegalPage title="Contact">
      <LegalSection title="Get in touch">
        <p>
          For product support, billing questions, refund requests, or enterprise plans, email us
          and we will respond within <LegalStrong>three (3) business days</LegalStrong>.
        </p>
      </LegalSection>

      <LegalSection title="Email">
        <p>
          <a
            href="mailto:contact@recondesk.in"
            className="font-medium text-brand hover:underline"
          >
            contact@recondesk.in
          </a>
        </p>
        <p className="text-[#6B6B6B]">
          For refund requests, use the subject line <LegalStrong>&quot;Refund Request&quot;</LegalStrong> and
          include your registered email and Razorpay payment reference.
        </p>
      </LegalSection>

      <LegalSection title="Phone">
        <p>
          <a
            href="tel:+918605035248"
            className="font-medium text-brand hover:underline"
          >
            +91 86050 35248
          </a>
        </p>
      </LegalSection>

      <LegalSection title="Operator">
        <p>
          <LegalStrong>Omkar Rajendra Kadam</LegalStrong> (sole proprietorship)
        </p>
        <p>
          <LegalStrong>Address:</LegalStrong> Hadapsar, Pune, Maharashtra, India
        </p>
      </LegalSection>

      <LegalSection title="Policies">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <Link href="/privacy" className="font-medium text-brand hover:underline">
              Privacy Policy
            </Link>
          </li>
          <li>
            <Link href="/terms" className="font-medium text-brand hover:underline">
              Terms of Service
            </Link>
          </li>
          <li>
            <Link href="/refund" className="font-medium text-brand hover:underline">
              Refund Policy
            </Link>
          </li>
        </ul>
      </LegalSection>
    </LegalPage>
  );
}
