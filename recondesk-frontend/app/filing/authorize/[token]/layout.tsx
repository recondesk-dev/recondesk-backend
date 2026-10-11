import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ReconDesk Client Return Review & Authorization",
  referrer: "no-referrer",
  robots: {
    index: false,
    follow: false,
  },
};

export default function ClientAuthorizeLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
