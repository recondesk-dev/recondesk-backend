import type { Metadata } from "next";

import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicNavbar } from "@/components/public/PublicNavbar";

export const metadata: Metadata = {
  title: "ReconDesk — GSTR-2B reconciliation for CA firms",
  description:
    "Find missed ITC every month. Upload GSTR-2B + purchase register. 5-level matching, decision-ready results for CA firms.",
};

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen min-w-0 bg-[#0f1117] text-slate-100 antialiased">
      <PublicNavbar />
      <main className="min-w-0">{children}</main>
      <PublicFooter />
    </div>
  );
}
