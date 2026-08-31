import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ReconDesk — Reconciliation that just works",
  description:
    "See how ReconDesk eliminates GSTR-2B reconciliation pain for CA firms. An interactive story.",
};

export default function StoryLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // Full-screen canvas — no sidebar, no header
    <div className="isolate">{children}</div>
  );
}
