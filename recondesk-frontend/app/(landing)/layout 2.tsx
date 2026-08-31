import type { Metadata } from "next";

import { MarketingPageLayout } from "@/components/layout/MarketingPageLayout";

export const metadata: Metadata = {
  title: "ReconDesk — GSTR-2B reconciliation for CA firms",
  description:
    "Find missed ITC every month. Upload GSTR-2B + purchase register. 5-level matching, decision-ready results for CA firms.",
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <MarketingPageLayout className="landing-page overflow-x-hidden">{children}</MarketingPageLayout>
  );
}
