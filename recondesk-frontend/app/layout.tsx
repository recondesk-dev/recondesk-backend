import type { Metadata } from "next";
import { DM_Sans, Space_Mono } from "next/font/google";

import { RootProviders } from "@/components/providers/RootProviders";

import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-dm-sans",
  display: "swap",
});

const spaceMono = Space_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-space-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ReconDesk",
  description: "Reconciliation decision engine for CA firms",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${dmSans.variable} ${spaceMono.variable}`}>
      <body className="min-w-[1280px] font-sans antialiased">
        <RootProviders>{children}</RootProviders>
      </body>
    </html>
  );
}
