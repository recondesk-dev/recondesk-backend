import type { Metadata } from "next";
import { LandingNavbar } from "@/components/landing/LandingNavbar";
import { LandingFooter } from "@/components/landing/LandingFooter";

export const metadata: Metadata = {
  title: "ReconDesk — Intelligent Solutions Powered by AI",
  description:
    "GSTR-2B reconciliation decision engine for CA firms. 5-level invoice matching, Rule 37 tracking, and automated ITC optimization.",
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-white text-[#0A0A0A] selection:bg-[#F97316]/20 selection:text-[#0A0A0A]">
      <LandingNavbar />
      <main className="min-w-0">{children}</main>
      <LandingFooter />
    </div>
  );
}
