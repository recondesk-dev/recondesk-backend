import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ReconDesk — GSTR-2B reconciliation for CA firms",
  description:
    "Two files in. Clear decisions out. Upload GSTR-2B + Purchase Register. 5-level matching, decision-ready results, and direct filing for CA firms.",
  openGraph: {
    title: "ReconDesk — GSTR-2B reconciliation for CA firms",
    description:
      "Two files in. Clear decisions out. 5-level matching, Rule 37/17(5) reasoning, vendor risk scoring, and direct GSTR-1/3B filing.",
    siteName: "ReconDesk",
    type: "website",
  },
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-w-0 overflow-x-hidden" style={{ backgroundColor: '#0A0A0B' }}>
      {children}
    </main>
  );
}
