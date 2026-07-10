import type { Metadata } from "next";
import { Fraunces, JetBrains_Mono } from "next/font/google";

import { MarketingPageLayout } from "@/components/layout/MarketingPageLayout";

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-fraunces",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ReconDesk — Every invoice needs a judgment call",
  description:
    "GSTR-2B reconciliation with decision intelligence for CA firms. Claim, hold, or dispute — not just match.",
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={`${fraunces.variable} ${jetbrains.variable}`}>
      <MarketingPageLayout theme="ledger" className="landing-page landing-ledger overflow-x-hidden">
        {children}
      </MarketingPageLayout>
    </div>
  );
}
