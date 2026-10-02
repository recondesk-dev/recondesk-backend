import type { Metadata } from "next";
import { LandingFrame } from "@/components/landing/LandingFrame";


export const metadata: Metadata = {
  title: "ReconDesk — Intelligent Solutions Powered by AI",
  description:
    "GSTR-2B reconciliation decision engine for CA firms. 5-level invoice matching, Rule 37 tracking, and automated ITC optimization.",
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return <LandingFrame>{children}</LandingFrame>;
}
