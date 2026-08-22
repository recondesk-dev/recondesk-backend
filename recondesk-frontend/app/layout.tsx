import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Space_Mono } from "next/font/google";

import { ClarityScript } from "@/components/ClarityScript";
import { KeepAlive } from "@/components/KeepAlive";
import { RootProviders } from "@/components/providers/RootProviders";

import "./globals.css";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plus-jakarta",
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
    <html lang="en" className={`${jakarta.variable} ${spaceMono.variable} scroll-smooth`}>
      <head>
        {/* General Sans — display font for landing page headlines */}
        <link
          href="https://api.fontshare.com/v2/css?f[]=general-sans@200,300,400,500,600,700&display=swap"
          rel="stylesheet"
        />
        <style
          dangerouslySetInnerHTML={{
            __html: `:root { --font-general-sans: 'General Sans', sans-serif; }`,
          }}
        />
      </head>
      <body className={`${jakarta.className} min-w-0 font-sans antialiased`}>
        <RootProviders>{children}</RootProviders>
        <KeepAlive />
        <ClarityScript />
      </body>
    </html>
  );
}
