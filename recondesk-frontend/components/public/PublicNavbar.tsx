"use client";

import { useState } from "react";
import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { Menu, X } from "lucide-react";

type PublicNavbarProps = {
  theme?: "dark" | "light" | "ledger";
};

export function PublicNavbar({ theme = "dark" }: PublicNavbarProps) {
  const isLight = theme === "light";
  const isLedger = theme === "ledger";
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const linkClass = isLedger
    ? "font-mono text-[12px] tracking-wide text-[#4A5C6E] transition hover:text-[#0B1D33]"
    : isLight
      ? "text-sm font-medium text-[#3A3A3A] transition hover:text-[#0A0A0A]"
      : "text-sm font-medium text-slate-300 transition hover:text-white";

  const mobileLinkClass = isLedger
    ? "block border-b border-[#D4D9E0] px-1 py-3 font-mono text-sm text-[#0B1D33]"
    : isLight
      ? "block rounded-lg px-3 py-3 text-base font-medium text-[#3A3A3A] transition hover:bg-[#F5F5F5] hover:text-[#0A0A0A]"
      : "block rounded-lg px-3 py-3 text-base font-medium text-slate-300 transition hover:bg-white/5 hover:text-white";

  const ctaClass = isLedger
    ? "inline-flex min-h-[40px] items-center justify-center border border-[#0D4F3C] bg-[#0D4F3C] px-4 font-mono text-[12px] font-medium tracking-wide text-white transition hover:bg-[#0A3F30]"
    : "inline-flex min-h-[40px] items-center justify-center rounded-full bg-brand px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-hover";

  const headerClass = isLedger
    ? "sticky top-0 z-50 border-b border-[#D4D9E0] bg-[#F2F3F5]/95 backdrop-blur-sm"
    : isLight
      ? "sticky top-0 z-50 border-b border-[#E5E5E5] bg-white"
      : "sticky top-0 z-50 border-b border-white/10 bg-[#0a0c10]/85 backdrop-blur-md";

  return (
    <header className={headerClass}>
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className={`font-brand inline-flex shrink-0 items-baseline gap-0 font-bold tracking-tight ${
            isLedger || isLight ? "text-[#0B1D33]" : "text-white"
          }`}
          onClick={() => setMobileMenuOpen(false)}
        >
          <Logo width={210} height={40} />
        </Link>

        {isLight || isLedger ? (
          <>
            <nav className="hidden items-center gap-6 sm:flex">
              <Link href="/pricing" className={linkClass}>
                Pricing
              </Link>
              <Link href="/auth/login" className={linkClass}>
                Login
              </Link>
              <Link href="/auth/signup" className={ctaClass}>
                Start Free
              </Link>
            </nav>

            <button
              type="button"
              className={
                isLedger
                  ? "inline-flex min-h-[44px] min-w-[44px] items-center justify-center border border-[#0B1D33]/25 text-[#0B1D33] sm:hidden"
                  : "inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full border border-[#E5E5E5] text-[#0A0A0A] sm:hidden"
              }
              aria-expanded={mobileMenuOpen}
              aria-controls="landing-mobile-nav"
              aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
              onClick={() => setMobileMenuOpen((open) => !open)}
            >
              {mobileMenuOpen ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
            </button>
          </>
        ) : (
          <nav className="flex items-center gap-3 sm:gap-6">
            <Link href="/pricing" className={linkClass}>
              Pricing
            </Link>
            <Link href="/auth/login" className={linkClass}>
              Login
            </Link>
            <Link href="/auth/signup" className={ctaClass}>
              Start Free
            </Link>
          </nav>
        )}
      </div>

      {(isLight || isLedger) && mobileMenuOpen ? (
        <nav
          id="landing-mobile-nav"
          className={
            isLedger
              ? "border-t border-[#D4D9E0] bg-[#F2F3F5] px-4 py-3 sm:hidden"
              : "border-t border-[#E5E5E5] px-4 py-3 sm:hidden"
          }
        >
          <div className="flex flex-col gap-1">
            <Link href="/pricing" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>
              Pricing
            </Link>
            <Link href="/auth/login" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>
              Login
            </Link>
            <Link
              href="/auth/signup"
              className={`mt-3 ${ctaClass} w-full`}
              onClick={() => setMobileMenuOpen(false)}
            >
              Start Free
            </Link>
          </div>
        </nav>
      ) : null}
    </header>
  );
}
