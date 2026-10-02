"use client";

import { usePathname } from "next/navigation";
import { LandingNavbar } from "./LandingNavbar";
import { LandingFooter } from "./LandingFooter";
import "./modern-home.css";
import "./studio-home.css";

/** The homepage theme is scoped so app and article styles keep their own context. */
export function LandingFrame({ children }: { children: React.ReactNode }) {
  const isHome = usePathname() === "/";
  return (
    <div className={isHome ? "rd-modern rd-studio min-h-screen" : "rd-public dashboard-soft-bg min-h-screen text-[#0A0A0A] selection:bg-[#F97316]/20 selection:text-[#0A0A0A]"}>
      {isHome && <a className="studio-skip-link" href="#main-content">Skip to content</a>}
      <LandingNavbar />
      <main id="main-content" tabIndex={-1} className="min-w-0">{children}</main>
      <LandingFooter />
    </div>
  );
}
