import type { Metadata } from "next";

import { MarketingPageLayout } from "@/components/layout/MarketingPageLayout";

export const metadata: Metadata = {
  title: "ReconDesk — GST reconciliation with a Decision Layer for CA firms",
  description:
    "Upload two files. Get five-level matching plus WHAT / WHY / NEXT on every invoice — Rule 37, Section 17(5), and Audit Observations included. No Tally bridge required.",
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <MarketingPageLayout className="landing-page overflow-x-hidden">{children}</MarketingPageLayout>
  );
}
